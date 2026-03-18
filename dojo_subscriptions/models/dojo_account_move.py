from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    subscription_id = fields.Many2one(
        "dojo.member.subscription",
        string="Dojang Subscription",
        index=True,
        ondelete="set null",
        help="Dojo membership subscription that generated this invoice.",
    )
    dojo_subscription_ids = fields.Many2many(
        "dojo.member.subscription",
        "dojo_invoice_sub_rel",
        "invoice_id",
        "subscription_id",
        string="Dojang Subscriptions",
        help="All subscriptions included in this consolidated household invoice.",
    )
