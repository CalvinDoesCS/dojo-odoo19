"""
cors.py
───────
OPTIONS preflight handler for all /bridge/v1/* routes.

Next.js (and any browser client) will send a preflight OPTIONS request
before any cross-origin POST/PUT/DELETE. This controller handles those
centrally so every route doesn't need its own OPTIONS route.

Allowed origins are read from ir.config_parameter x_bridge.cors_origins
(comma-separated). If unconfigured, the origin is reflected back
(development convenience — tighten this in production).
"""
import json
import logging

import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

_CORS_METHODS = "GET, POST, DELETE, OPTIONS"
_CORS_HEADERS_ALLOWED = (
    "Authorization, Content-Type, X-Bridge-Signature, X-Requested-With"
)
_CORS_MAX_AGE = "86400"  # 24 h


def _get_allowed_origins(env) -> list[str]:
    try:
        from ..models.bridge_config import BridgeConfig
        params = env["ir.config_parameter"].sudo()
        return BridgeConfig.cors_origins(params)
    except Exception:
        return []


def _cors_headers(origin: str, allowed_origins: list[str]) -> list[tuple[str, str]]:
    """
    Build CORS response headers.
    If allowed_origins is empty (dev/unconfigured), reflect the request origin.
    """
    if not allowed_origins or origin in allowed_origins:
        allow_origin = origin
    else:
        allow_origin = allowed_origins[0]  # fallback — should result in a CORS error

    return [
        ("Access-Control-Allow-Origin", allow_origin),
        ("Access-Control-Allow-Methods", _CORS_METHODS),
        ("Access-Control-Allow-Headers", _CORS_HEADERS_ALLOWED),
        ("Access-Control-Allow-Credentials", "true"),
        ("Access-Control-Max-Age", _CORS_MAX_AGE),
        ("Vary", "Origin"),
    ]


class BridgeCorsController(http.Controller):

    @http.route(
        "/bridge/v1/<path:subpath>",
        type="http",
        auth="public",
        methods=["OPTIONS"],
        csrf=False,
    )
    def bridge_cors_preflight(self, subpath="", **kw):
        """Handle all OPTIONS preflight requests under /bridge/v1/."""
        origin = request.httprequest.headers.get("Origin", "*")

        # We need a DB connection to load the allowed origins config.
        # Use the current DB from dbfilter; if unavailable, reflect origin.
        db_name = request.db
        if db_name:
            try:
                registry = Registry(db_name)
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    allowed_origins = _get_allowed_origins(env)
            except Exception:
                allowed_origins = []
        else:
            allowed_origins = []

        headers = _cors_headers(origin, allowed_origins)
        return Response("", status=204, headers=headers)


def add_cors_headers(response: Response, origin: str, allowed_origins: list[str]) -> Response:
    """
    Utility used by all bridge controllers to add CORS headers to responses.
    Import and call from each controller's response path.
    """
    for key, value in _cors_headers(origin, allowed_origins):
        response.headers[key] = value
    return response
