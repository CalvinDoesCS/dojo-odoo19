import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DojoClassSession(models.Model):
    _inherit = "dojo.class.session"

    calendar_event_id = fields.Many2one(
        "calendar.event",
        string="Calendar Event",
        ondelete="set null",
        readonly=True,
        copy=False,
        index=True,
        help="The calendar event automatically created for this session.",
    )

    # ------------------------------------------------------------------
    # Calendar sync helpers
    # ------------------------------------------------------------------

    def _dojo_calendar_event_vals(self):
        """Return vals dict to create/update the linked calendar.event."""
        self.ensure_one()
        name = (
            self.name
            or (self.template_id.name if self.template_id else False)
            or "Dojang Class"
        )
        partner_ids = []
        if self.instructor_profile_id and self.instructor_profile_id.partner_id:
            partner_ids.append(self.instructor_profile_id.partner_id.id)
        vals = {
            "name": name,
            "start": self.start_datetime,
            "stop": self.end_datetime,
            "x_session_id": self.id,
            "x_capacity": self.capacity or 0,
            # public so all internal users see it in the standard Calendar app
            "privacy": "public",
            "show_as": "busy",
        }
        if partner_ids:
            vals["partner_ids"] = [(6, 0, partner_ids)]
        if self.instructor_profile_id and self.instructor_profile_id.user_id:
            vals["user_id"] = self.instructor_profile_id.user_id.id
        return vals

    def _sync_calendar_event(self):
        """Create or update the linked calendar.event for this session."""
        CalendarEvent = self.env["calendar.event"].with_context(
            no_mail_for_attendees=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
        )
        for session in self:
            vals = session._dojo_calendar_event_vals()
            if session.calendar_event_id:
                session.calendar_event_id.sudo().write(vals)
            else:
                event = CalendarEvent.sudo().create(vals)
                # Use direct SQL to avoid re-triggering write hooks
                session.with_context(no_calendar_sync=True).sudo().write(
                    {"calendar_event_id": event.id}
                )

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        sessions._sync_calendar_event()
        return sessions

    def write(self, vals):
        result = super().write(vals)
        # Skip sync when we're only writing the calendar_event_id itself or
        # when we're already inside a sync call
        if self.env.context.get("no_calendar_sync"):
            return result
        sync_trigger_fields = {
            "start_datetime",
            "end_datetime",
            "name",
            "capacity",
            "instructor_profile_id",
            "template_id",
            "state",
        }
        if sync_trigger_fields & set(vals):
            self._sync_calendar_event()
        return result

    def unlink(self):
        # Collect events before unlinking sessions
        events = self.mapped("calendar_event_id").sudo()
        result = super().unlink()
        events.with_context(
            no_mail_for_attendees=True,
        ).unlink()
        return result
