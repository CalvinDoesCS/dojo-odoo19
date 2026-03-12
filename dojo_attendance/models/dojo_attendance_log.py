from odoo import api, fields, models


class DojoAttendanceLog(models.Model):
    _name = "dojo.attendance.log"
    _description = "Dojo Attendance Log"
    _order = "checkin_datetime desc"
    _rec_name = "name"

    name = fields.Char(compute="_compute_name", store=True, string="Name")

    @api.depends("member_id", "session_id")
    def _compute_name(self):
        for rec in self:
            parts = []
            if rec.member_id:
                parts.append(rec.member_id.name)
            if rec.session_id:
                parts.append(rec.session_id.display_name or rec.session_id.name)
            rec.name = " \u2014 ".join(parts) if parts else "Attendance Log"

    session_id = fields.Many2one(
        "dojo.class.session", required=True, ondelete="cascade", index=True
    )
    enrollment_id = fields.Many2one("dojo.class.enrollment", index=True)
    member_id = fields.Many2one("dojo.member", required=True, index=True, ondelete="cascade")
    status = fields.Selection(
        [
            ("present", "Present"),
            ("late", "Late"),
            ("absent", "Absent"),
            ("excused", "Excused"),
        ],
        default="present",
        required=True,
    )
    checkin_datetime = fields.Datetime(default=fields.Datetime.now, required=True)
    checkout_datetime = fields.Datetime(string="Checkout Time")
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company", related="session_id.company_id", store=True, readonly=True
    )

    _dojo_attendance_unique_session_member = models.Constraint(
        "unique(session_id, member_id)",
        "Attendance is already logged for this member in this session.",
    )
