"""
dojo_onboarding_wizard.py  (dojo_onboarding_stripe)
─────────────────────────────────────────────────────
Extends the onboarding wizard with a Stripe payment-capture step.

Step order after this module:
  member_info → household → guardian_setup → enrollment → auto_enroll
  → subscription → payment  ← NEW
  → portal_access

At action_confirm (after the base wizard creates all Odoo records):
  1. Create a Stripe Customer for the primary guardian.
  2. Attach the captured PaymentMethod to that customer.
  3. Create a native payment.token in Odoo (provider_ref = cus_xxx,
     stripe_payment_method = pm_xxx) linked to the guardian's partner.
  4. Immediately generate + charge the first invoice via the existing
     dojo_member_subscription_stripe override (action_generate_invoice).

If the staff clicks "Skip", billing defers to the cron / next_billing_date.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoOnboardingWizard(models.TransientModel):
    _inherit = 'dojo.onboarding.wizard'

    # ── Step selection — add 'payment' ────────────────────────────────────
    step = fields.Selection(
        selection_add=[('payment', '7. Payment')],
        ondelete={'payment': 'set default'},
    )

    # ── Stripe payment capture state ──────────────────────────────────────
    stripe_client_secret = fields.Char(readonly=True)
    stripe_setup_intent_id = fields.Char(readonly=True)
    stripe_payment_method_id = fields.Char(readonly=True)
    stripe_card_display = fields.Char(readonly=True)
    stripe_customer_id = fields.Char(readonly=True)  # created in get_setup_intent
    payment_captured = fields.Boolean(default=False)
    skip_payment = fields.Boolean(string='Send Invoice — skip card capture for now', default=False)

    # ── Override step order to insert 'payment' before 'portal_access' ───
    _STEP_ORDER = [
        'member_info', 'household', 'guardian_setup',
        'enrollment', 'auto_enroll',
        'subscription', 'payment', 'portal_access',
    ]

    # ── Step-skip logic ───────────────────────────────────────────────────
    def _should_skip_step(self, step_name):
        if step_name == 'payment' and not self.create_new_household:
            # Existing household already has a payment method on file — skip capture
            return True
        return super()._should_skip_step(step_name)

    # ── Validation on the payment step ────────────────────────────────────
    def action_next(self):
        if self.step == 'payment':
            if not self.payment_captured and not self.skip_payment:
                raise UserError(_(
                    'Please save a payment method, or check '
                    '"Send Invoice" to email the member an invoice instead.'
                ))
        return super().action_next()

    # ── Override confirm to attach PM and charge first invoice ────────────
    def action_confirm(self):
        """Run base confirm, then attach Stripe PM and charge, or send a pending invoice."""
        # Signal the base wizard to create the subscription as pending when skipping payment
        if self.skip_payment:
            self.defer_payment = True

        result = super().action_confirm()

        if self.stripe_payment_method_id and not self.skip_payment:
            self._attach_stripe_payment_and_charge()
        elif self.skip_payment:
            self._send_pending_invoice()

        return result

    # ── Helpers ───────────────────────────────────────────────────────────
    def _get_stripe_provider(self):
        return self.env['payment.provider'].sudo().search(
            [('code', '=', 'stripe'), ('state', 'in', ('enabled', 'test'))],
            limit=1,
        )

    def _send_pending_invoice(self):
        """Generate and email the first invoice for a pending (pay-by-invoice) subscription.

        The subscription was created as 'pending' by the base wizard because
        defer_payment=True. No credits are issued here — they fire via the
        write() hook when an admin activates the subscription after payment.
        """
        self.ensure_one()
        member = self.created_member_id
        if not member:
            return
        subscription = self.env['dojo.member.subscription'].sudo().search(
            [('member_id', '=', member.id), ('state', '=', 'pending')],
            limit=1,
            order='create_date desc',
        )
        if not subscription:
            _logger.warning(
                'dojo_onboarding_stripe: no pending subscription found for member %s — '
                'invoice not sent.', member.id,
            )
            return
        try:
            subscription.action_generate_invoice()
            _logger.info(
                'dojo_onboarding_stripe: invoice generated and emailed for '
                'pending subscription %s (member %s).',
                subscription.id, member.id,
            )
        except Exception as exc:
            _logger.error(
                'dojo_onboarding_stripe: failed to generate invoice for '
                'pending subscription %s: %s', subscription.id, exc,
            )

    def _attach_stripe_payment_and_charge(self):
        """
        Called after action_confirm has created the Odoo records.

        At this point the Stripe Customer was already created in get_setup_intent
        and the PM was attached to it by Stripe during stripe.confirmSetup().
        All we need to do here is:
          1. Update the Stripe customer with the Odoo partner_id metadata and
             set the PM as the customer's default.
          2. Create the Odoo payment.token record (pure DB write — no Stripe API).
          3. Charge the first invoice.
        """
        self.ensure_one()

        provider = self._get_stripe_provider()
        if not provider:
            _logger.warning(
                "dojo_onboarding_stripe: No active Stripe provider — "
                "skipping payment token creation."
            )
            return

        member = self.created_member_id
        if not member:
            _logger.warning(
                "dojo_onboarding_stripe: created_member_id not set — "
                "cannot attach Stripe PM."
            )
            return

        household = member.household_id
        guardian = household.primary_guardian_id if household else None
        if not guardian or not guardian.partner_id:
            _logger.warning(
                "dojo_onboarding_stripe: No guardian/partner on household — "
                "skipping."
            )
            return

        partner = guardian.partner_id
        pm_id = self.stripe_payment_method_id
        cus_id = self.stripe_customer_id

        if not cus_id:
            _logger.warning(
                "dojo_onboarding_stripe: No stripe_customer_id on wizard — "
                "PM was not pre-attached. Skipping token creation."
            )
            return

        try:
            # 1. Back-fill Odoo partner_id metadata now that the partner exists,
            #    and set the confirmed PM as the customer's default.
            provider._send_api_request(
                'POST', f'customers/{cus_id}',
                data={
                    'metadata[odoo_partner_id]': str(partner.id),
                    'invoice_settings[default_payment_method]': pm_id,
                },
            )
        except Exception as exc:
            # Non-fatal — token creation below still works without this.
            _logger.warning(
                "dojo_onboarding_stripe: could not update customer metadata "
                "(cus=%s): %s", cus_id, exc
            )

        try:
            # 2. Create Odoo payment.token (pure DB write)
            payment_method = self.env['payment.method'].sudo().search(
                [('code', '=', 'card'), ('provider_ids', 'in', [provider.id])],
                limit=1,
            )

            token_vals = {
                'provider_id': provider.id,
                'partner_id': partner.id,
                'provider_ref': cus_id,
                'stripe_payment_method': pm_id,
                'active': True,
            }
            if payment_method:
                token_vals['payment_method_id'] = payment_method.id
            if self.stripe_card_display:
                token_vals['payment_details'] = self.stripe_card_display

            token = self.env['payment.token'].sudo().create(token_vals)

            _logger.info(
                "dojo_onboarding_stripe: created payment.token %s for "
                "guardian %s (cus=%s pm=%s)",
                token.id, guardian.name, cus_id, pm_id,
            )

            # 3. Charge first invoice immediately
            subscription = self.env['dojo.member.subscription'].sudo().search(
                [('member_id', '=', member.id), ('state', '=', 'active')],
                limit=1,
                order='create_date desc',
            )
            if subscription:
                try:
                    subscription.action_generate_invoice()
                    _logger.info(
                        "dojo_onboarding_stripe: first invoice generated "
                        "and charge initiated for member %s",
                        member.id,
                    )
                except Exception as exc:
                    _logger.error(
                        "dojo_onboarding_stripe: failed to charge first "
                        "invoice for member %s: %s", member.id, exc
                    )

        except Exception as exc:
            _logger.error(
                "dojo_onboarding_stripe: failed to create payment.token "
                "for member %s: %s", member.id if member else '?', exc
            )
            # Do NOT re-raise — the member record was created successfully.
            # Staff can set up billing manually from the household form.
