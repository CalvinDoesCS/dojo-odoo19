# -*- coding: utf-8 -*-
import logging
import requests

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

_GRAPH_API = "https://graph.facebook.com/v19.0"


class DojoSocialOAuth(http.Controller):

    @http.route("/dojo/social/facebook/callback", type="http", auth="user", csrf=False)
    def facebook_callback(self, code=None, state=None, error=None, **kwargs):
        """
        Handle Facebook OAuth redirect.
        'state' contains the dojo.social.account ID.
        """
        base_url = request.env["ir.config_parameter"].sudo().get_param("web.base.url")

        if error:
            _logger.warning("Facebook OAuth error: %s", error)
            return request.redirect(
                f"{base_url}/odoo/action-dojo_social.action_dojo_social_account"
                f"?notification=Facebook connection was cancelled."
            )

        if not code or not state:
            return request.redirect(f"{base_url}/odoo/action-dojo_social.action_dojo_social_account")

        account_id = int(state)
        account = request.env["dojo.social.account"].sudo().browse(account_id)
        if not account.exists():
            _logger.error("Facebook callback: account %s not found", account_id)
            return request.redirect(f"{base_url}/odoo/action-dojo_social.action_dojo_social_account")

        icp = request.env["ir.config_parameter"].sudo()
        app_id = icp.get_param("dojo_social.fb_app_id", "")
        app_secret = icp.get_param("dojo_social.fb_app_secret", "")
        redirect_uri = f"{base_url}/dojo/social/facebook/callback"

        try:
            # Exchange code for short-lived user token
            token_resp = requests.get(
                f"{_GRAPH_API}/oauth/access_token",
                params={
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                timeout=15,
            )
            token_data = token_resp.json()
            if "error" in token_data:
                raise Exception(token_data["error"].get("message", "Token exchange failed"))

            user_token = token_data["access_token"]

            # Get the page access token
            pages_resp = requests.get(
                f"{_GRAPH_API}/{account.page_id}",
                params={
                    "fields": "id,name,access_token",
                    "access_token": user_token,
                },
                timeout=15,
            )
            page_data = pages_resp.json()
            if "error" in page_data:
                raise Exception(page_data["error"].get("message", "Failed to get page token"))

            page_token = page_data.get("access_token", user_token)
            page_name = page_data.get("name", account.name)

            account.write({
                "access_token": page_token,
                "name": page_name,
                "status": "connected",
                "error_message": False,
            })
            _logger.info("Facebook page '%s' connected to account %s", page_name, account_id)

        except Exception as e:
            _logger.error("Facebook OAuth callback failed: %s", e, exc_info=True)
            account.write({"status": "error", "error_message": str(e)})

        return request.redirect(
            f"{base_url}/odoo/action-dojo_social.action_dojo_social_account/{account_id}"
        )
