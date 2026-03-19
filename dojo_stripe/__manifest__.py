{
    "name": "Dojang Stripe",
    "summary": "Stripe Billing (member subscriptions) + Stripe Issuing (employee cards)",
    "description": """
Provides two distinct Stripe object types:

  res.partner (household)  →  stripe.Customer (Billing)
                  →  stripe.PaymentMethod (card-on-file for recurring billing)

  hr.employee     →  stripe.issuing.Cardholder (individual)
                  →  stripe.issuing.Card (virtual)

The dojo.member.subscription action_generate_invoice() override charges the
household's saved payment method immediately after posting the Odoo invoice.
Falls back to invoice-by-email if no Stripe customer / PM is configured.

Stripe keys are read from the Stripe payment provider configured in
Invoicing → Configuration → Payment Providers → Stripe.
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
    "assets": {
        "web.assets_backend": [
            "dojo_stripe/static/src/issuing.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application": False,
}
