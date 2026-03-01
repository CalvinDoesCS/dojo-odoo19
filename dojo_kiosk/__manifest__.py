{
    "name": "Dojo Kiosk",
    "summary": "Tablet check-in kiosk for dojo members and instructors",
    "version": "19.0.1.0.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojo",
    "depends": [
        "dojo_attendance",
        "dojo_members",
        "dojo_belt_progression",
        "dojo_subscriptions",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/dojo_kiosk_views.xml",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}
