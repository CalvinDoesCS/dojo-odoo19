"""
dojo_member_subscription_stripe.py
────────────────────────────────────
Extends dojo.member.subscription to charge via Stripe immediately after
posting the Odoo invoice, when the household has a saved native payment.token.

Architecture (native payment_stripe):
  - payment.token  (provider_ref = cus_xxx, stripe_payment_method = pm_xxx)
    linked to the primary guardian's partner_id.
  - action_charge_invoice() on res.partner (household) creates a payment.transaction
    with operation='offline' and calls _send_payment_request().
  - Odoo reconciles the invoice via Stripe webhook or status-check cron.

Fallback: if no payment.token is found for the household guardian, the base
action_generate_invoice() result is returned unchanged (e-mail invoice path).

Dunning (_handle_billing_failure) is called on immediate errors (tx.state
becomes 'error' synchronously). Async failures are handled via webhooks.
"""
import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoMemberSubscriptionStripe(models.Model):
    _inherit = "dojo.member.subscription"

    def action_generate_invoice(self):
        """Generate invoice then immediately charge via saved payment.token.

        If the household's primary guardian has an active Stripe payment.token,
        household.action_charge_invoice(invoice) is called right after the
        Odoo invoice is posted.

        On tx.state == 'error'  → _handle_billing_failure() (triggers dunning).
        On tx.state == 'done'   → _reset_billing_failures() (immediate success).
        On tx.state == 'pending' → async; Stripe webhook / cron will reconcile.

        Falls back to email-invoice path when no token is configured.
        """
        invoice = super().action_generate_invoice()

        household = self.member_id.partner_id.parent_id
        if not household or not household.is_household:
            return invoice

        # Use the computed payment_token_count field from dojo_household_billing
        # to determine whether a card is on file.  Attribute check required in
        # case dojo_stripe is not installed (defensive programming).
        if not getattr(household, 'payment_token_count', 0):
            # No saved card — invoice-by-email path already handled by super()
            return invoice

        try:
            tx = household.action_charge_invoice(invoice)
        except UserError as exc:
            # e.g. "No saved Stripe payment method found" or "No active Stripe provider"
            _logger.warning(
                'Dojo Stripe: could not charge invoice %s for subscription %s: %s',
                invoice.name, self.id, exc,
            )
            self._handle_billing_failure(exc)
            return invoice
        except Exception as exc:
            _logger.error(
                'Dojo Stripe: unexpected error charging invoice %s for subscription %s: %s',
                invoice.name, self.id, exc, exc_info=True,
            )
            self._handle_billing_failure(exc)
            return invoice

        # tx.state is set synchronously by _send_payment_request()
        state = tx.state if tx else ''
        if state == 'done':
            self._reset_billing_failures()
            _logger.info(
                'Dojo Stripe: PaymentIntent succeeded immediately for subscription %s.',
                self.id,
            )
        elif state == 'error':
            error_msg = getattr(tx, 'state_message', None) or 'Stripe payment failed'
            exc = UserError(_(error_msg))
            _logger.warning(
                'Dojo Stripe: charge failed for subscription %s: %s',
                self.id, error_msg,
            )
            self._handle_billing_failure(exc)
        else:
            # 'pending', 'draft', etc. — async resolution via Stripe webhook
            _logger.info(
                'Dojo Stripe: transaction %s in state %r for subscription %s — '
                'awaiting Stripe webhook for reconciliation.',
                tx.id, state, self.id,
            )

        return invoice

    def _generate_household_invoice(self, subs, today):
        """Create consolidated household invoice then charge via saved payment.token.

        Overrides the base method so the single combined invoice gets charged
        once through Stripe rather than triggering a charge per subscription.
        """
        invoice = super()._generate_household_invoice(subs, today)
        if not invoice:
            return invoice

        # All subs in a billing group share the same household/billing partner.
        household = subs[0].member_id.partner_id.parent_id if subs else None
        if not household or not getattr(household, 'payment_token_count', 0):
            return invoice

        try:
            tx = household.action_charge_invoice(invoice)
        except UserError as exc:
            _logger.warning(
                'Dojo Stripe: could not charge consolidated invoice %s: %s',
                invoice.name, exc,
            )
            for sub in subs:
                sub._handle_billing_failure(exc)
            return invoice
        except Exception as exc:
            _logger.error(
                'Dojo Stripe: unexpected error charging consolidated invoice %s: %s',
                invoice.name, exc, exc_info=True,
            )
            for sub in subs:
                sub._handle_billing_failure(exc)
            return invoice

        state = tx.state if tx else ''
        if state == 'done':
            for sub in subs:
                sub._reset_billing_failures()
            _logger.info(
                'Dojo Stripe: consolidated invoice %s charged successfully.', invoice.name
            )
        elif state == 'error':
            error_msg = getattr(tx, 'state_message', None) or 'Stripe payment failed'
            exc = UserError(_(error_msg))
            _logger.warning(
                'Dojo Stripe: consolidated charge failed for invoice %s: %s',
                invoice.name, error_msg,
            )
            for sub in subs:
                sub._handle_billing_failure(exc)
        else:
            _logger.info(
                'Dojo Stripe: consolidated invoice %s pending (tx %s) — '
                'awaiting Stripe webhook.',
                invoice.name, tx.id if tx else 'N/A',
            )

        return invoice
