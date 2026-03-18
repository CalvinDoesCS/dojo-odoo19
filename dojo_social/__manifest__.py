{
    'name': 'Dojo Social Media',
    'version': '19.0.1.0.0',
    'summary': 'Facebook/Instagram post scheduling and publishing for the dojo',
    'author': 'Dojang',
    'category': 'Dojang',
    'license': 'LGPL-3',
    'application': False,
    'installable': True,
    'auto_install': False,
    'depends': [
        'base',
        'mail',
        'dojo_base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_social.xml',
        'views/dojo_social_account_views.xml',
        'views/dojo_social_post_views.xml',
        'views/dojo_social_menus.xml',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
}
