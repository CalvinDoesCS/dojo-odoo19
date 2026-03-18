from odoo import fields, models


class DojoEmergencyContact(models.Model):
    _name = "dojo.emergency.contact"
    _description = "Dojang Emergency Contact"

    member_id = fields.Many2one("dojo.member", required=True, ondelete="cascade", index=True)
    name = fields.Char(required=True)
    relationship = fields.Char(required=True)
    phone = fields.Char(required=True)
    email = fields.Char()
    is_primary = fields.Boolean(default=False)
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company", related="member_id.company_id", store=True, readonly=True
    )
