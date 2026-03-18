import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

STAGE_TRIAL_BOOKED = "Trial Booked"


class DojoAppointmentController(http.Controller):
    """
    Public trial-class booking controller.

    Route: /dojo/book-trial
    - GET  → renders session list + booking form
    - POST → creates/updates crm.lead, moves it to Trial Booked,
             fires existing automation (confirmation email + SMS)
    """

    @http.route("/dojo/book-trial", auth="public", website=True, methods=["GET"])
    def book_trial_page(self, **kw):
        """Render the public booking page with available trial sessions."""
        sessions = self._get_available_sessions()
        return request.render(
            "dojo_appointments.booking_page",
            {
                "sessions": sessions,
                "error": None,
                "success": False,
            },
        )

    @http.route("/dojo/book-trial", auth="public", website=True, methods=["POST"], csrf=True)
    def book_trial_submit(self, **post):
        """Process the booking form submission."""
        name = (post.get("name") or "").strip()
        email = (post.get("email") or "").strip().lower()
        mobile = (post.get("mobile") or "").strip()
        session_id = post.get("session_id")

        sessions = self._get_available_sessions()

        # --- Basic validation ---
        if not name or not email or not session_id:
            return request.render(
                "dojo_appointments.booking_page",
                {
                    "sessions": sessions,
                    "error": "Please fill in all required fields.",
                    "success": False,
                    "values": post,
                },
            )

        try:
            session_id = int(session_id)
        except (ValueError, TypeError):
            return request.render(
                "dojo_appointments.booking_page",
                {
                    "sessions": sessions,
                    "error": "Invalid session selected.",
                    "success": False,
                    "values": post,
                },
            )

        session = request.env["dojo.class.session"].sudo().browse(session_id)
        if not session.exists() or session.state not in ("draft", "open"):
            return request.render(
                "dojo_appointments.booking_page",
                {
                    "sessions": sessions,
                    "error": "That session is no longer available. Please choose another.",
                    "success": False,
                    "values": post,
                },
            )

        if session.capacity and session.seats_taken >= session.capacity:
            return request.render(
                "dojo_appointments.booking_page",
                {
                    "sessions": sessions,
                    "error": "Sorry, that session is fully booked. Please choose another.",
                    "success": False,
                    "values": post,
                },
            )

        # --- Find or create res.partner ---
        Partner = request.env["res.partner"].sudo()
        partner = Partner.search([("email", "=ilike", email)], limit=1)
        if not partner:
            partner = Partner.create(
                {
                    "name": name,
                    "email": email,
                    "mobile": mobile,
                    "company_type": "person",
                }
            )
        else:
            # Update phone if not yet set
            if mobile and not partner.phone:
                partner.write({"phone": mobile})

        # --- Find or create crm.lead ---
        trial_booked_stage = (
            request.env["crm.stage"]
            .sudo()
            .search([("name", "=", STAGE_TRIAL_BOOKED)], limit=1)
        )

        Lead = request.env["crm.lead"].sudo()
        # Look for an existing open lead for this partner that isn't yet converted
        lead = Lead.search(
            [
                ("partner_id", "=", partner.id),
                ("is_converted", "=", False),
                ("active", "=", True),
            ],
            order="id desc",
            limit=1,
        )

        if lead:
            lead.write(
                {
                    "trial_session_id": session_id,
                    "trial_reminder_sent": False,
                    **({"stage_id": trial_booked_stage.id} if trial_booked_stage else {}),
                }
            )
        else:
            lead_vals = {
                "name": f"Trial Booking — {name}",
                "contact_name": name,
                "email_from": email,
                "mobile": mobile,
                "partner_id": partner.id,
                "trial_session_id": session_id,
                "trial_reminder_sent": False,
            }
            if trial_booked_stage:
                lead_vals["stage_id"] = trial_booked_stage.id
            lead = Lead.create(lead_vals)

        _logger.info(
            "dojo_appointments: public booking — lead %d linked to session %d for %s",
            lead.id,
            session_id,
            email,
        )

        return request.render(
            "dojo_appointments.booking_page",
            {
                "sessions": sessions,
                "error": None,
                "success": True,
                "booked_session": session,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_available_sessions():
        """Return open/draft sessions in the next 60 days, ordered by start time."""
        from odoo import fields
        from datetime import timedelta

        now = fields.Datetime.now()
        cutoff = now + timedelta(days=60)
        return (
            request.env["dojo.class.session"]
            .sudo()
            .search(
                [
                    ("state", "in", ["draft", "open"]),
                    ("start_datetime", ">=", now),
                    ("start_datetime", "<=", cutoff),
                ],
                order="start_datetime asc",
            )
        )
