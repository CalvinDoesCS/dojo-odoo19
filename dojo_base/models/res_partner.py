import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_student = fields.Boolean(
        string="Is Student",
        default=False,
        help="This person trains at the dojo.",
    )
    is_guardian = fields.Boolean(
        string="Is Guardian",
        default=False,
        help="This person is a guardian of students in their household.",
    )
    is_minor = fields.Boolean(
        string="Is Minor",
        default=False,
        help="This person is a minor.",
    )
    is_household = fields.Boolean(
        string="Is Household",
        default=False,
        help="This partner record represents a household container.",
    )
    primary_guardian_id = fields.Many2one(
        "res.partner",
        string="Primary Guardian",
        help="The main guardian contact for this household. Only meaningful when is_household is True.",
        index=True,
    )
    dojo_member_id = fields.Many2one(
        "dojo.member",
        string="Dojo Member",
        compute="_compute_dojo_member_id",
        search="_search_dojo_member_id",
    )

    @api.depends("is_student")
    def _compute_dojo_member_id(self):
        members = self.env["dojo.member"].sudo().search([
            ("partner_id", "in", self.ids),
        ])
        partner_map = {m.partner_id.id: m.id for m in members}
        for partner in self:
            partner.dojo_member_id = partner_map.get(partner.id, False)

    def _search_dojo_member_id(self, operator, value):
        if operator == "!=" and value is False:
            members = self.env["dojo.member"].sudo().search([])
            return [("id", "in", members.mapped("partner_id").ids)]
        if operator == "=" and value is False:
            members = self.env["dojo.member"].sudo().search([])
            return [("id", "not in", members.mapped("partner_id").ids)]
        return [("id", "in", [])]

    def _grant_portal_access_credentials(self):
        """Grant portal access and return credentials dict, or None if user existed."""
        self.ensure_one()
        if not self.email:
            raise UserError(_(
                "An email address is required before portal access can be granted."
            ))
        group_parent = self.env.ref("dojo_base.group_dojo_parent_student")
        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", self.id)], limit=1
        )
        if user:
            if group_parent not in user.group_ids:
                user.sudo().write({"group_ids": [(4, group_parent.id)]})
            return None
        temp_password = secrets.token_urlsafe(10)
        user = self.env["res.users"].sudo().create({
            "partner_id": self.id,
            "login": self.email,
            "name": self.name,
            "group_ids": [(4, group_parent.id)],
        })
        user.sudo().write({"password": temp_password})
        return {
            "name": self.name,
            "login": self.email,
            "temp_password": temp_password,
        }
