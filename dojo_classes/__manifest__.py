{
    "name": "Dojang Classes",
    "summary": "Courses, sessions, and enrollment",
    "version": "19.0.1.2.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojang",
    "depends": ["dojo_members"],
    "data": [
        "security/ir.model.access.csv",
        "security/dojo_classes_security.xml",
        "data/dojo_class_recurrence_cron.xml",
        "views/dojo_class_views.xml",
        "views/dojo_auto_enroll_views.xml",
    ],
    "application": True,
    "auto_install": True,
    "installable": True,
}
