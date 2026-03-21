import logging
import re

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DojoTrialBooking(http.Controller):
    """Public-facing trial booking and management pages."""

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_lead_by_booking_token(self, token):
        if not token:
            return None
        lead = (
            request.env["crm.lead"]
            .sudo()
            .search([("trial_booking_token", "=", token)], limit=1)
        )
        return lead if lead.exists() else None

    def _get_lead_by_manage_token(self, token):
        if not token:
            return None
        lead = (
            request.env["crm.lead"]
            .sudo()
            .search([("trial_cancel_token", "=", token)], limit=1)
        )
        return lead if lead.exists() else None

    def _get_trial_sessions(self):
        """Return upcoming open trial-program sessions with available capacity.

        Trial sessions are identified by their program name containing 'trial'
        (case-insensitive). Owners create these manually in the normal
        Program → Course → Session flow.
        """
        from odoo import fields as odoo_fields

        now = odoo_fields.Datetime.now()
        sessions = (
            request.env["dojo.class.session"]
            .sudo()
            .search(
                [
                    ("template_id.program_id.name", "ilike", "trial"),
                    ("state", "in", ["draft", "open"]),
                    ("start_datetime", ">", now),
                ],
                order="start_datetime asc",
                limit=30,
            )
        )
        return sessions

    # ── Book Trial ───────────────────────────────────────────────────────

    @http.route(
        "/trial/book/<string:token>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def trial_book_page(self, token, **kw):
        lead = self._get_lead_by_booking_token(token)
        if not lead:
            return request.render("dojo_crm.trial_token_expired")

        from odoo import fields as odoo_fields

        if lead.trial_token_expires and lead.trial_token_expires < odoo_fields.Datetime.now():
            return request.render("dojo_crm.trial_token_expired")

        # Already booked?
        if lead.trial_session_id:
            return request.render(
                "dojo_crm.trial_book_already",
                {"lead": lead, "session": lead.trial_session_id},
            )

        sessions = self._get_trial_sessions()
        return request.render(
            "dojo_crm.trial_book_page",
            {
                "lead": lead,
                "sessions": sessions,
                "error": kw.get("error"),
            },
        )

    @http.route(
        "/trial/book/<string:token>/confirm",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def trial_book_confirm(self, token, **kw):
        lead = self._get_lead_by_booking_token(token)
        if not lead:
            return request.render("dojo_crm.trial_token_expired")

        from odoo import fields as odoo_fields

        if lead.trial_token_expires and lead.trial_token_expires < odoo_fields.Datetime.now():
            return request.render("dojo_crm.trial_token_expired")

        session_id = int(kw.get("session_id", 0))
        if not session_id:
            return request.redirect(f"/trial/book/{token}?error=Please+select+a+session")

        session = (
            request.env["dojo.class.session"]
            .sudo()
            .browse(session_id)
            .exists()
        )
        if not session or session.state not in ("draft", "open"):
            return request.redirect(f"/trial/book/{token}?error=Session+no+longer+available")

        if session.seats_taken >= session.capacity:
            return request.redirect(f"/trial/book/{token}?error=Session+is+full")

        # Book the trial
        trial_booked_stage = (
            request.env["crm.stage"]
            .sudo()
            .search([("name", "=", "Trial Booked")], limit=1)
        )
        vals = {
            "trial_session_id": session.id,
            "trial_reminder_sent": False,
            "booking_link_clicked": True,
        }
        if trial_booked_stage:
            vals["stage_id"] = trial_booked_stage.id
        lead.write(vals)

        lead.message_post(
            body=f"Trial booked via public link: {session.name} on {session.start_datetime}",
            subtype_xmlid="mail.mt_note",
        )

        return request.render(
            "dojo_crm.trial_book_confirm_page",
            {"lead": lead, "session": session},
        )

    # ── Manage (Cancel / Reschedule) ─────────────────────────────────────

    @http.route(
        "/trial/manage/<string:token>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def trial_manage_page(self, token, **kw):
        lead = self._get_lead_by_manage_token(token)
        if not lead:
            return request.render("dojo_crm.trial_token_expired")

        if not lead.trial_session_id:
            return request.render(
                "dojo_crm.trial_manage_no_booking",
                {"lead": lead},
            )

        sessions = self._get_trial_sessions()
        return request.render(
            "dojo_crm.trial_manage_page",
            {
                "lead": lead,
                "session": lead.trial_session_id,
                "sessions": sessions,
                "error": kw.get("error"),
                "success": kw.get("success"),
            },
        )

    @http.route(
        "/trial/manage/<string:token>/cancel",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def trial_manage_cancel(self, token, **kw):
        lead = self._get_lead_by_manage_token(token)
        if not lead or not lead.trial_session_id:
            return request.render("dojo_crm.trial_token_expired")

        old_session = lead.trial_session_id.name
        qualified_stage = (
            request.env["crm.stage"]
            .sudo()
            .search([("name", "=", "Qualified")], limit=1)
        )
        vals = {
            "trial_session_id": False,
            "trial_reminder_sent": False,
            "no_show": False,
        }
        if qualified_stage:
            vals["stage_id"] = qualified_stage.id
        lead.write(vals)

        lead.message_post(
            body=f"Trial cancelled via manage link (was: {old_session})",
            subtype_xmlid="mail.mt_note",
        )

        return request.redirect(
            f"/trial/manage/{token}?success=Your+trial+has+been+cancelled"
        )

    @http.route(
        "/trial/manage/<string:token>/reschedule",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def trial_manage_reschedule(self, token, **kw):
        lead = self._get_lead_by_manage_token(token)
        if not lead:
            return request.render("dojo_crm.trial_token_expired")

        session_id = int(kw.get("session_id", 0))
        if not session_id:
            return request.redirect(
                f"/trial/manage/{token}?error=Please+select+a+new+session"
            )

        session = (
            request.env["dojo.class.session"]
            .sudo()
            .browse(session_id)
            .exists()
        )
        if not session or session.state not in ("draft", "open"):
            return request.redirect(
                f"/trial/manage/{token}?error=Session+no+longer+available"
            )

        if session.seats_taken >= session.capacity:
            return request.redirect(
                f"/trial/manage/{token}?error=Session+is+full"
            )

        old_session = lead.trial_session_id.name if lead.trial_session_id else "None"
        trial_booked_stage = (
            request.env["crm.stage"]
            .sudo()
            .search([("name", "=", "Trial Booked")], limit=1)
        )
        vals = {
            "trial_session_id": session.id,
            "trial_reminder_sent": False,
            "no_show": False,
        }
        if trial_booked_stage:
            vals["stage_id"] = trial_booked_stage.id
        lead.write(vals)

        lead.message_post(
            body=f"Trial rescheduled via manage link: {old_session} → {session.name}",
            subtype_xmlid="mail.mt_note",
        )

        return request.redirect(
            f"/trial/manage/{token}?success=Your+trial+has+been+rescheduled"
        )

    # ── Public Trial Sign-Up Form ─────────────────────────────────────────

    @http.route(
        "/trial",
        type="http",
        auth="public",
        website=True,
        sitemap=True,
        methods=["GET"],
    )
    def trial_signup_page(self, **kw):
        """Public website form — capture interest and create a new CRM lead."""
        return request.render(
            "dojo_crm.trial_signup_form",
            {"error": kw.get("error")},
        )

    @http.route(
        "/trial/submit",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
        methods=["POST"],
        csrf=True,
    )
    def trial_signup_submit(self, **kw):
        """Handle trial sign-up form submission — creates a New Lead in CRM."""
        name = (kw.get("name") or "").strip()
        email = (kw.get("email") or "").strip()
        phone = (kw.get("phone") or "").strip()
        discipline = (kw.get("discipline") or "").strip()
        message = (kw.get("message") or "").strip()

        # Basic validation
        if not name or not email:
            return request.redirect("/trial?error=Please+provide+your+name+and+email+address")

        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return request.redirect("/trial?error=Please+provide+a+valid+email+address")

        # Resolve tags
        discipline_tag_map = {
            "adult_bjj": "Adult BJJ",
            "kids_bjj": "Kids BJJ",
            "muay_thai": "Muay Thai",
        }
        tag_ids = []

        online_tag = (
            request.env["crm.tag"].sudo().search([("name", "=", "Online")], limit=1)
        )
        if online_tag:
            tag_ids.append((4, online_tag.id))

        if discipline in discipline_tag_map:
            disc_tag = (
                request.env["crm.tag"]
                .sudo()
                .search([("name", "=", discipline_tag_map[discipline])], limit=1)
            )
            if disc_tag:
                tag_ids.append((4, disc_tag.id))

        # Find "New Lead" stage
        new_lead_stage = (
            request.env["crm.stage"]
            .sudo()
            .search([("name", "=", "New Lead")], limit=1)
        )

        # Find or create a res.partner so automations (no-show email, SMS fallback) work
        Partner = request.env["res.partner"].sudo()
        partner = Partner.search([("email", "=ilike", email)], limit=1)
        if not partner:
            partner_vals = {"name": name, "email": email, "company_type": "person"}
            if phone:
                partner_vals["mobile"] = phone
            partner = Partner.create(partner_vals)
        else:
            if phone and not partner.mobile:
                partner.write({"mobile": phone})

        vals = {
            "name": f"Free Trial — {name}",
            "contact_name": name,
            "email_from": email,
            "partner_id": partner.id,
        }
        if phone:
            vals["phone"] = phone
        if tag_ids:
            vals["tag_ids"] = tag_ids
        if new_lead_stage:
            vals["stage_id"] = new_lead_stage.id
        if message:
            vals["description"] = message

        lead = request.env["crm.lead"].sudo().create(vals)
        lead.message_post(
            body="Lead created via website trial sign-up form.",
            subtype_xmlid="mail.mt_note",
        )

        return request.render(
            "dojo_crm.trial_signup_success",
            {"contact_name": name},
        )
