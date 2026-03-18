# -*- coding: utf-8 -*-
import logging
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_GRAPH_API = "https://graph.facebook.com/v19.0"


class DojoSocialAccount(models.Model):
    _name = "dojo.social.account"
    _description = "Social Media Account"
    _order = "platform, name"

    name = fields.Char("Account Name", required=True)
    platform = fields.Selection(
        [("facebook", "Facebook Page"), ("instagram", "Instagram Business")],
        required=True,
        default="facebook",
    )
    page_id = fields.Char("Page / Account ID", required=True)
    access_token = fields.Char("Access Token", required=True)
    status = fields.Selection(
        [("connected", "Connected"), ("error", "Error"), ("disconnected", "Disconnected")],
        default="disconnected",
        readonly=True,
    )
    error_message = fields.Char("Last Error", readonly=True)
    post_ids = fields.One2many("dojo.social.post", "account_id", string="Posts")
    post_count = fields.Integer("Posts", compute="_compute_post_count")

    @api.depends("post_ids")
    def _compute_post_count(self):
        for rec in self:
            rec.post_count = len(rec.post_ids)

    # ─── App credentials (stored in ir.config_parameter) ─────────────────────

    @api.model
    def _get_app_id(self):
        return self.env["ir.config_parameter"].sudo().get_param("dojo_social.fb_app_id", "")

    @api.model
    def _get_app_secret(self):
        return self.env["ir.config_parameter"].sudo().get_param("dojo_social.fb_app_secret", "")

    # ─── Actions ─────────────────────────────────────────────────────────────

    def action_connect_facebook(self):
        """Start Facebook OAuth flow — redirects to Facebook login."""
        self.ensure_one()
        app_id = self._get_app_id()
        if not app_id:
            raise UserError(
                "Facebook App ID is not configured. "
                "Go to Settings → Technical → System Parameters and set dojo_social.fb_app_id."
            )
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        redirect_uri = f"{base_url}/dojo/social/facebook/callback"
        scope = "pages_manage_posts,pages_read_engagement,instagram_basic,instagram_content_publish"
        oauth_url = (
            f"https://www.facebook.com/v19.0/dialog/oauth"
            f"?client_id={app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&state={self.id}"
            f"&response_type=code"
        )
        return {
            "type": "ir.actions.act_url",
            "url": oauth_url,
            "target": "new",
        }

    def action_test_connection(self):
        """Ping the Graph API to verify the stored token is valid."""
        self.ensure_one()
        if not self.access_token or not self.page_id:
            raise UserError("Access token and Page ID are required before testing.")

        try:
            resp = requests.get(
                f"{_GRAPH_API}/{self.page_id}",
                params={"access_token": self.access_token, "fields": "id,name"},
                timeout=10,
            )
            data = resp.json()
        except Exception as e:
            self.write({"status": "error", "error_message": str(e)})
            raise UserError(f"Connection failed: {e}")

        if "error" in data:
            msg = data["error"].get("message", "Unknown error")
            self.write({"status": "error", "error_message": msg})
            raise UserError(f"Facebook API error: {msg}")

        self.write({
            "status": "connected",
            "error_message": False,
            "name": data.get("name", self.name),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Connected",
                "message": f"Successfully connected to '{data.get('name')}'.",
                "type": "success",
            },
        }

    def action_disconnect(self):
        """Clear token and mark disconnected."""
        self.ensure_one()
        self.write({"access_token": "", "status": "disconnected", "error_message": False})

    def action_view_posts(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Posts",
            "res_model": "dojo.social.post",
            "view_mode": "kanban,list,form",
            "domain": [("account_id", "=", self.id)],
            "context": {"default_account_id": self.id},
        }
