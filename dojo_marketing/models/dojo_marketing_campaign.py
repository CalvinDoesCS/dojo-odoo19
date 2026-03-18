import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class DojoMarketingCampaign(models.Model):
    """
    Scheduled SMS / email campaign cards.

    Instructors create a campaign, configure its target audience and
    schedule, then activate it.  A daily cron (_cron_send_campaigns)
    dispatches every due campaign and advances the next_send_date for
    recurring ones.
    """

    _name = "dojo.marketing.campaign"
    _description = "Marketing Campaign"
    _order = "sequence, id"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # ── Identity ─────────────────────────────────────────────────────
    name = fields.Char(string="Campaign Name", required=True)
    sequence = fields.Integer(default=10)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("paused", "Paused"),
            ("done", "Done"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    # ── Targeting ────────────────────────────────────────────────────
    target_all = fields.Boolean(
        string="All Active Members",
        default=True,
        help="Send to every member with membership_state = active, "
             "ignoring the individual state/role filters below.",
    )

    # Membership state filters (only used when target_all=False)
    filter_lead = fields.Boolean(string="Leads", default=False)
    filter_trial = fields.Boolean(string="Trial", default=False)
    filter_active = fields.Boolean(string="Active", default=True)
    filter_paused = fields.Boolean(string="Paused", default=False)
    filter_cancelled = fields.Boolean(string="Cancelled", default=False)

    # Role filters (only used when target_all=False)
    filter_role_student = fields.Boolean(string="Students", default=True)
    filter_role_parent = fields.Boolean(string="Parents", default=True)
    filter_role_both = fields.Boolean(string="Standalone", default=True)

    # ── Schedule ─────────────────────────────────────────────────────
    schedule_type = fields.Selection(
        [
            ("one_time", "One-Time"),
            ("recurring", "Recurring"),
        ],
        string="Schedule Type",
        default="one_time",
        required=True,
    )
    scheduled_date = fields.Date(
        string="Send On",
        help="Date on which this one-time campaign will be sent.",
    )
    interval_number = fields.Integer(
        string="Every",
        default=7,
        help="Number of days/weeks/months between sends (recurring only).",
    )
    interval_type = fields.Selection(
        [
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        string="Interval Unit",
        default="days",
    )
    next_send_date = fields.Date(
        string="Next Send Date",
        readonly=True,
        help="Populated when the campaign is activated. Automatically advanced "
             "after each recurring dispatch.",
    )

    # ── Channels ─────────────────────────────────────────────────────
    send_email = fields.Boolean(string="Send Email", default=True)
    send_sms = fields.Boolean(string="Send SMS", default=True)

    # ── Content ──────────────────────────────────────────────────────
    subject = fields.Char(
        string="Email Subject",
        help="Subject line for the email. Not used for SMS-only campaigns.",
    )
    body_email = fields.Html(
        string="Email Body",
        help="HTML content for the email. Leave blank to skip email.",
    )
    body_sms = fields.Text(
        string="SMS Body",
        help="Plain-text SMS message. Leave blank to skip SMS.",
    )

    # ── Stats (readonly) ────────────────────────────────────────────
    last_sent_date = fields.Datetime(string="Last Sent", readonly=True)
    sent_count = fields.Integer(string="Times Sent", default=0, readonly=True)

    # ── Computed helpers ─────────────────────────────────────────────
    recipient_count = fields.Integer(
        string="Recipients",
        compute="_compute_recipient_count",
    )

    @api.depends(
        "target_all",
        "filter_lead", "filter_trial", "filter_active",
        "filter_paused", "filter_cancelled",
        "filter_role_student", "filter_role_parent", "filter_role_both",
    )
    def _compute_recipient_count(self):
        for rec in self:
            domain = rec._build_domain()
            rec.recipient_count = self.env["dojo.member"].search_count(domain)

    # ── Domain builder ───────────────────────────────────────────────

    def _build_domain(self):
        """Return an ORM domain for dojo.member matching this campaign's target."""
        self.ensure_one()
        domain = [("active", "=", True)]

        if self.target_all:
            domain += [("membership_state", "=", "active")]
            return domain

        # Membership state filter
        states = []
        if self.filter_lead:
            states.append("lead")
        if self.filter_trial:
            states.append("trial")
        if self.filter_active:
            states.append("active")
        if self.filter_paused:
            states.append("paused")
        if self.filter_cancelled:
            states.append("cancelled")
        if states:
            domain += [("membership_state", "in", states)]
        else:
            # Nothing selected → no results
            domain += [("id", "=", False)]
            return domain

        # Role filter
        roles = []
        if self.filter_role_student:
            roles.append("student")
        if self.filter_role_parent:
            roles.append("parent")
        if self.filter_role_both:
            roles.append("both")
        if roles:
            domain += [("role", "in", roles)]
        else:
            domain += [("id", "=", False)]

        return domain

    # ── Dispatch ─────────────────────────────────────────────────────

    def _dispatch(self):
        """Send this campaign to all matching members."""
        self.ensure_one()
        if not (self.send_email or self.send_sms):
            return

        members = self.env["dojo.member"].sudo().search(self._build_domain())
        if not members:
            _logger.info("Campaign %s: no matching members, skipping.", self.name)
            return

        # Collect unique guardian/contact partners
        partner_map = {}
        for member in members:
            household = member.household_id
            if household and household.primary_guardian_id:
                partner = household.primary_guardian_id.partner_id
            else:
                partner = member.partner_id
            if partner and partner.id not in partner_map:
                partner_map[partner.id] = partner

        sent_emails = 0
        sent_sms = 0
        failed = 0

        for partner in partner_map.values():
            try:
                if self.send_email and self.body_email and partner.email:
                    mail = self.env["mail.mail"].sudo().create(
                        {
                            "subject": self.subject or self.name,
                            "body_html": self.body_email,
                            "email_to": partner.email,
                            "auto_delete": True,
                        }
                    )
                    mail.send()
                    sent_emails += 1

                _sms_number = getattr(partner, 'mobile', None) or partner.phone
                if self.send_sms and self.body_sms and _sms_number:
                    self.env["sms.sms"].sudo().create(
                        {
                            "number": _sms_number,
                            "body": self.body_sms,
                            "partner_id": partner.id,
                        }
                    ).send()
                    sent_sms += 1

            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "Campaign %s: send failed for partner %s: %s",
                    self.name,
                    partner.id,
                    exc,
                )
                failed += 1

        self.sudo().write(
            {
                "last_sent_date": fields.Datetime.now(),
                "sent_count": self.sent_count + 1,
            }
        )
        _logger.info(
            "Campaign '%s': %d email(s), %d SMS, %d failed.",
            self.name, sent_emails, sent_sms, failed,
        )

    def _advance_next_send_date(self):
        """Advance next_send_date by the configured interval (recurring only)."""
        self.ensure_one()
        base = self.next_send_date or date.today()
        n = max(1, self.interval_number)
        if self.interval_type == "months":
            self.next_send_date = base + relativedelta(months=n)
        elif self.interval_type == "weeks":
            self.next_send_date = base + relativedelta(weeks=n)
        else:
            self.next_send_date = base + relativedelta(days=n)

    # ── Cron entry point ─────────────────────────────────────────────

    @api.model
    def _cron_send_campaigns(self):
        """Daily cron: fire every active campaign that is due today."""
        today = date.today()
        campaigns = self.sudo().search([("state", "=", "active")])
        for campaign in campaigns:
            try:
                due = False
                if campaign.schedule_type == "one_time":
                    due = campaign.scheduled_date and campaign.scheduled_date <= today
                else:
                    due = campaign.next_send_date and campaign.next_send_date <= today

                if not due:
                    continue

                campaign._dispatch()

                if campaign.schedule_type == "one_time":
                    campaign.state = "done"
                else:
                    campaign._advance_next_send_date()

            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "Campaign cron: unhandled error for campaign %s (%s): %s",
                    campaign.id, campaign.name, exc,
                )

    # ── State transitions ─────────────────────────────────────────────

    def action_activate(self):
        for rec in self:
            if not (rec.send_email or rec.send_sms):
                raise UserError(
                    _("Please enable at least one channel (Email or SMS) before activating.")
                )
            if rec.send_email and not rec.body_email:
                raise UserError(_("Email body is required when 'Send Email' is enabled."))
            if rec.send_sms and not rec.body_sms:
                raise UserError(_("SMS body is required when 'Send SMS' is enabled."))

            if rec.schedule_type == "one_time":
                if not rec.scheduled_date:
                    raise UserError(_("Please set a send date for this one-time campaign."))
                rec.next_send_date = rec.scheduled_date
            else:
                if rec.interval_number < 1:
                    raise UserError(_("Interval must be at least 1."))
                if not rec.next_send_date:
                    rec.next_send_date = date.today()

            rec.state = "active"

    def action_pause(self):
        self.filtered(lambda r: r.state == "active").write({"state": "paused"})

    def action_resume(self):
        self.filtered(lambda r: r.state == "paused").write({"state": "active"})

    def action_reset_draft(self):
        self.filtered(lambda r: r.state in ("paused", "done")).write(
            {"state": "draft", "next_send_date": False}
        )
