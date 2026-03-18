from odoo import api, fields, models
from odoo.exceptions import ValidationError


def _action_open_attendance_wizard(session):
    """Return the ir.actions dict that opens the quick-attendance wizard for
    *session* in a popup.  Extracted as a module-level helper so it can be
    referenced from both the model and from tests."""
    return {
        'type': 'ir.actions.act_window',
        'name': 'Mark Attendance',
        'res_model': 'dojo.attendance.quick.wizard',
        'view_mode': 'form',
        'target': 'new',
        'context': {'default_session_id': session.id},
    }


class DojoClassSession(models.Model):
    _name = "dojo.class.session"
    _description = "Dojang Class Session"
    _order = "start_datetime desc"

    name = fields.Char(compute="_compute_name", store=True)
    template_id = fields.Many2one("dojo.class.template", required=True, index=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    instructor_profile_id = fields.Many2one("dojo.instructor.profile", index=True)
    start_datetime = fields.Datetime(required=True, index=True)
    end_datetime = fields.Datetime(required=True, index=True)
    capacity = fields.Integer(default=20)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("open", "Open"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
    )
    enrollment_ids = fields.One2many(
        "dojo.class.enrollment", "session_id", string="Enrollments"
    )
    seats_taken = fields.Integer(compute="_compute_seats_taken")
    attendance_complete = fields.Boolean(
        compute="_compute_attendance_complete",
        store=True,
        readonly=False,
        string="Attendance Complete",
        help="Automatically set when all registered enrollments are marked. Can also be toggled manually.",
    )
    generated_from_recurrence = fields.Boolean(
        string="Auto-generated", default=False, readonly=True, index=True
    )
    recurrence_template_id = fields.Many2one(
        "dojo.class.template",
        string="Recurrence Template",
        index=True,
        help="The template whose recurrence rule generated this session.",
    )

    @api.depends("template_id", "start_datetime")
    def _compute_name(self):
        for session in self:
            if session.template_id and session.start_datetime:
                session.name = "%s - %s" % (
                    session.template_id.name,
                    fields.Datetime.to_string(session.start_datetime),
                )
            else:
                session.name = "New Session"

    @api.depends("enrollment_ids.status")
    def _compute_seats_taken(self):
        if not self.ids:
            return
        groups = self.env['dojo.class.enrollment'].read_group(
            [('session_id', 'in', self.ids), ('status', '=', 'registered')],
            fields=['session_id'],
            groupby=['session_id'],
        )
        counts = {g['session_id'][0]: g['session_id_count'] for g in groups}
        for session in self:
            session.seats_taken = counts.get(session.id, 0)

    @api.depends("state", "enrollment_ids.attendance_state", "enrollment_ids.status")
    def _compute_attendance_complete(self):
        for session in self:
            if session.state != "done":
                session.attendance_complete = False
                continue
            registered = session.enrollment_ids.filtered(
                lambda e: e.status == "registered"
            )
            session.attendance_complete = bool(registered) and all(
                e.attendance_state != "pending" for e in registered
            )

    def action_open_attendance_wizard(self):
        """Open the quick attendance marking wizard for this session."""
        self.ensure_one()
        return _action_open_attendance_wizard(self)

    @api.constrains("start_datetime", "end_datetime")
    def _check_datetime_order(self):
        for session in self:
            if session.end_datetime <= session.start_datetime:
                raise ValidationError("End time must be after start time.")

    @api.constrains("capacity")
    def _check_capacity(self):
        for session in self:
            if session.capacity < 0:
                raise ValidationError("Capacity cannot be negative.")

    @api.constrains("attendance_complete")
    def _check_attendance_complete(self):
        for session in self:
            if not session.attendance_complete:
                continue
            pending = session.enrollment_ids.filtered(
                lambda e: e.status == "registered" and e.attendance_state == "pending"
            )
            if pending:
                names = ", ".join(pending.mapped("member_id.name"))
                raise ValidationError(
                    "Cannot mark attendance complete — the following student(s) are still pending: %s. "
                    "Please mark each one as present or absent first." % names
                )

    def write(self, vals):
        """When a session is marked done, auto-create 'absent' attendance logs
        for any registered enrollments that are still in 'pending' state.
        This ensures those students are counted in attendance-rate KPIs rather
        than being silently excluded from the calculation."""
        result = super().write(vals)
        if vals.get("state") == "done":
            AttLog = self.env["dojo.attendance.log"]
            for session in self:
                # Find all registered enrollments still pending
                pending_enrollments = session.enrollment_ids.filtered(
                    lambda e: e.status == "registered" and e.attendance_state == "pending"
                )
                if not pending_enrollments:
                    continue
                # Collect members that already have a log (don't double-create)
                existing_member_ids = set(
                    AttLog.search([("session_id", "=", session.id)]).mapped("member_id").ids
                )
                for enr in pending_enrollments:
                    if enr.member_id.id in existing_member_ids:
                        continue
                    AttLog.create({
                        "session_id": session.id,
                        "member_id": enr.member_id.id,
                        "enrollment_id": enr.id,
                        "status": "absent",
                        "checkin_datetime": session.end_datetime or fields.Datetime.now(),
                    })
                    enr.attendance_state = "absent"
        return result
