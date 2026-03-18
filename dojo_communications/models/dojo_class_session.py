import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class DojoClassSession(models.Model):
    _inherit = "dojo.class.session"

    reminder_sent = fields.Boolean(
        string="Reminder Sent",
        default=False,
        help="Set once the 24-hour prior reminder has been dispatched for this session.",
    )

    # ------------------------------------------------------------------
    # Cron — called hourly; finds sessions starting in ~24 hours
    # ------------------------------------------------------------------

    @api.model
    def _cron_send_reminders(self):
        """Dispatch 24-hour reminder SMS + email for upcoming sessions."""
        now = fields.Datetime.now()
        window_start = now + timedelta(hours=23)
        window_end = now + timedelta(hours=25)

        sessions = self.search(
            [
                ("state", "=", "open"),
                ("start_datetime", ">=", window_start),
                ("start_datetime", "<=", window_end),
                ("reminder_sent", "=", False),
            ]
        )

        email_template = self.env.ref(
            "dojo_communications.mail_template_reminder_email",
            raise_if_not_found=False,
        )
        sms_template = self.env.ref(
            "dojo_communications.mail_template_reminder_sms",
            raise_if_not_found=False,
        )

        for session in sessions:
            sent_to = set()
            for enrollment in session.enrollment_ids.filtered(
                lambda e: e.status == "registered"
            ):
                member = enrollment.member_id
                household = member.household_id

                # Resolve recipient
                if household and household.primary_guardian_id:
                    guardian_partner = household.primary_guardian_id.partner_id
                else:
                    guardian_partner = member.partner_id

                if guardian_partner.id in sent_to:
                    continue
                sent_to.add(guardian_partner.id)

                try:
                    # Email
                    if email_template and guardian_partner.email:
                        email_template.send_mail(
                            session.id,
                            force_send=True,
                            email_values={"email_to": guardian_partner.email},
                        )

                    # SMS
                    _guardian_sms = getattr(guardian_partner, 'mobile', None) or guardian_partner.phone
                    if sms_template and _guardian_sms:
                        body = sms_template._render_field(
                            "body_html", [session.id], compute_lang=True
                        )[session.id]
                        body_plain = (
                            html2plaintext(body)
                            if body
                            else f"Reminder: {session.name} is tomorrow."
                        )
                        self.env["sms.sms"].create(
                            {
                                "number": _guardian_sms,
                                "body": body_plain,
                                "partner_id": guardian_partner.id,
                            }
                        ).send()
                except Exception as exc:  # noqa: BLE001
                    _logger.error(
                        "dojo_communications: reminder failed for session %s / partner %s: %s",
                        session.id,
                        guardian_partner.id,
                        exc,
                    )

            session.reminder_sent = True
            _logger.info(
                "dojo_communications: sent reminders for session %s to %d recipients",
                session.name,
                len(sent_to),
            )

    # ------------------------------------------------------------------
    # Wizard launcher
    # ------------------------------------------------------------------

    def action_message_all_enrolled(self):
        """Open the Send Message wizard pre-loaded with all registered members."""
        self.ensure_one()
        member_ids = self.enrollment_ids.filtered(
            lambda e: e.status == "registered"
        ).mapped("member_id").ids
        return {
            "type": "ir.actions.act_window",
            "name": "Message All Enrolled",
            "res_model": "dojo.send.message.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_member_ids": [(6, 0, member_ids)]},
        }
