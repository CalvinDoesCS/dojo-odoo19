{
    'name': 'Dojo Member Portal',
    'version': '19.0.2.0.0',
    'summary': 'Self-service portal for dojo parents and students',
    'description': """
        Extends the Odoo website portal (/my) with dojo-specific pages:
        - My Schedule: browse upcoming open class sessions
        - My Attendance: attendance history for all household members
        - My Invoices: view and download subscription invoices
        - My Household: update household info and emergency contacts
    """,
    'author': 'Dojo',
    'category': 'Dojo',
    'license': 'LGPL-3',
    'application': False,
    'installable': True,
    'auto_install': True,
    'depends': [
        'portal',
        'account',
        'dojo_members',
        'dojo_classes',
        'dojo_attendance',
        'dojo_subscriptions',
        'dojo_stripe',
        'dojo_belt_progression',
    ],
    'data': [
        'security/dojo_portal_security.xml',
        'security/ir.model.access.csv',
        'views/portal_layout.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'dojo_members_portal/static/src/css/dojo_portal.css',
            'dojo_members_portal/static/src/js/dojo_portal.js',
        ],
    },
}
