import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Stage name constants — must match data/crm_stage.xml exactly
STAGE_NEW_LEAD = "New Lead"
STAGE_TRIAL_BOOKED = "Trial Booked"
STAGE_TRIAL_ATTENDED = "Trial Attended"
STAGE_OFFER_MADE = "Offer Made"
STAGE_CONVERTED = "Converted"


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # ------------------------------------------------------------------
    # Dojo-specific fields
    # ------------------------------------------------------------------

    dojo_member_id = fields.Many2one(
        "dojo.member",
        string="Dojo Member",
        ondelete="set null",
        help="Populated when this lead is converted to a dojo member.",
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

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends("dojo_member_id")
    def _compute_is_converted(self):
        for rec in self:
            rec.is_converted = bool(rec.dojo_member_id)

    # ------------------------------------------------------------------
    # Override write — capture no_show_date when no_show is first set
    # ------------------------------------------------------------------

    def write(self, vals):
        if vals.get("no_show") is True and "no_show_date" not in vals:
            today = fields.Date.today()
            # Stamp no_show_date only on records transitioning False→True
            # that don't already have a stored date, preserving historical values.
            needs_date = self.filtered(lambda r: not r.no_show and not r.no_show_date)
            has_date = self - needs_date
            if needs_date:
                super(CrmLead, needs_date).write(dict(vals, no_show_date=today))
            if has_date:
                super(CrmLead, has_date).write(vals)
            return True
        return super().write(vals)

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
                    # SMS follow-up
                    mobile = lead.mobile or (lead.partner_id.mobile if lead.partner_id else False)
                    if mobile:
                        body = _(
                            "We missed you! Reschedule your free trial at "
                            "%(company)s — reply or call us to pick a new date.",
                            company=lead.company_id.name or "our dojo",
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
                mobile = lead.mobile or (lead.partner_id.mobile if lead.partner_id else False)
                if mobile and lead.trial_session_id:
                    session = lead.trial_session_id
                    body = _(
                        "Reminder: your free trial at %(company)s is tomorrow — "
                        "%(session)s at %(start)s. See you there!",
                        company=lead.company_id.name or "the dojo",
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
            [("name", "=", STAGE_OFFER_MADE)], limit=1
        )
        attended_stage = self.env["crm.stage"].search(
            [("name", "=", STAGE_TRIAL_ATTENDED)], limit=1
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
                # SMS nudge
                mobile = lead.mobile or (lead.partner_id.mobile if lead.partner_id else False)
                if mobile:
                    body = _(
                        "Heads up — your special membership offer from %(company)s "
                        "expires in 24 hours. Reply or call us to lock it in!",
                        company=lead.company_id.name or "the dojo",
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
            [("name", "=", STAGE_CONVERTED)], limit=1
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
                mobile = lead.mobile or (lead.partner_id.mobile if lead.partner_id else False)
                if mobile:
                    body = _(
                        "Hey! We'd still love to have you try a class at %(company)s. "
                        "Reply or call us to book a new trial — no pressure!",
                        company=lead.company_id.name or "the dojo",
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
