from odoo import fields, models


class DojoProgramCreditExtend(models.Model):
    _inherit = "dojo.program"

    credits_per_class = fields.Integer(
        string="Credits per Class",
        default=1,
        help=(
            "Credits deducted from a member's balance each time they book a "
            "session in this program. Ignored when the plan's "
            "'Credits per Billing Cycle' is 0 (unlimited)."
        ),
    )
