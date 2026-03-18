from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    dojo_role = fields.Selection(
        [
            ("admin", "Dojang Admin"),
            ("instructor", "Instructor"),
            ("parent_student", "Student/Parent"),
            ("other", "Other"),
        ],
        compute="_compute_dojo_role",
        string="Dojang Role",
    )

    @api.depends("all_group_ids")
    def _compute_dojo_role(self):
        group_admin = self.env.ref("dojo_base.group_dojo_admin")
        group_instructor = self.env.ref("dojo_base.group_dojo_instructor")
        group_parent = self.env.ref("dojo_base.group_dojo_parent_student")
        for user in self:
            if group_admin in user.all_group_ids:
                user.dojo_role = "admin"
            elif group_instructor in user.all_group_ids:
                user.dojo_role = "instructor"
            elif group_parent in user.all_group_ids:
                user.dojo_role = "parent_student"
            else:
                user.dojo_role = "other"
