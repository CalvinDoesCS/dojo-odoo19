"""
bridge_webhook.py
─────────────────
x.bridge.webhook.handler — AbstractModel that processes typed events
pushed from the NestJS Control Plane to POST /bridge/v1/webhooks/event.

Each event_type maps to a dispatch_<event_type> method.
Unknown event types are logged and gracefully ignored (returns a 200 so
NestJS doesn't retry indefinitely on genuinely unhandled events).

Supported events:
  subscription.created       → create/activate dojo.member.subscription
  subscription.cancelled     → cancel dojo.member.subscription
  member.firebase_uid_linked → link firebase_uid to existing dojo.member
  payment.succeeded          → log payment reference on member subscription
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BridgeWebhookHandler(models.AbstractModel):
    _name = "x.bridge.webhook.handler"
    _description = "Bridge Webhook Event Dispatcher"

    # ── dispatch router ───────────────────────────────────────────────────────

    @api.model
    def dispatch(self, event_type: str, payload: dict, company_id: int) -> dict:
        """
        Route an inbound webhook event to the matching handler method.
        Always returns a dict; callers should commit the cursor on success.
        """
        method_name = "dispatch_" + event_type.replace(".", "_")
        handler = getattr(self, method_name, None)

        if handler is None:
            _logger.warning(
                "Bridge webhook: no handler for event_type=%r — ignoring",
                event_type,
            )
            return {"accepted": False, "reason": f"Unknown event type: {event_type}"}

        _logger.info("Bridge webhook: dispatching event_type=%r", event_type)
        try:
            result = handler(payload, company_id)
            return {"accepted": True, "event_type": event_type, **(result or {})}
        except UserError as exc:
            _logger.error(
                "Bridge webhook: UserError in %s: %s", method_name, exc
            )
            return {"accepted": False, "reason": str(exc)}

    # ── individual handlers ───────────────────────────────────────────────────

    @api.model
    def dispatch_subscription_created(
        self, payload: dict, company_id: int
    ) -> dict:
        """
        Expected payload keys:
          firebase_uid   – used to resolve identity → member
          plan_id        – dojo.subscription.plan id
          start_date     – ISO date string (optional)
          external_id    – Control Plane's subscription reference (optional)
        """
        member = self._resolve_member_from_payload(payload, company_id)
        plan_id = payload.get("plan_id")

        if not plan_id:
            raise UserError("subscription.created requires 'plan_id'")

        plan = self.env["dojo.subscription.plan"].search(
            [("id", "=", plan_id), ("company_id", "=", company_id)], limit=1
        )
        if not plan:
            raise UserError(f"Plan {plan_id} not found in company {company_id}")

        start_date = payload.get("start_date")
        vals = {
            "member_id": member.id,
            "plan_id": plan.id,
            "company_id": company_id,
            "state": "active",
        }
        if start_date:
            vals["start_date"] = start_date

        sub = self.env["dojo.member.subscription"].create(vals)
        _logger.info(
            "Bridge webhook: created subscription_id=%s for member_id=%s",
            sub.id,
            member.id,
        )
        return {"subscription_id": sub.id}

    @api.model
    def dispatch_subscription_cancelled(
        self, payload: dict, company_id: int
    ) -> dict:
        """
        Expected payload keys:
          subscription_id  – dojo.member.subscription id   (preferred)
          firebase_uid     – fallback if subscription_id not given
        """
        sub_id = payload.get("subscription_id")
        if sub_id:
            sub = self.env["dojo.member.subscription"].search(
                [("id", "=", sub_id), ("company_id", "=", company_id)], limit=1
            )
        else:
            member = self._resolve_member_from_payload(payload, company_id)
            sub = self.env["dojo.member.subscription"].search(
                [
                    ("member_id", "=", member.id),
                    ("company_id", "=", company_id),
                    ("state", "=", "active"),
                ],
                order="create_date desc",
                limit=1,
            )

        if not sub:
            raise UserError("No matching active subscription found to cancel.")

        sub.write({"state": "cancelled"})
        _logger.info("Bridge webhook: cancelled subscription_id=%s", sub.id)
        return {"subscription_id": sub.id, "state": "cancelled"}

    @api.model
    def dispatch_member_firebase_uid_linked(
        self, payload: dict, company_id: int
    ) -> dict:
        """
        Explicitly link a firebase_uid to an existing dojo.member.
        Useful when the Control Plane creates the Firebase account after
        the member record already exists in Odoo.

        Expected payload keys:
          firebase_uid  – new Firebase UID
          member_id     – existing dojo.member id
          email         – Firebase account email (optional, cached on identity)
        """
        firebase_uid = payload.get("firebase_uid")
        member_id = payload.get("member_id")

        if not firebase_uid or not member_id:
            raise UserError(
                "member.firebase_uid_linked requires 'firebase_uid' and 'member_id'"
            )

        member = self.env["dojo.member"].search(
            [("id", "=", member_id), ("company_id", "=", company_id)], limit=1
        )
        if not member:
            raise UserError(
                f"Member {member_id} not found in company {company_id}"
            )

        identity = self.env["x.bridge.identity"].search(
            [
                ("firebase_uid", "=", firebase_uid),
                ("company_id", "=", company_id),
            ],
            limit=1,
        )

        if identity:
            if identity.member_id and identity.member_id.id != member_id:
                raise UserError(
                    f"Firebase UID {firebase_uid} is already linked to a different member."
                )
            identity.write(
                {
                    "member_id": member_id,
                    "is_active": True,
                    "firebase_email": payload.get("email") or identity.firebase_email,
                }
            )
        else:
            identity = self.env["x.bridge.identity"].create(
                {
                    "firebase_uid": firebase_uid,
                    "company_id": company_id,
                    "member_id": member_id,
                    "firebase_email": payload.get("email"),
                    "is_active": True,
                }
            )

        _logger.info(
            "Bridge webhook: linked firebase_uid=%s to member_id=%s (identity_id=%s)",
            firebase_uid,
            member_id,
            identity.id,
        )
        return {"identity_id": identity.id, "member_id": member_id}

    @api.model
    def dispatch_payment_succeeded(self, payload: dict, company_id: int) -> dict:
        """
        Log a successful payment against a member subscription.

        Expected payload keys:
          subscription_id      – dojo.member.subscription id
          amount               – float (the amount charged)
          currency             – 3-letter code, e.g. "USD"
          external_payment_id  – Control Plane / Stripe payment reference
          payment_date         – ISO datetime (optional, defaults to now)
        """
        sub_id = payload.get("subscription_id")
        if not sub_id:
            raise UserError("payment.succeeded requires 'subscription_id'")

        sub = self.env["dojo.member.subscription"].search(
            [("id", "=", sub_id), ("company_id", "=", company_id)], limit=1
        )
        if not sub:
            raise UserError(
                f"Subscription {sub_id} not found in company {company_id}"
            )

        # Post a chatter note so the payment is visible in the Odoo UI.
        external_id = payload.get("external_payment_id", "N/A")
        amount = payload.get("amount", 0)
        currency = payload.get("currency", "")
        payment_date = payload.get("payment_date") or fields.Datetime.now()

        message = (
            f"✅ Payment received via Control Plane\n"
            f"Amount: {amount} {currency}\n"
            f"External ref: {external_id}\n"
            f"Date: {payment_date}"
        )
        sub.message_post(body=message, subtype_xmlid="mail.mt_note")

        _logger.info(
            "Bridge webhook: payment_succeeded for subscription_id=%s amount=%s %s",
            sub_id,
            amount,
            currency,
        )
        return {"subscription_id": sub_id, "logged": True}

    # ── private ───────────────────────────────────────────────────────────────

    @api.model
    def _resolve_member_from_payload(self, payload: dict, company_id: int):
        """
        Resolve dojo.member from payload using firebase_uid → x.bridge.identity.
        Raises UserError if the identity or member cannot be resolved.
        """
        firebase_uid = payload.get("firebase_uid")
        if not firebase_uid:
            raise UserError("Payload must contain 'firebase_uid' for member resolution.")

        identity = self.env["x.bridge.identity"].search(
            [
                ("firebase_uid", "=", firebase_uid),
                ("company_id", "=", company_id),
                ("is_active", "=", True),
            ],
            limit=1,
        )
        if not identity or not identity.member_id:
            raise UserError(
                f"No active identity with a linked member found for "
                f"firebase_uid={firebase_uid} in company {company_id}."
            )
        return identity.member_id
