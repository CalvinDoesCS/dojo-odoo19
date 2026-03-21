{
    "name": "Dojang Marketing Cards",
    "summary": "Marketing cards with QR codes — published to kiosk carousel and member portal",
    "version": "19.0.1.0.0",
    "category": "Services",
    "license": "LGPL-3",
    "author": "Dojang",
    "depends": [
        "dojo_kiosk",
        "dojo_members",
        "dojo_members_portal",

        "mail",
        "sms",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_campaign.xml",
        "views/dojo_marketing_card_views.xml",
        "views/dojo_marketing_campaign_views.xml",
        "views/dojo_member_badge_button.xml",
        "views/portal_marketing_banner.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "dojo_marketing/static/src/dojo_marketing.css",
        ],
    },
    "application": False,
    "installable": True,
}
