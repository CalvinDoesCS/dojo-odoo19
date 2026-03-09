from odoo import api, fields, models


class DojoInstructorProfile(models.Model):
    _name = "dojo.instructor.profile"
    _description = "Dojo Instructor Profile"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one("res.users", required=True, tracking=True)
    employee_id = fields.Many2one("hr.employee", tracking=True, readonly=True, copy=False)
    partner_id = fields.Many2one("res.partner", required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    bio = fields.Text()

    _dojo_instructor_user_unique = models.Constraint(
        "unique(user_id)",
        "A user can only have one instructor profile.",
    )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _employee_vals(self):
        """Return a dict of hr.employee field values mirrored from this profile."""
        self.ensure_one()
        return {
            "name": self.name,
            "user_id": self.user_id.id,
            "work_email": self.user_id.email or False,
            "address_home_id": self.partner_id.id,
            "job_title": "Instructor",
            "company_id": self.company_id.id,
        }

    def _sync_to_employee(self, vals):
        """Propagate changed profile fields to the linked hr.employee record."""
        sync_keys = {"name", "user_id", "partner_id", "company_id"}
        if not sync_keys.intersection(vals):
            return
        for profile in self:
            if not profile.employee_id:
                continue
            employee_vals = {}
            if "name" in vals:
                employee_vals["name"] = vals["name"]
            if "user_id" in vals:
                employee_vals["user_id"] = vals["user_id"]
                new_user = self.env["res.users"].browse(vals["user_id"])
                employee_vals["work_email"] = new_user.email or False
            if "partner_id" in vals:
                employee_vals["address_home_id"] = vals["partner_id"]
            if "company_id" in vals:
                employee_vals["company_id"] = vals["company_id"]
            if employee_vals:
                profile.employee_id.sudo().write(employee_vals)

    # ── ORM overrides ─────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for profile in records:
            if profile.employee_id:
                continue
            employee = self.env["hr.employee"].sudo().create(profile._employee_vals())
            # Use sudo + direct write to avoid triggering _compute_dojo_role re-entry
            profile.sudo().write({"employee_id": employee.id})
        return records

    def write(self, vals):
        # Mirror archival to employee before the record itself is toggled
        if "active" in vals:
            to_toggle = self.filtered(lambda p: p.employee_id)
            if to_toggle:
                self.env["hr.employee"].sudo().with_context(active_test=False).search(
                    [("id", "in", to_toggle.employee_id.ids)]
                ).write({"active": vals["active"]})

        res = super().write(vals)
        self._sync_to_employee(vals)
        return res
