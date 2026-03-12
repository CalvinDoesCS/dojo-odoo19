"""
Extensions to dojo.member.subscription:
  - O2m to credit transactions
  - Computed balance fields (no stored denorm)
  - _issue_period_credits() — expire old balance, grant new
  - Hooks into action_generate_invoice() and _generate_household_invoice()
  - Thread-safety helper _lock_for_credit_write()
  - Classmethod _find_subscription_for_session(member, session)
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class DojoMemberSubscriptionCreditExtend(models.Model):
    _inherit = "dojo.member.subscription"

    # ── Ledger link ──────────────────────────────────────────────────────
    transaction_ids = fields.One2many(
        "dojo.credit.transaction",
        "subscription_id",
        string="Credit Transactions",
        readonly=True,
    )

    # ── Computed balance fields (always derived from ledger) ─────────────
    credit_balance = fields.Integer(
        string="Available Balance",
        compute="_compute_credit_balance",
        help="Effective balance: confirmed grants minus all non-cancelled holds and expiries.",
    )
    credit_pending = fields.Integer(
        string="Pending Holds",
        compute="_compute_credit_balance",
        help="Sum of pending (unconfirmed) hold amounts — always ≤ 0.",
    )
    credit_confirmed = fields.Integer(
        string="Confirmed Balance",
        compute="_compute_credit_balance",
        help="Sum of confirmed transactions only (does not count pending holds).",
    )

    @api.depends("transaction_ids.amount", "transaction_ids.status")
    def _compute_credit_balance(self):
        for rec in self:
            txns = rec.transaction_ids
            confirmed = sum(t.amount for t in txns if t.status == "confirmed")
            pending = sum(t.amount for t in txns if t.status == "pending")
            rec.credit_confirmed = confirmed
            rec.credit_pending = pending
            rec.credit_balance = confirmed + pending  # pending is already negative

    # ── Helpers ──────────────────────────────────────────────────────────

    def _lock_for_credit_write(self):
        """
        Advisory row-level lock on this subscription.
        Raises UserError if another transaction already holds the lock,
        which safely prevents double-booking races.
        """
        self.ensure_one()
        try:
            self.env.cr.execute(
                "SELECT id FROM dojo_member_subscription "
                "WHERE id = %s FOR UPDATE NOWAIT",
                [self.id],
            )
        except Exception:
            raise UserError(
                "This subscription is being updated by another process. "
                "Please try again in a moment."
            )

    @api.model
    def _find_subscription_for_session(self, member, session):
        """
        Return the active subscription for *member* that covers *session*.

        Matching rules (in order):
          1. Subscription whose plan's program matches the session's program.
          2. Subscription whose plan's allowed templates include the session's
             template (course-style subscriptions).

        Returns a single `dojo.member.subscription` record or empty recordset.
        """
        active_subs = self.search([
            ("member_id", "=", member.id),
            ("state", "=", "active"),
        ])
        program = session.template_id.program_id if session.template_id else False
        template = session.template_id

        for sub in active_subs:
            plan = sub.plan_id
            # Program-based match
            if program and plan.plan_type == "program" and plan.program_id == program:
                return sub
            # Template-based match
            if template and plan.plan_type == "course" and template in plan.allowed_template_ids:
                return sub
        return self.browse()

    # ── Credit issuance ───────────────────────────────────────────────────

    def _issue_period_credits(self):
        """
        Called at invoice generation time.
        1. Expire any remaining confirmed balance (no rollover).
        2. Grant a fresh allocation of credits_per_period credits.
        """
        self.ensure_one()
        plan = self.plan_id
        credits_per_period = getattr(plan, "credits_per_period", 0)
        if not credits_per_period:
            # 0 = unlimited — nothing to do
            return

        CreditTxn = self.env["dojo.credit.transaction"]

        # 1. Expire leftover confirmed balance
        leftover = self.credit_confirmed
        if leftover > 0:
            CreditTxn.create({
                "subscription_id": self.id,
                "transaction_type": "expiry",
                "amount": -leftover,
                "status": "confirmed",
                "note": "Unused credits expired at period renewal",
            })

        # 2. Grant new period credits
        CreditTxn.create({
            "subscription_id": self.id,
            "transaction_type": "grant",
            "amount": credits_per_period,
            "status": "confirmed",
            "note": f"Period credit grant — {credits_per_period} credits",
        })
        _logger.info(
            "Issued %d credits to subscription %s (member: %s)",
            credits_per_period,
            self.id,
            self.member_id.display_name,
        )

    # ── Invoice hooks ─────────────────────────────────────────────────────

    def action_open_adjustment_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Manual Credit Adjustment",
            "res_model": "dojo.credit.adjustment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_subscription_id": self.id},
        }

    def action_view_credit_transactions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Credit Transactions",
            "res_model": "dojo.credit.transaction",
            "view_mode": "list,form",
            "domain": [("subscription_id", "=", self.id)],
            "context": {"default_subscription_id": self.id},
        }

    def action_generate_invoice(self):
        """Issue period credits after the invoice is created."""
        result = super().action_generate_invoice()
        for rec in self:
            try:
                rec._issue_period_credits()
            except Exception:
                _logger.exception(
                    "Failed to issue credits for subscription %s", rec.id
                )
        return result

    def _generate_household_invoice(self, subscriptions):
        """Issue period credits for every subscription in the household batch."""
        result = super()._generate_household_invoice(subscriptions)
        for sub in subscriptions:
            try:
                sub._issue_period_credits()
            except Exception:
                _logger.exception(
                    "Failed to issue credits for subscription %s", sub.id
                )
        return result
