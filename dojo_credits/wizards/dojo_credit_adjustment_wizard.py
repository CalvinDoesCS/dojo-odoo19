"""
Manual credit adjustment wizard — lets admin staff add or subtract credits
from a subscription with a mandatory reason note.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DojoCreditAdjustmentWizard(models.TransientModel):
    _name = "dojo.credit.adjustment.wizard"
    _description = "Manual Credit Adjustment"

    subscription_id = fields.Many2one(
        "dojo.member.subscription",
        string="Subscription",
        required=True,
    )
    member_id = fields.Many2one(
        related="subscription_id.member_id",
        readonly=True,
        string="Member",
    )
    current_balance = fields.Integer(
        related="subscription_id.credit_balance",
        readonly=True,
        string="Current Balance",
    )
    amount = fields.Integer(
        string="Adjustment Amount",
        required=True,
        help="Positive to add credits, negative to deduct credits.",
    )
    note = fields.Char(
        string="Reason",
        required=True,
        help="Mandatory reason recorded on the transaction ledger.",
    )

    # ── Constraints ───────────────────────────────────────────────────────

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount == 0:
                raise ValidationError("Adjustment amount cannot be zero.")

    # ── Action ─────────────────────────────────────────────────────────────

    def action_apply(self):
        self.ensure_one()
        self.env["dojo.credit.transaction"].create({
            "subscription_id": self.subscription_id.id,
            "transaction_type": "adjustment",
            "amount": self.amount,
            "status": "confirmed",
            "note": self.note,
        })
        return {"type": "ir.actions.act_window_close"}
