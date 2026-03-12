"""
Credit hook on dojo.attendance.log:

create():
  When a present/late attendance log is created for an enrollment that has a
  pending hold, finalise the hold (status → confirmed).  This represents the
  credit being fully consumed at check-in.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

_ATTENDED_STATUSES = {"present", "late"}


class DojoAttendanceLogCreditExtend(models.Model):
    _inherit = "dojo.attendance.log"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for log in records:
            if log.status not in _ATTENDED_STATUSES:
                continue
            enrollment = log.enrollment_id
            if not enrollment and log.session_id and log.member_id:
                # Fallback: look up the enrollment from session + member
                enrollment = self.env["dojo.class.enrollment"].search(
                    [
                        ("session_id", "=", log.session_id.id),
                        ("member_id", "=", log.member_id.id),
                        ("status", "=", "registered"),
                    ],
                    limit=1,
                )
            if not enrollment:
                continue
            self._confirm_hold(enrollment)
        return records

    def _confirm_hold(self, enrollment):
        """Finalise the pending hold for the given enrollment."""
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
        hold.sudo().write({
            "status": "confirmed",
            "note": "Hold confirmed — member checked in",
        })
        _logger.debug(
            "Credit hold %s confirmed at check-in for enrollment %s",
            hold.reference,
            enrollment.id,
        )
