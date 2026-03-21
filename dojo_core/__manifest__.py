{
    'name': 'Dojo Management',
    'version': '19.0.1.0.0',
    'category': 'Martial Arts',
    'summary': 'Complete martial arts facility management suite',
    'description': """
        Single install point for the full Dojo Management system.
        Installing this app installs all dojo_* modules and exposes
        a unified menu covering members, classes, attendance,
        subscriptions, belt progression, CRM, communications,
        kiosk, social media, and configuration.
    """,
    'author': 'Dojo Team',
    'application': True,
    'installable': True,
    'auto_install': False,
    'depends': [
        # Foundation
        'dojo_base',
        'dojo_members',
        # Scheduling & Attendance
        'dojo_classes',
        'dojo_attendance',
        'dojo_calendar',
        # Billing
        'dojo_subscriptions',
        'dojo_stripe',
        'dojo_onboarding_stripe',
        'dojo_credits',
        # Member Lifecycle
        'dojo_onboarding',
        'dojo_crm',
        'dojo_belt_progression',
        # Communications & Marketing
        'dojo_communications',
        'dojo_marketing',
        'dojo_social',
        # Interfaces
        'dojo_kiosk',
        'dojo_members_portal',
        'dojo_checkout',
        # Intelligence & Integrations
        'dojo_assistant',
        'dojo_bridge',
        'dojo_sign',
    ],
    'data': [
        'views/dojo_core_menus.xml',
        'views/dojo_core_settings.xml',
    ],
    'license': 'LGPL-3',
}
