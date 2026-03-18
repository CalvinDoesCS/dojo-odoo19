{
    "name": "Dojang Belt Progression",
    "summary": "Belt ranks, test events, certifications, and member rank history",
    "version": "19.0.1.0.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojang",
    "depends": ["dojo_classes", "dojo_members", "dojo_attendance", "account", "dojo_instructor_dashboard"],
    "data": [
        "security/dojo_belt_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/dojo_belt_views.xml",
        "views/dojo_belt_promotion_wizard_views.xml",
    ],
    "application": True,
    "auto_install": True,
    "installable": True,
}
