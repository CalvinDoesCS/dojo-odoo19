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

    def _compute_payment_state(self):
        # Capture old DB-stored payment_state before super() recomputes it.
        # We do NOT read from the ORM cache here (which may already hold the
        # to-be-written value); instead we query the DB directly so we get the
        # true "before" state and can detect the → paid transition.
        if self.ids:
            self.env.cr.execute(
                "SELECT id, payment_state FROM account_move WHERE id = ANY(%s)",
                (list(self.ids),),
            )
            old_states = dict(self.env.cr.fetchall())
        else:
            old_states = {}

        super()._compute_payment_state()

        # After super() has set the new payment_state on each record, find
        # those that just became paid/in_payment and activate their pending subs.
        pending_subs = self.env['dojo.member.subscription']
        for move in self:
            old = old_states.get(move.id)
            if old not in ('paid', 'in_payment') and move.payment_state in ('paid', 'in_payment'):
                if move.subscription_id and move.subscription_id.state == 'pending':
                    pending_subs |= move.subscription_id
                for sub in move.dojo_subscription_ids.filtered(lambda s: s.state == 'pending'):
                    pending_subs |= sub

        for sub in pending_subs:
            sub.sudo().write({'state': 'active'})
            if sub.member_id and sub.member_id.membership_state != 'active':
                sub.member_id.sudo().action_set_active()
