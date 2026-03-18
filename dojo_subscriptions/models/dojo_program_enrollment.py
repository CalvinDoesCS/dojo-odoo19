"""Dojo Program Enrollment — permanent member ↔ program history table.

One record is created for every program a member subscribes to.
Records are never deleted. When the underlying subscription ends,
``is_active`` is set to ``False`` and ``deactivated_date`` is recorded.
If the member re-subscribes to the same program later, a fresh enrollment
record is created (the old one stays for history).
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DojoProgramEnrollment(models.Model):
    _name = "dojo.program.enrollment"
    _description = "Dojang Program Enrollment"
    _order = "is_active desc, enrolled_date desc"

    # ── Core fields ───────────────────────────────────────────────────────
    member_id = fields.Many2one(
        "dojo.member",
        required=True,
        index=True,
        ondelete="cascade",
        string="Member",
    )
    program_id = fields.Many2one(
        "dojo.program",
        required=True,
        index=True,
        ondelete="cascade",
        string="Program",
    )
    subscription_id = fields.Many2one(
        "dojo.member.subscription",
        index=True,
        ondelete="set null",
        string="Source Subscription",
        help="The subscription that triggered this enrollment, if any. "
             "Left empty for manually-created enrollments.",
    )

    # ── Status ────────────────────────────────────────────────────────────
    is_active = fields.Boolean(
        default=True,
        index=True,
        string="Active",
        help="Active means the member currently has access to this program. "
             "Deactivated when the linked subscription ends or expires.",
    )
    enrolled_date = fields.Date(
        default=fields.Date.context_today,
        required=True,
        string="Enrolled Date",
    )
    deactivated_date = fields.Date(
        string="Deactivated Date",
        help="Set automatically when the linked subscription is cancelled or expired.",
    )

    # ── Extra ─────────────────────────────────────────────────────────────
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        index=True,
    )
    notes = fields.Text(string="Notes")

    # Convenience related fields so the list view doesn't need extra joins
    member_name = fields.Char(related="member_id.name", string="Member Name", store=False)
    program_name = fields.Char(related="program_id.name", string="Program Name", store=False)

    def name_get(self):
        result = []
        for rec in self:
            member = rec.member_id.name or ""
            prog = rec.program_id.name or ""
            status = "Active" if rec.is_active else "Inactive"
            result.append((rec.id, f"{member} — {prog} ({status})"))
        return result


class DojoMemberProgramEnrollmentRef(models.Model):
    """Back-reference on dojo.member for easy access to program enrollment history."""
    _inherit = "dojo.member"

    program_enrollment_ids = fields.One2many(
        "dojo.program.enrollment",
        "member_id",
        string="Program Enrollments",
    )
    active_program_enrollment_ids = fields.One2many(
        "dojo.program.enrollment",
        "member_id",
        string="Active Programs",
        domain=[("is_active", "=", True)],
    )
