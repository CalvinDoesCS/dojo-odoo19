"""
member_routes.py
────────────────
Member read endpoints — all protected by @require_bridge_auth.

Routes
──────
GET /bridge/v1/members/me                → profile
GET /bridge/v1/members/me/subscriptions  → active memberships
GET /bridge/v1/members/me/rank           → belt rank + history
"""
import logging

from odoo import http
from odoo.http import request
from odoo.exceptions import UserError

from .auth_middleware import require_bridge_auth, bridge_response, bridge_error

_logger = logging.getLogger(__name__)


class BridgeMemberController(http.Controller):

    @http.route(
        "/bridge/v1/members/me",
        type="http",
        auth="public",
        methods=["GET", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def get_profile(self, b_env=None, b_member=None, b_company_id=None,
                    b_identity=None, b_payload=None, **kw):
        """
        Return the member profile for the authenticated user.

        If the identity has no linked member yet (recently provisioned),
        returns a 200 with member data set to null so the frontend can
        guide the user through a member-creation flow.
        """
        origin = request.httprequest.headers.get("Origin", "")

        if not b_member or not b_member.id:
            data = {
                "identity": b_identity.to_api_dict(),
                "member": None,
                "hint": "Member not yet linked. Call /bridge/v1/auth/resolve to provision.",
            }
        else:
            try:
                svc = b_env["x.bridge.service"].sudo()
                data = {
                    "identity": b_identity.to_api_dict(),
                    "member": svc.get_member_profile(b_member.id, b_company_id),
                }
            except UserError as exc:
                return bridge_error(str(exc), status=404)

        resp = bridge_response(data)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp

    @http.route(
        "/bridge/v1/members/me/subscriptions",
        type="http",
        auth="public",
        methods=["GET", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def get_subscriptions(self, b_env=None, b_member=None, b_company_id=None,
                          b_identity=None, b_payload=None, **kw):
        """Return all subscriptions for the authenticated member."""
        origin = request.httprequest.headers.get("Origin", "")

        if not b_member or not b_member.id:
            return bridge_error("No member linked to this identity.", status=404)

        try:
            svc = b_env["x.bridge.service"].sudo()
            data = svc.get_member_subscriptions(b_member.id, b_company_id)
        except UserError as exc:
            return bridge_error(str(exc), status=404)

        resp = bridge_response(data)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp

    @http.route(
        "/bridge/v1/members/me/rank",
        type="http",
        auth="public",
        methods=["GET", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def get_rank(self, b_env=None, b_member=None, b_company_id=None,
                 b_identity=None, b_payload=None, **kw):
        """Return current belt rank and full rank history for the authenticated member."""
        origin = request.httprequest.headers.get("Origin", "")

        if not b_member or not b_member.id:
            return bridge_error("No member linked to this identity.", status=404)

        try:
            svc = b_env["x.bridge.service"].sudo()
            data = svc.get_member_rank_history(b_member.id, b_company_id)
        except UserError as exc:
            return bridge_error(str(exc), status=404)

        resp = bridge_response(data)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp
