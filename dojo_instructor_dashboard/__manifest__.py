{
    'name': 'Dojo Instructor Dashboard',
    'version': '19.0.1.1.0',
    'summary': 'Instructor and admin backend dashboard with quick attendance, student roster, todos, and calendar',
    'description': """
        Provides a dedicated backend dashboard for Dojo instructors and admins:
        - Today's sessions with quick attendance marking
        - My Students roster (with medical flags)
        - My Todos (filtered view of project.task)
        - Class calendar scoped to the logged-in instructor
        - KPI computed fields on instructor profiles
    """,
    'author': 'Dojo',
    'category': 'Dojo',
    'license': 'LGPL-3',
    'application': True,
    'installable': True,
    'auto_install': True,
    'depends': [
        'dojo_classes',
        'dojo_attendance',
        'dojo_communications',
        'project',
        'account',
        'elevenlabs_connector',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/instructor_todos_data.xml',
        'data/ir_cron.xml',
        'views/dojo_instructor_dashboard_views.xml',
        'views/dojo_attendance_quick_views.xml',
        'views/dojo_member_profile_button.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dojo_instructor_dashboard/static/src/css/instructor_dashboard.css',
            'dojo_instructor_dashboard/static/src/xml/instructor_dashboard.xml',
            'dojo_instructor_dashboard/static/src/js/instructor_dashboard.js',
            'dojo_instructor_dashboard/static/src/xml/admin_dashboard.xml',
            'dojo_instructor_dashboard/static/src/js/admin_dashboard.js',
            'dojo_instructor_dashboard/static/src/xml/member_profile.xml',
            'dojo_instructor_dashboard/static/src/js/member_profile.js',
            'dojo_instructor_dashboard/static/src/xml/voice_assistant.xml',
            'dojo_instructor_dashboard/static/src/js/voice_assistant.js',
        ],
    },
}
