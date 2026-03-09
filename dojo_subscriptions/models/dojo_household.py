from odoo import _, fields, models
from odoo.exceptions import UserError


class DojoHousehold(models.Model):
    _inherit = "dojo.household"

    # ── Stripe Issuing / Payment Method ────────────────────────────────────
    stripe_customer_id = fields.Char(
        string="Stripe Cardholder ID",
        copy=False,
        help="Stripe Issuing Cardholder ID created for this household's primary guardian.",
    )
    stripe_card_id = fields.Char(
        string="Stripe Card ID",
        copy=False,
        help="Stripe Issuing virtual card ID linked to this household.",
    )
    payment_card_brand = fields.Char(
        string="Card Brand",
        help="e.g. Visa, Mastercard",
    )
    payment_card_last4 = fields.Char(
        string="Last 4 Digits",
        size=4,
    )
    payment_card_expiry = fields.Char(
        string="Expiry (MM/YY)",
        size=5,
    )
    payment_card_status = fields.Char(
        string="Card Status",
        copy=False,
        help="active, inactive, canceled — as reported by Stripe",
    )

    # ── Internal helpers ────────────────────────────────────────────────────
    def _get_stripe_api(self):
        """Return (stripe_module, secret_key). Never sets the global api_key."""
        try:
            import stripe as stripe_lib
        except ImportError:
            raise UserError(_(
                'The stripe Python package is not installed. '
                'Add "stripe" to requirements.txt and rebuild the container.'
            ))
        ICP = self.env['ir.config_parameter'].sudo()
        secret_key = ICP.get_param('stripe.secret_key', '')
        if not secret_key:
            raise UserError(_(
                'Stripe secret key is not configured. '
                'Go to Settings \u2192 Technical \u2192 System Parameters and set "stripe.secret_key".'
            ))
        return stripe_lib, secret_key

    # ── Stripe Issuing actions ──────────────────────────────────────────────
    def action_create_stripe_cardholder(self):
        """Create a Stripe Issuing Cardholder for this household's primary guardian."""
        self.ensure_one()
        if self.stripe_customer_id:
            return  # Already created
        guardian = self.primary_guardian_id
        if not guardian:
            raise UserError(_('A primary guardian must be set before creating a Stripe cardholder.'))
        stripe, api_key = self._get_stripe_api()
        company = self.env.company
        cardholder = stripe.issuing.Cardholder.create(
            name=guardian.name,
            email=guardian.email or None,
            phone_number=guardian.mobile or guardian.phone or None,
            type='individual',
            billing={
                'address': {
                    'line1': company.street or '123 Main St',
                    'city': company.city or 'City',
                    'state': company.state_id.code if company.state_id else 'CA',
                    'postal_code': company.zip or '00000',
                    'country': company.country_id.code if company.country_id else 'US',
                }
            },
            api_key=api_key,
        )
        self.sudo().write({'stripe_customer_id': cardholder['id']})

    def action_create_stripe_card(self):
        """Create a Stripe Issuing virtual Card for this household."""
        self.ensure_one()
        if not self.stripe_customer_id:
            self.action_create_stripe_cardholder()
        if self.stripe_card_id:
            return  # Already created
        stripe, api_key = self._get_stripe_api()
        currency = (self.env.company.currency_id.name or 'usd').lower()
        card = stripe.issuing.Card.create(
            cardholder=self.stripe_customer_id,
            currency=currency,
            type='virtual',
            api_key=api_key,
        )
        self.sudo().write({
            'stripe_card_id': card['id'],
            'payment_card_brand': (card.get('brand') or '').capitalize(),
            'payment_card_last4': card.get('last4') or '',
            'payment_card_expiry': '{:02d}/{}'.format(
                card.get('exp_month', 0),
                str(card.get('exp_year', ''))[-2:],
            ),
            'payment_card_status': card.get('status') or 'active',
        })

    def action_get_wallet_ephemeral_key(self):
        """Return a Stripe Ephemeral Key dict for Google Wallet push provisioning."""
        self.ensure_one()
        if not self.stripe_card_id:
            raise UserError(_('No Stripe card exists for this household yet.'))
        stripe, api_key = self._get_stripe_api()
        eph = stripe.EphemeralKey.create(
            {'issuing_card': self.stripe_card_id},
            stripe_version='2024-06-20',
            api_key=api_key,
        )
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'ephemeral_key_secret': eph['secret'],
            'stripe_card_id': self.stripe_card_id,
            'publishable_key': ICP.get_param('stripe.publishable_key', ''),
        }

    def action_issue_card_button(self):
        """Button: create cardholder + virtual card if not already done."""
        self.ensure_one()
        self.action_create_stripe_cardholder()
        self.action_create_stripe_card()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Stripe Card Issued'),
                'message': _('Virtual card \u2022\u2022\u2022\u2022 %s has been created and is active.') % (self.payment_card_last4 or ''),
                'type': 'success',
                'sticky': False,
            },
        }
