import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    # ------------------------------------------------------------------
    # Dojo fields
    # ------------------------------------------------------------------

    x_session_id = fields.Many2one(
        "dojo.class.session",
        string="Dojang Session",
        ondelete="set null",
        index=True,
        help="The Dojang class session this calendar event represents.",
    )

    x_capacity = fields.Integer(
        string="Capacity",
        default=0,
        help="Maximum number of students for this class.",
    )

    x_roster_count = fields.Integer(
        string="Roster",
        compute="_compute_x_roster_count",
        store=True,
        help="Number of registered enrollments for this session.",
    )

    x_attendance_complete = fields.Boolean(
        string="Attendance Complete",
        default=False,
        help="Marks that attendance has been fully recorded for this class.",
    )

    # Stored related fields — enable fast filtering/grouping in calendar
    x_instructor_id = fields.Many2one(
        "dojo.instructor.profile",
        string="Instructor",
        related="x_session_id.instructor_profile_id",
        store=True,
        readonly=True,
    )

    x_site_id = fields.Many2one(
        "res.company",
        string="Site",
        related="x_session_id.company_id",
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends("x_session_id", "x_session_id.enrollment_ids.status")
    def _compute_x_roster_count(self):
        for event in self:
            if event.x_session_id:
                event.x_roster_count = len(
                    event.x_session_id.enrollment_ids.filtered(
                        lambda e: e.status == "registered"
                    )
                )
            else:
                event.x_roster_count = 0

    # ------------------------------------------------------------------
    # Smart button actions
    # ------------------------------------------------------------------

    def action_open_session_roster(self):
        """Open the enrollment list for the linked session."""
        self.ensure_one()
        if not self.x_session_id:
            return {}
        return {
            "type": "ir.actions.act_window",
            "name": "Session Roster",
            "res_model": "dojo.class.enrollment",
            "view_mode": "list,form",
            "domain": [("session_id", "=", self.x_session_id.id)],
            "context": {
                "default_session_id": self.x_session_id.id,
                "search_default_registered": True,
            },
        }

    def action_mark_attendance_complete(self):
        """Mark attendance as complete and transition the session to done."""
        self.ensure_one()
        self.write({"x_attendance_complete": True})
        if self.x_session_id and self.x_session_id.state != "done":
            self.x_session_id.write({"state": "done"})
        return True
