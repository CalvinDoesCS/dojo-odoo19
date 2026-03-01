{
    "name": "Dojo Members",
    "summary": "Members and household management",
    "version": "19.0.1.0.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojo",
    "depends": ["dojo_base"],
    "data": [
        "security/ir.model.access.csv",
        "security/dojo_members_security.xml",
        "data/sequences.xml",
        "views/dojo_member_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": True,
    "auto_install": True,
    "installable": True,
}
