from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DojoClassEnrollment(models.Model):
    _name = "dojo.class.enrollment"
    _description = "Dojang Class Enrollment"

    session_id = fields.Many2one(
        "dojo.class.session", required=True, ondelete="cascade", index=True
    )
    member_id = fields.Many2one("dojo.member", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company", related="session_id.company_id", store=True, readonly=True
    )
    status = fields.Selection(
        [
            ("registered", "Registered"),
            ("waitlist", "Waitlist"),
            ("cancelled", "Cancelled"),
        ],
        default="registered",
        required=True,
    )
    attendance_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("present", "Present"),
            ("absent", "Absent"),
            ("excused", "Excused"),
        ],
        default="pending",
        required=True,
    )

    _dojo_class_enrollment_unique = models.Constraint(
        "unique(session_id, member_id)",
        "The member is already enrolled in this session.",
    )

    @api.constrains('session_id', 'member_id', 'status')
    def _check_course_membership(self):
        """Enforce that the member is on the course roster before allowing registration.

        Set context key ``skip_course_membership_check=True`` to bypass this
        constraint (e.g. when the instructor explicitly overrides roster settings
        from the kiosk).
        """
        if self.env.context.get('skip_course_membership_check'):
            return
        for rec in self:
            if rec.status != 'registered':
                continue
            template = rec.session_id.template_id
            # Only restrict when the template has an explicit roster
            if template and template.course_member_ids:
                if rec.member_id not in template.course_member_ids:
                    raise ValidationError(_(
                        '"%s" is not enrolled in the course "%s". '
                        'Please add them to the course roster first.',
                        rec.member_id.name, template.name,
                    ))

    @api.constrains('session_id', 'status')
    def _check_session_capacity(self):
        """Enforce session capacity for all enrollment entry points.

        Set context key ``skip_capacity_check=True`` to bypass — used for
        admin overrides and automatic waitlist promotions.
        """
        if self.env.context.get('skip_capacity_check'):
            return
        for rec in self:
            if rec.status != 'registered':
                continue
            session = rec.session_id
            if not session.capacity or session.capacity <= 0:
                continue  # 0 / unset = unlimited
            registered_count = self.search_count([
                ('session_id', '=', session.id),
                ('status', '=', 'registered'),
                ('id', '!=', rec.id),
            ])
            if registered_count >= session.capacity:
                raise ValidationError(_(
                    'Session "%s" is full (%d/%d seats taken). '
                    'Please contact the Dojang to be added to the waitlist.',
                    session.name,
                    registered_count,
                    session.capacity,
                ))

    def write(self, vals):
        """Promote the first waitlist enrollment when a registered spot opens up."""
        result = super().write(vals)
        if vals.get('status') == 'cancelled':
            for rec in self:
                waitlist = self.search([
                    ('session_id', '=', rec.session_id.id),
                    ('status', '=', 'waitlist'),
                ], limit=1, order='id asc')
                if waitlist:
                    # skip_capacity_check: seat is already freed, this is a system action
                    waitlist.with_context(skip_capacity_check=True).write(
                        {'status': 'registered'}
                    )
        return result