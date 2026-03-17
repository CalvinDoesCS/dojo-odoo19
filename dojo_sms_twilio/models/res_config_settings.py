import uuid as _uuid

from odoo import api, fields, models

from odoo.addons.dojo_sms_twilio.tools.sms_api_twilio import SmsApiTwilio


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    twilio_account_sid = fields.Char(
        string="Account SID",
        config_parameter="twilio.account_sid",
    )
    twilio_auth_token = fields.Char(
        string="Auth Token",
        config_parameter="twilio.auth_token",
    )
    twilio_from_number = fields.Char(
        string="From Number",
        help="Twilio phone number in E.164 format, e.g. +15551234567",
        config_parameter="twilio.from_number",
    )

    def action_test_twilio_sms(self):
        """Send a test SMS to the company's phone number to verify Twilio config."""
        self.ensure_one()
        SmsApiTwilio(self.env)._send_sms_batch(
            [
                {
                    "content": "Dojo Twilio test: configuration is working.",
                    "numbers": [
                        {
                            "uuid": str(_uuid.uuid4()),
                            "number": self.twilio_from_number or "",
                        }
                    ],
                }
            ]
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Test SMS Sent",
                "message": "Check your Twilio logs for delivery status.",
                "type": "success",
                "sticky": False,
            },
        }
