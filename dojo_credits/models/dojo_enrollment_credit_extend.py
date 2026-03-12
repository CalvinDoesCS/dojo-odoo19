"""
Credit hooks on dojo.class.enrollment:

create():
  When status='registered', find the member's active subscription that covers
  the session's program, lock the subscription row, verify balance, and place
  a 'hold' transaction.

write({'status': 'cancelled'}):
  Find the pending hold for each cancelled enrollment.
  • If cancelled > CANCEL_REFUND_HOURS before session start → release hold (status='cancelled')
  • If within window (or session already passed) → confirm hold (credit consumed)
"""
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .dojo_credit_transaction import CANCEL_REFUND_HOURS

_logger = logging.getLogger(__name__)


class DojoClassEnrollmentCreditExtend(models.Model):
    _inherit = "dojo.class.enrollment"

    # ── Create: place hold ───────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for enrollment in records:
            if enrollment.status != "registered":
                continue
            self._place_credit_hold(enrollment)
        return records

    def _place_credit_hold(self, enrollment):
        """Place a pending hold against the member's subscription balance."""
        member = enrollment.member_id
        session = enrollment.session_id
        if not member or not session:
            return

        Sub = self.env["dojo.member.subscription"]
        sub = Sub._find_subscription_for_session(member, session)
        if not sub:
            # No matching subscription found — possibly a drop-in or admin booking
            return

        plan = sub.plan_id
        credits_per_period = getattr(plan, "credits_per_period", 0)
        if not credits_per_period:
            # 0 = unlimited plan — no credit gate
            return

        program = session.template_id.program_id if session.template_id else False
        cost = program.credits_per_class if program else 1
        if cost <= 0:
            return

        # Thread-safe row lock
        sub._lock_for_credit_write()

        # Re-read balance inside the lock
        balance = sub.credit_balance
        if balance < cost:
            raise UserError(
                f"Insufficient credits. You have {balance} credit(s) but this "
                f"class costs {cost}. Please contact the front desk."
            )

        self.env["dojo.credit.transaction"].create({
            "subscription_id": sub.id,
            "transaction_type": "hold",
            "amount": -cost,
            "status": "pending",
            "enrollment_id": enrollment.id,
            "note": f"Hold — {session.display_name or session.id}",
        })

    # ── Write: handle cancellation ───────────────────────────────────────

    def write(self, vals):
        # Capture records that are transitioning TO cancelled
        cancelling = self.browse()
        if vals.get("status") == "cancelled":
            cancelling = self.filtered(lambda e: e.status != "cancelled")

        result = super().write(vals)

        for enrollment in cancelling:
            self._handle_cancel_credit(enrollment)

        return result

    def _handle_cancel_credit(self, enrollment):
        """Release or consume the pending hold depending on the cancel window."""
        hold = self.env["dojo.credit.transaction"].search(
            [
                ("enrollment_id", "=", enrollment.id),
                ("transaction_type", "=", "hold"),
                ("status", "=", "pending"),
            ],
            limit=1,
        )
        if not hold:
            return

        session = enrollment.session_id
        now = fields.Datetime.now()
        start = session.start_datetime if session else False

        if start and (start - now) > timedelta(hours=CANCEL_REFUND_HOURS):
            # Outside penalty window → refund
            hold.sudo().write({
                "status": "cancelled",
                "note": f"Hold released — cancelled > {CANCEL_REFUND_HOURS} h before session",
            })
        else:
            # Inside penalty window or session already started → keep credit
            hold.sudo().write({
                "status": "confirmed",
                "note": "Hold confirmed — late cancel / no refund window",
            })
