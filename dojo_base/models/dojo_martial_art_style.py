from odoo import fields, models


class DojoMartialArtStyle(models.Model):
    _name = "dojo.martial.art.style"
    _description = "Martial Art Style"
    _order = "sequence, name"

    name = fields.Char(required=True, string="Style Name")
    code = fields.Char(string="Code", help="Short code, e.g. BJJ, MT, JDO")
    sequence = fields.Integer(default=10)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
