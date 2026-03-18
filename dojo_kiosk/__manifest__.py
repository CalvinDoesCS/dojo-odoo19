{
    "name": "Dojang Kiosk",
    "summary": "Tablet check-in kiosk for Dojang members and instructors",
    "version": "19.0.1.0.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojang",
    "depends": [
        "dojo_attendance",
        "dojo_members",
        "dojo_belt_progression",
        "dojo_subscriptions",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/dojo_kiosk_views.xml",
        "views/dojo_kiosk_announcement_views.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
