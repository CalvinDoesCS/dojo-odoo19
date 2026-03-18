{
    "name": "Dojang Stripe",
    "summary": "Stripe Billing (member subscriptions) + Stripe Issuing (employee cards)",
    "description": """
Provides two distinct Stripe object types:

  dojo.household  →  stripe.Customer (Billing)
                  →  stripe.PaymentMethod (card-on-file for recurring billing)

  hr.employee     →  stripe.issuing.Cardholder (individual)
                  →  stripe.issuing.Card (virtual)

The dojo.member.subscription action_generate_invoice() override charges the
household's saved payment method immediately after posting the Odoo invoice.
Falls back to invoice-by-email if no Stripe customer / PM is configured.

Stripe keys are stored in ir.config_parameter:
  stripe.secret_key
  stripe.publishable_key
""",
    "version": "19.0.2.0.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojo Platform",
    "depends": [
        "dojo_subscriptions",
        "hr",
        "payment_stripe",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/dojo_stripe_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
