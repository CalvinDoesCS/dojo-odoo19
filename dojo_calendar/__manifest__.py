{
    "name": "Dojang Calendar",
    "version": "19.0.1.0.0",
    "summary": "Class Calendar — sync Dojang sessions to calendar.event with roster & attendance controls",
    "author": "Dojang",
    "category": "Dojang",
    "depends": ["dojo_classes", "dojo_attendance", "calendar"],
    "data": [
        "security/ir.model.access.csv",
        "views/calendar_event_view_inherit.xml",
        "views/calendar_class_action.xml",
    ],
    "post_init_hook": "_backfill_session_calendar_events",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
