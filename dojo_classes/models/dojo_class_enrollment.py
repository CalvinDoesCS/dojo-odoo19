from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DojoClassEnrollment(models.Model):
    _name = "dojo.class.enrollment"
    _description = "Dojo Class Enrollment"

    session_id = fields.Many2one(
        "dojo.class.session", required=True, ondelete="cascade", index=True
    )
    member_id = fields.Many2one("dojo.member", required=True, index=True, ondelete="restrict")
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
