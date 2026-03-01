import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DojoKioskConfig(models.Model):
    _name = "dojo.kiosk.config"
    _description = "Dojo Kiosk Configuration"
    _order = "name"

    name = fields.Char(string="Kiosk Name", required=True)
    pin_code = fields.Char(
        string="Instructor PIN",
        required=True,
        help="Exactly 6 digits used to unlock Instructor Mode on this kiosk.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)

    @api.constrains("pin_code")
    def _check_pin_code(self):
        for kiosk in self:
            if not re.fullmatch(r"\d{6}", kiosk.pin_code or ""):
                raise ValidationError(
                    "Instructor PIN must be exactly 6 digits (numbers only)."
                )
