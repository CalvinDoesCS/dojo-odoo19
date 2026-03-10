"""
webhook_routes.py
─────────────────
POST /bridge/v1/webhooks/event — inbound events from the NestJS Control Plane.

Authentication
──────────────
Does NOT use @require_bridge_auth (which requires an existing user identity).
Instead, uses HMAC-SHA256 request signing:

  X-Bridge-Signature: sha256=<hex_digest>

Where the digest is computed over the raw request body using the value of
ir.config_parameter `x_bridge.webhook_secret` as the key.

This is the same pattern used by Stripe, GitHub, and Twilio webhooks —
the payload authenticity is guaranteed by the shared secret without needing
a per-user identity.

Supported event types (see bridge_webhook.py for implementations):
  subscription.created
  subscription.cancelled
  member.firebase_uid_linked
  payment.succeeded
"""
import hashlib
import hmac
import json
import logging

import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry
from odoo import http
from odoo.http import request, Response

from .auth_middleware import bridge_response, bridge_error, _service_error

_logger = logging.getLogger(__name__)


class BridgeWebhookController(http.Controller):

    @http.route(
        "/bridge/v1/webhooks/event",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def ingest_event(self, **kw):
        """
        Ingest a typed event from the Control Plane.

        Body (JSON):
          {
            "event_type": "subscription.created",
            "tenant_db":  "odoo19",
            "company_id": 1,
            "payload":    { ... event-specific fields ... }
          }

        Headers:
          X-Bridge-Signature: sha256=<hmac_hex>
          Content-Type: application/json
        """
        if request.httprequest.method == "OPTIONS":
            from .auth_middleware import _options_response
            return _options_response()

        origin = request.httprequest.headers.get("Origin", "")
        raw_body = request.httprequest.get_data()

        # ── 1. Parse JSON body ─────────────────────────────────────────────
        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return bridge_error("Request body must be valid JSON.", status=400)

        tenant_db = body.get("tenant_db") or body.get("tenant_id")
        company_id = body.get("company_id")
        event_type = body.get("event_type")
        payload = body.get("payload", {})

        if not tenant_db:
            return bridge_error("Missing 'tenant_db' in request body.", status=400)
        if not event_type:
            return bridge_error("Missing 'event_type' in request body.", status=400)
        if not company_id:
            return bridge_error("Missing 'company_id' in request body.", status=400)

        try:
            company_id = int(company_id)
        except (TypeError, ValueError):
            return bridge_error("'company_id' must be an integer.", status=400)

        # ── 2. Open tenant DB ──────────────────────────────────────────────
        try:
            registry = Registry(tenant_db)
        except Exception:
            return bridge_error(f"Unknown tenant '{tenant_db}'.", status=403)

        try:
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                params = env["ir.config_parameter"].sudo()

                from ..models.bridge_config import BridgeConfig

                # ── 3. Verify HMAC signature ───────────────────────────────
                webhook_secret = BridgeConfig.webhook_secret(params)
                if webhook_secret:
                    sig_header = request.httprequest.headers.get(
                        "X-Bridge-Signature", ""
                    )
                    if not _verify_signature(raw_body, sig_header, webhook_secret):
                        _logger.warning(
                            "Bridge webhook: invalid signature for event_type=%r",
                            event_type,
                        )
                        return bridge_error("Invalid webhook signature.", status=401)
                else:
                    _logger.warning(
                        "Bridge webhook: x_bridge.webhook_secret not configured — "
                        "signature verification SKIPPED. Set this in production!"
                    )

                # ── 4. Verify company exists ───────────────────────────────
                company = env["res.company"].browse(company_id).exists()
                if not company:
                    return bridge_error(
                        f"Company {company_id} not found in tenant '{tenant_db}'.",
                        status=403,
                    )

                # ── 5. Dispatch to handler ─────────────────────────────────
                handler = env["x.bridge.webhook.handler"].sudo()
                result = handler.dispatch(event_type, payload, company_id)

                if result.get("accepted"):
                    cr.commit()
                    _logger.info(
                        "Bridge webhook: accepted event_type=%r result=%s",
                        event_type,
                        result,
                    )
                else:
                    _logger.warning(
                        "Bridge webhook: not accepted event_type=%r reason=%s",
                        event_type,
                        result.get("reason"),
                    )

        except Exception as exc:
            _logger.exception("Bridge webhook unexpected error: %s", exc)
            return _service_error(f"Unexpected error: {exc}")

        resp = bridge_response(result)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp


# ──────────────────────────────────────────────────────────────────────────────
# HMAC helpers
# ──────────────────────────────────────────────────────────────────────────────

def _verify_signature(body: bytes, sig_header: str, secret: str) -> bool:
    """
    Verify the X-Bridge-Signature header.
    Format: "sha256=<hex_digest>"
    Uses hmac.compare_digest to prevent timing attacks.
    """
    if not sig_header.startswith("sha256="):
        return False

    received_digest = sig_header[7:]  # strip "sha256=" prefix

    expected_digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_digest, received_digest)
