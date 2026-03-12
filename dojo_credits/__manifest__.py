{
    "name": "Dojo Credits",
    "summary": "Class credit ledger — replaces hard-coded weekly session cap with a per-subscription credit pool",
    "version": "19.0.1.0.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojo",
    "depends": [
        "dojo_subscriptions",   # dojo.member.subscription, dojo.subscription.plan
        "dojo_attendance",       # dojo.attendance.log
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/sequences.xml",
        "views/dojo_credit_transaction_views.xml",
        "views/dojo_subscription_plan_views.xml",
        "views/dojo_program_credit_views.xml",
        "views/dojo_subscription_credit_views.xml",
        "wizards/dojo_credit_adjustment_wizard_views.xml",
    ],
    "application": False,
    "auto_install": True,
    "installable": True,
}
