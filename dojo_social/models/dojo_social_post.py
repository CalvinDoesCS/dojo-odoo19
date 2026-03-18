# -*- coding: utf-8 -*-
import base64
import logging
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_GRAPH_API = "https://graph.facebook.com/v19.0"


class DojoSocialPost(models.Model):
    _name = "dojo.social.post"
    _description = "Social Media Post"
    _inherit = ["mail.thread"]
    _order = "scheduled_date desc, id desc"

    name = fields.Char("Title", compute="_compute_name", store=True)
    account_id = fields.Many2one(
        "dojo.social.account", string="Account", required=True, ondelete="cascade"
    )
    platform = fields.Selection(related="account_id.platform", store=True)
    message = fields.Text("Post Message", required=True)
    image = fields.Binary("Image", attachment=True)
    image_filename = fields.Char("Image Filename")
    scheduled_date = fields.Datetime("Scheduled Date")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("posted", "Posted"),
            ("failed", "Failed"),
        ],
        default="draft",
        tracking=True,
    )
    external_post_id = fields.Char("Platform Post ID", readonly=True, copy=False)
    posted_at = fields.Datetime("Posted At", readonly=True)
    error_message = fields.Char("Error", readonly=True)

    @api.depends("message")
    def _compute_name(self):
        for rec in self:
            rec.name = (rec.message or "")[:60] or "Post"

    # ─── State transitions ────────────────────────────────────────────────────

    def action_schedule(self):
        """Move draft post to scheduled state."""
        for rec in self:
            if not rec.scheduled_date:
                raise UserError("Please set a Scheduled Date before scheduling.")
            rec.write({"state": "scheduled", "error_message": False})

    def action_reset_draft(self):
        for rec in self:
            rec.write({"state": "draft", "error_message": False})

    # ─── Posting ─────────────────────────────────────────────────────────────

    def action_post_now(self):
        """Publish immediately to the connected platform."""
        self.ensure_one()
        account = self.account_id
        if account.status != "connected":
            raise UserError(
                f"Account '{account.name}' is not connected. "
                "Test the connection first."
            )
        self._do_post()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Posted",
                "message": f"Post published successfully to {account.name}.",
                "type": "success",
            },
        }

    def _do_post(self):
        """Internal: call Graph API and update record state."""
        self.ensure_one()
        account = self.account_id

        try:
            if self.image:
                post_id = self._post_with_photo(account)
            else:
                post_id = self._post_text_only(account)
        except Exception as e:
            self.write({"state": "failed", "error_message": str(e)})
            _logger.error("Social post %s failed: %s", self.id, e, exc_info=True)
            raise UserError(f"Failed to post: {e}")

        self.write({
            "state": "posted",
            "external_post_id": post_id,
            "posted_at": fields.Datetime.now(),
            "error_message": False,
        })

    def _post_text_only(self, account):
        """POST to /{page_id}/feed."""
        resp = requests.post(
            f"{_GRAPH_API}/{account.page_id}/feed",
            data={
                "message": self.message,
                "access_token": account.access_token,
            },
            timeout=15,
        )
        data = resp.json()
        if "error" in data:
            raise UserError(data["error"].get("message", "Graph API error"))
        return data.get("id")

    def _post_with_photo(self, account):
        """POST to /{page_id}/photos (publishes photo + caption)."""
        image_bytes = base64.b64decode(self.image)
        resp = requests.post(
            f"{_GRAPH_API}/{account.page_id}/photos",
            data={
                "caption": self.message,
                "access_token": account.access_token,
            },
            files={"source": (self.image_filename or "photo.jpg", image_bytes, "image/jpeg")},
            timeout=30,
        )
        data = resp.json()
        if "error" in data:
            raise UserError(data["error"].get("message", "Graph API error"))
        return data.get("post_id") or data.get("id")

    # ─── Cron: send scheduled posts ──────────────────────────────────────────

    @api.model
    def _cron_send_scheduled_posts(self):
        """Hourly cron — publish posts whose scheduled_date has passed."""
        now = fields.Datetime.now()
        due = self.search([
            ("state", "=", "scheduled"),
            ("scheduled_date", "<=", now),
        ])
        for post in due:
            try:
                post._do_post()
            except Exception as e:
                _logger.error("Cron: social post %s failed: %s", post.id, e)
