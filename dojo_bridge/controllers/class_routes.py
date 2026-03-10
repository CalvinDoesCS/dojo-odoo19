"""
class_routes.py
───────────────
Class/session endpoints — all protected by @require_bridge_auth.

Routes
──────
GET    /bridge/v1/classes/sessions                       → schedule
GET    /bridge/v1/classes/sessions/<id>                  → single session detail
POST   /bridge/v1/classes/sessions/<id>/enroll           → enroll
DELETE /bridge/v1/classes/sessions/<id>/enroll           → cancel enrollment
POST   /bridge/v1/classes/sessions/<id>/checkin          → record attendance
"""
import json
import logging
from datetime import datetime

from odoo import http
from odoo.http import request
from odoo.exceptions import UserError

from .auth_middleware import require_bridge_auth, bridge_response, bridge_error

_logger = logging.getLogger(__name__)


class BridgeClassController(http.Controller):

    # ── Schedule ──────────────────────────────────────────────────────────────

    @http.route(
        "/bridge/v1/classes/sessions",
        type="http",
        auth="public",
        methods=["GET", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def list_sessions(self, b_env=None, b_member=None, b_company_id=None,
                      b_identity=None, b_payload=None, **kw):
        """
        Return the class schedule for the tenant company.

        Query parameters:
          from        – ISO datetime string  (start of window)
          to          – ISO datetime string  (end of window)
          program_id  – int, filter by program
        """
        origin = request.httprequest.headers.get("Origin", "")
        params = request.httprequest.args

        from_dt = _parse_dt(params.get("from"))
        to_dt = _parse_dt(params.get("to"))
        program_id = _parse_int(params.get("program_id"))

        try:
            svc = b_env["x.bridge.service"].sudo()
            data = svc.get_sessions(
                company_id=b_company_id,
                from_dt=from_dt,
                to_dt=to_dt,
                program_id=program_id,
                member_id=b_member.id if b_member else None,
            )
        except UserError as exc:
            return bridge_error(str(exc), status=400)
        except Exception as exc:
            _logger.exception("Bridge list_sessions error: %s", exc)
            return bridge_error("Unexpected error.", status=500)

        resp = bridge_response(data)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp

    # ── Session detail ────────────────────────────────────────────────────────

    @http.route(
        "/bridge/v1/classes/sessions/<int:session_id>",
        type="http",
        auth="public",
        methods=["GET", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def get_session(self, session_id: int, b_env=None, b_member=None,
                    b_company_id=None, b_identity=None, b_payload=None, **kw):
        """Return detail for a single session + caller's enrollment status."""
        origin = request.httprequest.headers.get("Origin", "")
        try:
            svc = b_env["x.bridge.service"].sudo()
            data = svc.get_session_detail(
                session_id=session_id,
                company_id=b_company_id,
                member_id=b_member.id if b_member else None,
            )
        except UserError as exc:
            return bridge_error(str(exc), status=404)
        except Exception as exc:
            _logger.exception("Bridge get_session error: %s", exc)
            return bridge_error("Unexpected error.", status=500)

        resp = bridge_response(data)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp

    # ── Enroll ────────────────────────────────────────────────────────────────

    @http.route(
        "/bridge/v1/classes/sessions/<int:session_id>/enroll",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def enroll(self, session_id: int, b_env=None, b_member=None,
               b_company_id=None, b_identity=None, b_payload=None, **kw):
        """Enroll the authenticated member in a session."""
        origin = request.httprequest.headers.get("Origin", "")

        if not b_member or not b_member.id:
            return bridge_error("No member linked to this identity.", status=403)

        try:
            svc = b_env["x.bridge.service"].sudo()
            data = svc.do_enroll(
                session_id=session_id,
                member_id=b_member.id,
                company_id=b_company_id,
            )
            # Commit is handled by @require_bridge_auth on success
        except UserError as exc:
            return bridge_error(str(exc), status=409)
        except Exception as exc:
            _logger.exception("Bridge enroll error: %s", exc)
            return bridge_error("Unexpected error.", status=500)

        resp = bridge_response(data, status=201)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp

    # ── Cancel enrollment ─────────────────────────────────────────────────────

    @http.route(
        "/bridge/v1/classes/sessions/<int:session_id>/enroll",
        type="http",
        auth="public",
        methods=["DELETE", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def cancel_enrollment(self, session_id: int, b_env=None, b_member=None,
                          b_company_id=None, b_identity=None, b_payload=None, **kw):
        """Cancel the authenticated member's enrollment in a session."""
        origin = request.httprequest.headers.get("Origin", "")

        if not b_member or not b_member.id:
            return bridge_error("No member linked to this identity.", status=403)

        try:
            svc = b_env["x.bridge.service"].sudo()
            data = svc.do_cancel_enrollment(
                session_id=session_id,
                member_id=b_member.id,
                company_id=b_company_id,
            )
        except UserError as exc:
            return bridge_error(str(exc), status=404)
        except Exception as exc:
            _logger.exception("Bridge cancel_enrollment error: %s", exc)
            return bridge_error("Unexpected error.", status=500)

        resp = bridge_response(data)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp

    # ── Check-in ──────────────────────────────────────────────────────────────

    @http.route(
        "/bridge/v1/classes/sessions/<int:session_id>/checkin",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    @require_bridge_auth
    def checkin(self, session_id: int, b_env=None, b_member=None,
                b_company_id=None, b_identity=None, b_payload=None, **kw):
        """Record attendance for the authenticated member in a session."""
        origin = request.httprequest.headers.get("Origin", "")

        if not b_member or not b_member.id:
            return bridge_error("No member linked to this identity.", status=403)

        try:
            svc = b_env["x.bridge.service"].sudo()
            data = svc.do_checkin(
                session_id=session_id,
                member_id=b_member.id,
                company_id=b_company_id,
            )
        except UserError as exc:
            return bridge_error(str(exc), status=409)
        except Exception as exc:
            _logger.exception("Bridge checkin error: %s", exc)
            return bridge_error("Unexpected error.", status=500)

        status_code = 200 if data.get("already_existed") else 201
        resp = bridge_response(data, status=status_code)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
        return resp


# ──────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        _logger.warning("Bridge: invalid datetime param '%s'", value)
        return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
