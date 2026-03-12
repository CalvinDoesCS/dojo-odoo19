from odoo import fields, models


class DojoSubscriptionPlanCreditExtend(models.Model):
    _inherit = "dojo.subscription.plan"

    credits_per_period = fields.Integer(
        string="Credits per Billing Cycle",
        default=0,
        help=(
            "Number of credits granted each time the subscription renews. "
            "Set to 0 to disable the credit gate entirely (unlimited sessions)."
        ),
    )
