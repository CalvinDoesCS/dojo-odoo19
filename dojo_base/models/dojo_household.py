from odoo import fields, models


class DojoHousehold(models.Model):
    _name = "dojo.household"
    _description = "Dojang Household"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    primary_guardian_id = fields.Many2one(
        "dojo.member",
        string="Primary Guardian",
        tracking=True,
        domain="[('role', 'in', ['parent', 'both']), ('household_id', '=', id)]",
        help="The main parent/guardian contact for this household. Must be a member with role 'Parent' or 'Both'.",
    )
    member_ids = fields.One2many("dojo.member", "household_id", string="Members")
    guardian_link_ids = fields.One2many(
        "dojo.guardian.link", "household_id", string="Guardian Links"
    )
    note = fields.Text()
