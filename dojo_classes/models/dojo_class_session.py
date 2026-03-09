from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DojoClassSession(models.Model):
    _name = "dojo.class.session"
    _description = "Dojo Class Session"
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
