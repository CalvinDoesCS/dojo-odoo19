import base64
import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Stage name constants — must match data/crm_stage.xml exactly
STAGE_NEW_LEAD = "New"
STAGE_QUALIFIED = "Qualified"
STAGE_TRIAL_BOOKED = "Trial Booked"
STAGE_TRIAL_IN_PROGRESS = "Trial-in-progress"
STAGE_EVALUATION = "Evaluation"
STAGE_WON = "Won"

# Lead-scoring weights
_SCORE_EMAIL = 10
_SCORE_PHONE = 10
_SCORE_SOURCE_REFERRAL = 20
_SCORE_SOURCE_WALKIN = 15
_SCORE_SOURCE_ONLINE = 10
_SCORE_SOURCE_EVENT = 15
_SCORE_INTEREST_TAG = 15
_SCORE_AGE_TAG = 5
_SCORE_BOOKING_CLICKED = 10
_SCORE_TRIAL_ATTENDED = 15

# Source tag names (must match data/crm_tag.xml)
_SOURCE_SCORE_MAP = {
    "Referral": _SCORE_SOURCE_REFERRAL,
    "Walk-In": _SCORE_SOURCE_WALKIN,
    "Online": _SCORE_SOURCE_ONLINE,
    "Event": _SCORE_SOURCE_EVENT,
}
_INTEREST_TAGS = {"Adult BJJ", "Kids BJJ", "Muay Thai"}
_AGE_TAGS = {"Adult", "Teen", "Child"}


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # ------------------------------------------------------------------
    # Dojo-specific fields
    # ------------------------------------------------------------------

    dojo_member_id = fields.Many2one(
        "dojo.member",
        string="Dojang Member",
        ondelete="set null",
        help="Populated when this lead is converted to a Dojang member.",
    )
    trial_session_id = fields.Many2one(
        "dojo.class.session",
        string="Trial Session",
        domain="[('state', 'in', ['draft', 'open'])]",
        help="The class session booked for this lead's free trial.",
    )
    trial_attended = fields.Boolean(
        string="Trial Attended",
        default=False,
    )
    trial_reminder_sent = fields.Boolean(
        string="Trial Reminder Sent",
        default=False,
        help="Set to True once the 24h-before trial reminder email/SMS has been sent.",
    )
    offer_sent_date = fields.Date(
        string="Offer Sent Date",
        readonly=True,
    )
    offer_expiry_followup_sent = fields.Boolean(
        string="Offer Expiry Nudge Sent",
        default=False,
        help="Set once the 72h offer-expiry urgency email has been sent.",
    )
    no_show = fields.Boolean(
        string="No-Show",
        default=False,
        help="Set automatically 48h after trial booking if the lead is still in Trial Booked stage.",
    )
    no_show_date = fields.Date(
        string="No-Show Date",
        readonly=True,
        help="Date the lead was first marked as no-show.",
    )
    no_show_followup_sent = fields.Boolean(
        string="No-Show 2nd Follow-Up Sent",
        default=False,
        help="Set once the 5-day second no-show follow-up email has been sent.",
    )
    is_converted = fields.Boolean(
        string="Converted to Member",
        compute="_compute_is_converted",
        store=True,
    )

    # ── Trial booking tokens ─────────────────────────────────────────────
    trial_booking_token = fields.Char(
        string="Booking Token",
        copy=False,
        readonly=True,
        index=True,
        help="Unique token for the public trial-booking page.",
    )
    trial_cancel_token = fields.Char(
        string="Manage Token",
        copy=False,
        readonly=True,
        index=True,
        help="Unique token for the public cancel/reschedule page.",
    )
    trial_token_expires = fields.Datetime(
        string="Token Expires",
        readonly=True,
    )
    trial_booking_url = fields.Char(
        string="Booking URL",
        compute="_compute_trial_urls",
    )
    trial_manage_url = fields.Char(
        string="Manage URL",
        compute="_compute_trial_urls",
    )

    # ── Engagement tracking ──────────────────────────────────────────────
    booking_link_clicked = fields.Boolean(
        string="Booking Link Clicked",
        default=False,
        help="Set when the lead visits the public trial booking page.",
    )
    last_engagement_date = fields.Datetime(
        string="Last Engagement",
        help="Updated on stage change, email opens, or booking link clicks.",
    )

    # ── Lead scoring ─────────────────────────────────────────────────────
    dojo_lead_score = fields.Integer(
        string="Lead Score",
        compute="_compute_lead_score",
        store=True,
        help="Composite score 0–100 based on contact completeness, source, tags and engagement.",
    )

    # ── AI insights (populated when dojo_assistant is installed) ─────────
    ai_summary = fields.Text(
        string="AI Summary",
        readonly=True,
        help="Auto-generated lead summary from AI assistant.",
    )

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends("dojo_member_id")
    def _compute_is_converted(self):
        for rec in self:
            rec.is_converted = bool(rec.dojo_member_id)

    @api.depends("trial_booking_token", "trial_cancel_token")
    def _compute_trial_urls(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for rec in self:
            rec.trial_booking_url = (
                f"{base}/trial/book/{rec.trial_booking_token}"
                if rec.trial_booking_token
                else False
            )
            rec.trial_manage_url = (
                f"{base}/trial/manage/{rec.trial_cancel_token}"
                if rec.trial_cancel_token
                else False
            )

    @api.depends(
        "email_from", "phone", "tag_ids", "tag_ids.name",
        "booking_link_clicked", "trial_attended",
    )
    def _compute_lead_score(self):
        for rec in self:
            score = 0
            if rec.email_from:
                score += _SCORE_EMAIL
            if rec.phone:
                score += _SCORE_PHONE
            tag_names = set(rec.tag_ids.mapped("name"))
            for src_name, src_score in _SOURCE_SCORE_MAP.items():
                if src_name in tag_names:
                    score += src_score
                    break  # only one source tag counted
            if tag_names & _INTEREST_TAGS:
                score += _SCORE_INTEREST_TAG
            if tag_names & _AGE_TAGS:
                score += _SCORE_AGE_TAG
            if rec.booking_link_clicked:
                score += _SCORE_BOOKING_CLICKED
            if rec.trial_attended:
                score += _SCORE_TRIAL_ATTENDED
            rec.dojo_lead_score = min(score, 100)

    # ------------------------------------------------------------------
    # .ics calendar helpers
    # ------------------------------------------------------------------

    def _build_ics(self):
        """Return a bytes object containing an .ics VCALENDAR for the trial session."""
        self.ensure_one()
        session = self.trial_session_id
        if not session:
            return None
        # Format datetimes as iCal UTC strings
        fmt = "%Y%m%dT%H%M%SZ"
        dtstart = session.start_datetime.strftime(fmt) if session.start_datetime else ""
        dtend = session.end_datetime.strftime(fmt) if session.end_datetime else ""
        summary = f"Free Trial Class — {session.template_id.name or session.name}"
        location = self.company_id.name or "Dojang"
        uid = f"{self.trial_booking_token or self.id}@{location.replace(' ', '')}"
        description = (
            f"Your free trial class at {location}.\\n"
            f"Arrive 10 minutes early. Wear comfortable workout clothes."
        )
        manage_url = self.trial_manage_url or ""
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Dojang//CRM Trial//EN\r\n"
            "CALSCALE:GREGORIAN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTART:{dtstart}\r\n"
            f"DTEND:{dtend}\r\n"
            f"SUMMARY:{summary}\r\n"
            f"LOCATION:{location}\r\n"
            f"DESCRIPTION:{description}\\nManage booking: {manage_url}\r\n"
            "STATUS:CONFIRMED\r\n"
            "BEGIN:VALARM\r\n"
            "TRIGGER:-PT1H\r\n"
            "ACTION:DISPLAY\r\n"
            "DESCRIPTION:Trial class in 1 hour\r\n"
            "END:VALARM\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        return ics.encode("utf-8")

    def _get_ics_attachment(self):
        """Create a transient ir.attachment for the .ics file and return its id."""
        self.ensure_one()
        ics_data = self._build_ics()
        if not ics_data:
            return False
        attachment = self.env["ir.attachment"].create(
            {
                "name": "trial-booking.ics",
                "type": "binary",
                "datas": base64.b64encode(ics_data).decode(),
                "mimetype": "text/calendar",
                "res_model": "crm.lead",
                "res_id": self.id,
            }
        )
        return attachment

    # ------------------------------------------------------------------
    # Token generation
    # ------------------------------------------------------------------

    def _generate_trial_tokens(self):
        """Generate booking + manage tokens for the lead (idempotent)."""
        for rec in self:
            vals = {}
            if not rec.trial_booking_token:
                vals["trial_booking_token"] = str(uuid.uuid4())
            if not rec.trial_cancel_token:
                vals["trial_cancel_token"] = str(uuid.uuid4())
            if not rec.trial_token_expires:
                vals["trial_token_expires"] = fields.Datetime.now() + timedelta(days=7)
            if vals:
                rec.write(vals)

    # ------------------------------------------------------------------
    # Override write — stage change hooks
    # ------------------------------------------------------------------

    def write(self, vals):
        # ── no_show date stamping ────────────────────────────────────────
        if vals.get("no_show") is True and "no_show_date" not in vals:
            today = fields.Date.today()
            needs_date = self.filtered(lambda r: not r.no_show and not r.no_show_date)
            has_date = self - needs_date
            if needs_date:
                super(CrmLead, needs_date).write(dict(vals, no_show_date=today))
            if has_date:
                super(CrmLead, has_date).write(vals)
            return True

        # ── Detect stage transitions before super ────────────────────────
        old_stage_map = {}
        if "stage_id" in vals:
            for rec in self:
                old_stage_map[rec.id] = rec.stage_id.name

        result = super().write(vals)

        # ── Post-write stage-change hooks ────────────────────────────────
        if "stage_id" in vals:
            for rec in self:
                old_name = old_stage_map.get(rec.id)
                new_name = rec.stage_id.name
                if old_name == new_name:
                    continue
                rec._on_stage_change(old_name, new_name)

        # ── Engagement tracking ──────────────────────────────────────────
        engagement_fields = {"stage_id", "booking_link_clicked", "trial_attended"}
        if engagement_fields & set(vals.keys()):
            now = fields.Datetime.now()
            super(CrmLead, self).write({"last_engagement_date": now})

        return result

    def _on_stage_change(self, old_stage, new_stage):
        """Dispatch per-stage hooks after a stage transition."""
        if new_stage == STAGE_QUALIFIED:
            self._generate_trial_tokens()
        elif new_stage == STAGE_TRIAL_BOOKED:
            self._create_call_activity()
        elif new_stage == STAGE_TRIAL_IN_PROGRESS:
            self._schedule_post_trial_followups()

    # ------------------------------------------------------------------
    # Automation helpers
    # ------------------------------------------------------------------

    def _create_call_activity(self):
        """Create a 'Call' activity for the salesperson, due in 2 hours."""
        call_type = self.env.ref("mail.mail_activity_data_call", raise_if_not_found=False)
        if not call_type:
            return
        for rec in self:
            salesperson = rec.user_id or self.env.user
            session_info = ""
            if rec.trial_session_id:
                session_info = (
                    f"\nTrial session: {rec.trial_session_id.name} "
                    f"on {rec.trial_session_id.start_datetime}"
                )
            rec.activity_schedule(
                "mail.mail_activity_data_call",
                date_deadline=fields.Date.today(),
                summary=_("Follow up on trial booking for %s", rec.contact_name or rec.partner_name or "lead"),
                note=_(
                    "Call the lead to confirm attendance and answer questions.%s",
                    session_info,
                ),
                user_id=salesperson.id,
            )

    def _schedule_post_trial_followups(self):
        """Schedule Day 1 / Day 3 / Day 5 follow-up activities after trial attended."""
        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        call_type = self.env.ref("mail.mail_activity_data_call", raise_if_not_found=False)
        today = fields.Date.today()
        for rec in self:
            salesperson = rec.user_id or self.env.user
            # Day 1: email recap
            if todo_type:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=today + timedelta(days=1),
                    summary=_("Send recap email to %s", rec.contact_name or "lead"),
                    note=_("Send a personalised recap of their trial experience. Follow up on any questions."),
                    user_id=salesperson.id,
                )
            # Day 3: phone call
            if call_type:
                rec.activity_schedule(
                    "mail.mail_activity_data_call",
                    date_deadline=today + timedelta(days=3),
                    summary=_("Day 3 call — %s", rec.contact_name or "lead"),
                    note=_("Check in with the lead. Answer questions and present membership options."),
                    user_id=salesperson.id,
                )
            # Day 5: final offer follow-up
            if todo_type:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=today + timedelta(days=5),
                    summary=_("Final offer follow-up — %s", rec.contact_name or "lead"),
                    note=_("Last outreach before offer expires. Make the final pitch."),
                    user_id=salesperson.id,
                )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_view_converted_member(self):
        self.ensure_one()
        if not self.dojo_member_id:
            return {}
        return {
            "type": "ir.actions.act_window",
            "name": "Member",
            "res_model": "dojo.member",
            "res_id": self.dojo_member_id.id,
            "view_mode": "form",
        }

    def action_convert_to_member(self):
        """Open the Convert to Member wizard for this lead."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Convert to Member",
            "res_model": "dojo.convert.lead.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_lead_id": self.id},
        }

    # ------------------------------------------------------------------
    # Cron: mark no-shows 48h after booking
    # ------------------------------------------------------------------

    @api.model
    def _cron_mark_no_shows(self):
        """
        48h after moving to Trial Booked, if the lead is STILL in that stage
        and trial_attended is False, mark as no_show and send reschedule message.
        """
        trial_booked_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_TRIAL_BOOKED)], limit=1
        )
        if not trial_booked_stage:
            return

        cutoff = fields.Datetime.now() - timedelta(hours=48)
        leads = self.search(
            [
                ("stage_id", "=", trial_booked_stage.id),
                ("trial_attended", "=", False),
                ("no_show", "=", False),
                ("date_last_stage_update", "<=", cutoff),
            ]
        )

        no_show_template = self.env.ref(
            "dojo_crm.mail_template_no_show",
            raise_if_not_found=False,
        )

        for lead in leads:
            lead.no_show = True
            lead.no_show_date = fields.Date.today()
            lead.message_post(
                body=_("Lead automatically marked as no-show (48h elapsed since Trial Booked)."),
                subtype_xmlid="mail.mt_note",
            )
            if no_show_template and lead.partner_id:
                try:
                    no_show_template.send_mail(lead.id, force_send=True)
                    mobile = lead.phone or (lead.partner_id.phone if lead.partner_id else False)
                    if mobile:
                        body = _(
                            "We missed you! Reschedule your free trial at "
                            "%(company)s — reply or call us to pick a new date.",
                            company=lead.company_id.name or "our Dojang",
                        )
                        self.env["sms.sms"].create(
                            {
                                "number": mobile,
                                "body": body,
                                "partner_id": lead.partner_id.id if lead.partner_id else False,
                            }
                        ).send()
                except Exception as exc:  # noqa: BLE001
                    _logger.error(
                        "dojo_crm: no-show notification failed for lead %s: %s", lead.id, exc
                    )

        _logger.info("dojo_crm: marked %d lead(s) as no-show", len(leads))

    # ------------------------------------------------------------------
    # Cron: send 24h trial reminder to leads with upcoming sessions
    # ------------------------------------------------------------------

    @api.model
    def _cron_send_trial_reminders(self):
        """
        Hourly cron: for leads in Trial Booked stage whose trial session starts
        in the next 23–25h window, send a reminder email + SMS (once only).
        """
        trial_booked_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_TRIAL_BOOKED)], limit=1
        )
        if not trial_booked_stage:
            return

        now = fields.Datetime.now()
        window_start = now + timedelta(hours=23)
        window_end = now + timedelta(hours=25)

        leads = self.search(
            [
                ("stage_id", "=", trial_booked_stage.id),
                ("trial_attended", "=", False),
                ("trial_reminder_sent", "=", False),
                ("trial_session_id.start_datetime", ">=", window_start),
                ("trial_session_id.start_datetime", "<=", window_end),
            ]
        )

        reminder_template = self.env.ref(
            "dojo_crm.mail_template_trial_reminder",
            raise_if_not_found=False,
        )

        for lead in leads:
            try:
                if reminder_template and lead.email_from:
                    reminder_template.send_mail(lead.id, force_send=True)
                mobile = lead.phone or (lead.partner_id.phone if lead.partner_id else False)
                if mobile and lead.trial_session_id:
                    session = lead.trial_session_id
                    body = _(
                        "Reminder: your free trial at %(company)s is tomorrow — "
                        "%(session)s at %(start)s. See you there!",
                        company=lead.company_id.name or "the Dojang",
                        session=session.name,
                        start=session.start_datetime,
                    )
                    self.env["sms.sms"].create(
                        {
                            "number": mobile,
                            "body": body,
                            "partner_id": lead.partner_id.id if lead.partner_id else False,
                        }
                    ).send()
                lead.trial_reminder_sent = True
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: trial reminder failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: sent trial reminders to %d lead(s)", len(leads))

    # ------------------------------------------------------------------
    # Cron: offer expiry — 72h nudge + 7-day auto-lost
    # ------------------------------------------------------------------

    @api.model
    def _cron_offer_expiry(self):
        """
        Daily cron:
          • 72h after offer_sent_date → send urgency nudge email (once)
          • 7 days after offer_sent_date, still not converted → mark as lost
        """
        today = fields.Date.today()
        nudge_date = today - timedelta(days=3)
        auto_lost_date = today - timedelta(days=7)

        offer_made_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_EVALUATION)], limit=1
        )
        attended_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_TRIAL_IN_PROGRESS)], limit=1
        )

        nudge_template = self.env.ref(
            "dojo_crm.mail_template_offer_expiry_nudge",
            raise_if_not_found=False,
        )

        # --- 72h nudge ---
        nudge_domain = [
            ("is_converted", "=", False),
            ("offer_sent_date", "=", nudge_date),
            ("offer_expiry_followup_sent", "=", False),
        ]
        if offer_made_stage:
            nudge_domain.append(("stage_id", "=", offer_made_stage.id))

        nudge_leads = self.search(nudge_domain)
        for lead in nudge_leads:
            try:
                if nudge_template and lead.email_from:
                    nudge_template.send_mail(lead.id, force_send=True)
                mobile = lead.phone or (lead.partner_id.phone if lead.partner_id else False)
                if mobile:
                    body = _(
                        "Heads up — your special membership offer from %(company)s "
                        "expires in 24 hours. Reply or call us to lock it in!",
                        company=lead.company_id.name or "the Dojang",
                    )
                    self.env["sms.sms"].create(
                        {
                            "number": mobile,
                            "body": body,
                            "partner_id": lead.partner_id.id if lead.partner_id else False,
                        }
                    ).send()
                lead.offer_expiry_followup_sent = True
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: offer expiry nudge failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: sent offer expiry nudge to %d lead(s)", len(nudge_leads))

        # --- 7-day auto-lost ---
        lost_stage_ids = []
        if offer_made_stage:
            lost_stage_ids.append(offer_made_stage.id)
        if attended_stage:
            lost_stage_ids.append(attended_stage.id)

        if lost_stage_ids:
            lost_leads = self.search(
                [
                    ("is_converted", "=", False),
                    ("offer_sent_date", "<=", auto_lost_date),
                    ("stage_id", "in", lost_stage_ids),
                ]
            )
            for lead in lost_leads:
                try:
                    lead.action_set_lost(lost_reason_id=False)
                    lead.message_post(
                        body=_("Lead auto-lost: offer expired 7 days after sending."),
                        subtype_xmlid="mail.mt_note",
                    )
                except Exception as exc:  # noqa: BLE001
                    _logger.error(
                        "dojo_crm: auto-lost failed for lead %s: %s", lead.id, exc
                    )

            _logger.info("dojo_crm: auto-lost %d expired offer lead(s)", len(lost_leads))

    # ------------------------------------------------------------------
    # Cron: second no-show follow-up (5 days after no_show_date)
    # ------------------------------------------------------------------

    @api.model
    def _cron_no_show_followup(self):
        """
        Daily cron: 5 days after no_show_date, if the lead is still not converted,
        send a warm second follow-up email.
        """
        today = fields.Date.today()
        cutoff = today - timedelta(days=5)

        converted_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_WON)], limit=1
        )

        domain = [
            ("no_show", "=", True),
            ("no_show_followup_sent", "=", False),
            ("no_show_date", "<=", cutoff),
            ("is_converted", "=", False),
        ]
        if converted_stage:
            domain.append(("stage_id", "!=", converted_stage.id))

        leads = self.search(domain)

        followup_template = self.env.ref(
            "dojo_crm.mail_template_no_show_followup",
            raise_if_not_found=False,
        )

        for lead in leads:
            try:
                if followup_template and lead.email_from:
                    followup_template.send_mail(lead.id, force_send=True)
                mobile = lead.phone or (lead.partner_id.phone if lead.partner_id else False)
                if mobile:
                    body = _(
                        "Hey! We'd still love to have you try a class at %(company)s. "
                        "Reply or call us to book a new trial — no pressure!",
                        company=lead.company_id.name or "the Dojang",
                    )
                    self.env["sms.sms"].create(
                        {
                            "number": mobile,
                            "body": body,
                            "partner_id": lead.partner_id.id if lead.partner_id else False,
                        }
                    ).send()
                lead.no_show_followup_sent = True
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: no-show follow-up failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: sent no-show 2nd follow-up to %d lead(s)", len(leads))

    # ------------------------------------------------------------------
    # Cron: trial expiry — move expired trials to Trial Expired stage
    # ------------------------------------------------------------------

    @api.model
    def _cron_trial_expiry(self):
        """
        Daily cron: leads in Trial Booked whose trial session has passed
        and trial_attended is still False → move to Evaluation, notify.
        """
        trial_booked_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_TRIAL_BOOKED)], limit=1
        )
        evaluation_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_EVALUATION)], limit=1
        )
        if not trial_booked_stage or not evaluation_stage:
            return

        now = fields.Datetime.now()
        leads = self.search(
            [
                ("stage_id", "=", trial_booked_stage.id),
                ("trial_attended", "=", False),
                ("trial_session_id.start_datetime", "<", now),
            ]
        )

        expired_template = self.env.ref(
            "dojo_crm.mail_template_trial_expired", raise_if_not_found=False
        )
        owner_template = self.env.ref(
            "dojo_crm.mail_template_trial_expired_owner", raise_if_not_found=False
        )

        for lead in leads:
            try:
                lead.write({
                    "stage_id": evaluation_stage.id,
                    "no_show": True,
                    "no_show_date": fields.Date.today(),
                })
                lead.message_post(
                    body=_("Trial session passed without attendance — moved to Evaluation."),
                    subtype_xmlid="mail.mt_note",
                )
                # Re-engagement email to lead
                if expired_template and lead.email_from:
                    expired_template.send_mail(lead.id, force_send=True)
                # Internal notification to salesperson
                if owner_template and lead.user_id:
                    owner_template.send_mail(lead.id, force_send=True)
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: trial expiry failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: expired %d trial lead(s)", len(leads))

    # ------------------------------------------------------------------
    # Cron: auto-qualify leads with score >= 60
    # ------------------------------------------------------------------

    @api.model
    def _cron_auto_qualify(self):
        """
        Every 2 hours: leads in New Lead with dojo_lead_score >= 60
        auto-move to Qualified (triggers email automation with booking link).
        """
        new_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_NEW_LEAD)], limit=1
        )
        qualified_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_QUALIFIED)], limit=1
        )
        if not new_stage or not qualified_stage:
            return

        leads = self.search(
            [
                ("stage_id", "=", new_stage.id),
                ("dojo_lead_score", ">=", 60),
            ]
        )
        for lead in leads:
            try:
                lead.write({"stage_id": qualified_stage.id})
                lead.message_post(
                    body=_(
                        "Auto-qualified with lead score %(score)s/100.",
                        score=lead.dojo_lead_score,
                    ),
                    subtype_xmlid="mail.mt_note",
                )
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: auto-qualify failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: auto-qualified %d lead(s)", len(leads))

    # ------------------------------------------------------------------
    # Cron: win-back campaign for Trial Expired (weekly)
    # ------------------------------------------------------------------

    @api.model
    def _cron_winback(self):
        """
        Weekly: re-engage no-show leads in Evaluation stage (7–30 days old) with fresh booking link.
        After 30 days → auto-Lost.
        """
        today = fields.Date.today()
        evaluation_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_EVALUATION)], limit=1
        )
        if not evaluation_stage:
            return

        winback_template = self.env.ref(
            "dojo_crm.mail_template_trial_expired", raise_if_not_found=False
        )

        # --- Re-engage 7–30 day old no-show Evaluation leads ---
        cutoff_start = today - timedelta(days=30)
        cutoff_end = today - timedelta(days=7)
        leads = self.search(
            [
                ("stage_id", "=", evaluation_stage.id),
                ("no_show", "=", True),
                ("is_converted", "=", False),
                ("date_last_stage_update", ">=", fields.Datetime.to_datetime(cutoff_start)),
                ("date_last_stage_update", "<=", fields.Datetime.to_datetime(cutoff_end)),
            ]
        )
        for lead in leads:
            try:
                # Refresh tokens for a new 7-day booking window
                lead.write({
                    "trial_booking_token": str(uuid.uuid4()),
                    "trial_token_expires": fields.Datetime.now() + timedelta(days=7),
                    "trial_session_id": False,
                })
                if winback_template and lead.email_from:
                    winback_template.send_mail(lead.id, force_send=True)
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: win-back failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: sent win-back to %d lead(s)", len(leads))

        # --- Auto-lost after 30 days ---
        lost_cutoff = fields.Datetime.to_datetime(today - timedelta(days=30))
        stale_expired = self.search(
            [
                ("stage_id", "=", evaluation_stage.id),
                ("no_show", "=", True),
                ("is_converted", "=", False),
                ("date_last_stage_update", "<", lost_cutoff),
            ]
        )
        for lead in stale_expired:
            try:
                lead.action_set_lost(lost_reason_id=False)
                lead.message_post(
                    body=_("Auto-lost: no-show lead in Evaluation over 30 days with no re-engagement."),
                    subtype_xmlid="mail.mt_note",
                )
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: win-back auto-lost failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: auto-lost %d stale no-show lead(s)", len(stale_expired))

    # ------------------------------------------------------------------
    # Cron: stale lead cleanup (weekly)
    # ------------------------------------------------------------------

    @api.model
    def _cron_stale_leads(self):
        """
        Weekly: nudge salesperson at 14 days idle; auto-archive at 30 days.
        Only targets leads in New Lead stage.
        """
        today = fields.Date.today()
        new_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_NEW_LEAD)], limit=1
        )
        if not new_stage:
            return

        # --- 14+ day nudge to salesperson ---
        nudge_cutoff = fields.Datetime.to_datetime(today - timedelta(days=14))
        archive_cutoff = fields.Datetime.to_datetime(today - timedelta(days=30))

        nudge_leads = self.search(
            [
                ("stage_id", "=", new_stage.id),
                ("date_last_stage_update", "<=", nudge_cutoff),
                ("date_last_stage_update", ">", archive_cutoff),
                ("is_converted", "=", False),
            ]
        )
        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for lead in nudge_leads:
            if lead.user_id and todo_type:
                # Only create nudge if no open activities already exist
                existing = self.env["mail.activity"].search(
                    [
                        ("res_model", "=", "crm.lead"),
                        ("res_id", "=", lead.id),
                        ("activity_type_id", "=", todo_type.id),
                    ],
                    limit=1,
                )
                if not existing:
                    lead.activity_schedule(
                        "mail.mail_activity_data_todo",
                        date_deadline=today,
                        summary=_("Stale lead — %s idle for 14+ days", lead.contact_name or "lead"),
                        note=_("This lead has been in New Lead stage for over 14 days. Follow up or qualify."),
                        user_id=lead.user_id.id,
                    )

        _logger.info("dojo_crm: nudged salespeople for %d stale lead(s)", len(nudge_leads))

        # --- 30+ day auto-archive ---
        stale_leads = self.search(
            [
                ("stage_id", "=", new_stage.id),
                ("date_last_stage_update", "<=", archive_cutoff),
                ("is_converted", "=", False),
            ]
        )
        for lead in stale_leads:
            try:
                lead.action_set_lost(lost_reason_id=False)
                lead.message_post(
                    body=_("Auto-lost: lead idle in New stage for over 30 days."),
                    subtype_xmlid="mail.mt_note",
                )
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_crm: stale lead archive failed for lead %s: %s", lead.id, exc
                )

        _logger.info("dojo_crm: auto-lost %d stale lead(s)", len(stale_leads))
