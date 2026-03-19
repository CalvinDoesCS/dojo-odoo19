import logging

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class DojoSendMessageWizard(models.TransientModel):
    """
    Wizard that lets an instructor compose and send a manual SMS + email
    to selected students' primary guardians (or the students themselves
    when no household is set).
    """

    _name = "dojo.send.message.wizard"
    _description = "Send Message to Members / Guardians"

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    member_ids = fields.Many2many(
        "dojo.member",
        string="Recipients (Members)",
        help="Messages will be sent to the primary guardian of each household, "
             "or directly to the member if no household is set.",
    )
    subject = fields.Char(string="Subject", default="Message from Dojang")
    message_body = fields.Html(string="Message Body", required=True)
    send_email = fields.Boolean(string="Send Email", default=True)
    send_sms = fields.Boolean(string="Send SMS", default=True)

    # ------------------------------------------------------------------
    # Default member population (from context)
    # ------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Allow callers to pass a pre-selected member list via context
        member_ids = self.env.context.get("default_member_ids")
        if member_ids and "member_ids" in fields_list:
            res["member_ids"] = [(6, 0, member_ids)]
        return res

    # ------------------------------------------------------------------
    # Send action
    # ------------------------------------------------------------------

    def action_send(self):
        self.ensure_one()
        if not self.member_ids:
            return {"type": "ir.actions.act_window_close"}

        sent_emails = 0
        sent_sms = 0
        failed = 0

        # Collect unique guardian partners
        partner_map = {}  # partner_id → res.partner record
        for member in self.member_ids:
            household = member.partner_id.parent_id
            if household.is_household and household.primary_guardian_id:
                partner = household.primary_guardian_id
            else:
                partner = member.partner_id
            if partner.id not in partner_map:
                partner_map[partner.id] = partner

        for partner in partner_map.values():
            try:
                # ---- Email ----
                if self.send_email and partner.email:
                    mail = self.env["mail.mail"].create(
                        {
                            "subject": self.subject,
                            "body_html": self.message_body,
                            "email_to": partner.email,
                            "auto_delete": True,
                        }
                    )
                    mail.send()
                    sent_emails += 1

                # ---- SMS ----
                _sms_number = getattr(partner, 'mobile', None) or partner.phone
                if self.send_sms and _sms_number:
                    body_plain = html2plaintext(self.message_body)
                    self.env["sms.sms"].create(
                        {
                            "number": _sms_number,
                            "body": body_plain,
                            "partner_id": partner.id,
                        }
                    ).send()
                    sent_sms += 1

            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "dojo_communications: manual message failed for partner %s: %s",
                    partner.id,
                    exc,
                )
                failed += 1

        msg = _(
            "Messages sent — %(email)d email(s), %(sms)d SMS. %(failed)d failed.",
            email=sent_emails,
            sms=sent_sms,
            failed=failed,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Messages Sent"),
                "message": msg,
                "type": "success" if not failed else "warning",
                "sticky": False,
            },
        }
