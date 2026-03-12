"""
Credit hook on dojo.class.session:

write({'state': 'done'}):
  When a session closes, find all enrolled members that never checked in
  (attendance_state == 'pending' on the enrollment).  For each, confirm
  the pending hold — they no-showed, so the credit is consumed.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class DojoClassSessionCreditExtend(models.Model):
    _inherit = "dojo.class.session"

    def write(self, vals):
        closing = self.browse()
        if vals.get("state") == "done":
            closing = self.filtered(lambda s: s.state != "done")

        result = super().write(vals)

        for session in closing:
            self._process_no_shows(session)

        return result

    def _process_no_shows(self, session):
        """
        Sweep enrollments that are still registered but have no attendance log
        (or have an 'absent' attendance log).  Confirm their pending holds.
        """
        # Find registered enrollments with no attendance or attendance=absent
        pending_enrollments = session.enrollment_ids.filtered(
            lambda e: e.status == "registered"
            and getattr(e, "attendance_state", "pending") == "pending"
        )

        for enrollment in pending_enrollments:
            hold = self.env["dojo.credit.transaction"].search(
                [
                    ("enrollment_id", "=", enrollment.id),
                    ("transaction_type", "=", "hold"),
                    ("status", "=", "pending"),
                ],
                limit=1,
            )
            if hold:
                hold.sudo().write({
                    "status": "confirmed",
                    "note": "Hold confirmed — no-show when session closed",
                })
                _logger.info(
                    "No-show: credit hold %s confirmed for enrollment %s "
                    "(member: %s, session: %s)",
                    hold.reference,
                    enrollment.id,
                    enrollment.member_id.display_name,
                    session.id,
                )

            # Mark attendance on the enrollment itself
            if hasattr(enrollment, "attendance_state"):
                enrollment.sudo().write({"attendance_state": "absent"})
