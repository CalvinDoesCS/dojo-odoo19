import os
import hashlib

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError


def _static_ver(*rel_paths):
    """Return a short hash of the combined mtime of the given static file paths
    (relative to the addons root). Used for cache-busting CSS/JS URLs."""
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        mtimes = "".join(
            str(int(os.path.getmtime(os.path.join(base, p))))
            for p in rel_paths
            if os.path.exists(os.path.join(base, p))
        )
        return hashlib.md5(mtimes.encode()).hexdigest()[:8]
    except Exception:
        return "1"


class KioskController(http.Controller):
    """
    Public JSON API for the Dojo Kiosk SPA.
    All routes require a valid per-tablet kiosk token (stored on dojo.kiosk.config).
    Mutating operations run via sudo() on the dojo.kiosk.service AbstractModel.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_token(self, token):
        """Validate the kiosk token and return the matching config; raises AccessError on failure."""
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.validate_token(token)

    def _guard_token(self, token, fail_return):
        """Mandatory token gate. Returns None on success; fail_return if token is
        missing or invalid.  Usage::

            guard = self._guard_token(token, {"success": False, "error": "…"})
            if guard is not None:
                return guard
        """
        if not token:
            return fail_return
        try:
            self._require_token(token)
            return None
        except AccessError:
            return fail_return

    # ------------------------------------------------------------------
    # SPA shell  --  GET /kiosk/<token>
    # ------------------------------------------------------------------

    @http.route("/kiosk/<string:token>", auth="public", type="http", methods=["GET"], csrf=False)
    def kiosk_index(self, token, **kw):
        try:
            config = request.env["dojo.kiosk.config"].sudo().search(
                [("kiosk_token", "=", token), ("active", "=", True)], limit=1
            )
            if not config:
                return request.make_response(
                    _kiosk_error_page("Invalid or inactive kiosk token."),
                    headers=[("Content-Type", "text/html; charset=utf-8")],
                )
            theme_class = "kiosk-theme-light" if config.theme_mode == "light" else "kiosk-theme-dark"
        except Exception:
            theme_class = "kiosk-theme-dark"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"/>
    <meta name="robots" content="noindex,nofollow"/>
    <title>Dojo Kiosk</title>
    <link rel="stylesheet" href="/dojo_kiosk/static/src/kiosk.css?v={_static_ver('static/src/kiosk.css')}"/>
</head>
<body class="dojo-kiosk-body {theme_class}">
    <div id="kiosk-root"></div>
    <script>
        window.KIOSK_TOKEN = {repr(token)};
        window.onerror = function(msg, src, line, col, err) {{
            document.getElementById('kiosk-root').innerHTML =
                '<pre style="color:red;background:#111;padding:20px;font-size:13px;white-space:pre-wrap">'
                + 'JS ERROR:\\n' + msg + '\\n\\nSource: ' + src + ':' + line + ':' + col
                + (err ? '\\n\\nStack:\\n' + err.stack : '') + '</pre>';
        }};
    </script>
    <script src="/web/static/lib/owl/owl.js"></script>
    <script src="/dojo_kiosk/static/src/kiosk_app.js?v={_static_ver('static/src/kiosk_app.js')}"></script>
</body>
</html>"""
        return request.make_response(
            html, headers=[("Content-Type", "text/html; charset=utf-8")]
        )

    # Legacy: /kiosk without token
    @http.route("/kiosk", auth="public", type="http", methods=["GET"], csrf=False)
    def kiosk_no_token(self, **kw):
        return request.make_response(
            _kiosk_error_page(
                "No kiosk token in URL. "
                "Open Kiosk Settings in Odoo and copy the Kiosk URL for this tablet."
            ),
            headers=[("Content-Type", "text/html; charset=utf-8")],
        )

    # ------------------------------------------------------------------
    # Bootstrap  (config + sessions in one call)
    # ------------------------------------------------------------------

    @http.route("/kiosk/api/bootstrap", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_bootstrap(self, token=None, **kw):
        if not token:
            return {"error": "token_required"}
        try:
            svc = request.env["dojo.kiosk.service"].sudo()
            return svc.get_config_bootstrap(token)
        except AccessError:
            return {"error": "invalid_token"}

    # ------------------------------------------------------------------
    # Announcements
    # ------------------------------------------------------------------

    @http.route("/kiosk/api/announcements", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_announcements(self, token=None, **kw):
        if not token:
            return []
        try:
            svc = request.env["dojo.kiosk.service"].sudo()
            return svc.get_announcements(token)
        except AccessError:
            return []

    # ------------------------------------------------------------------
    # Session data
    # ------------------------------------------------------------------

    @http.route("/kiosk/sessions", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_sessions(self, token=None, date=None, **kw):
        guard = self._guard_token(token, [])
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_todays_sessions(date=date)

    @http.route("/kiosk/roster", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_roster(self, session_id=None, token=None, **kw):
        if not session_id:
            return []
        guard = self._guard_token(token, [])
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_session_roster(session_id)

    # ------------------------------------------------------------------
    # Member lookup / search
    # ------------------------------------------------------------------

    @http.route("/kiosk/lookup", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_lookup(self, barcode=None, token=None, **kw):
        if not barcode:
            return {"found": False}
        guard = self._guard_token(token, {"found": False, "error": "invalid_token"})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        result = svc.lookup_member_by_barcode(barcode)
        return {"found": True, "member": result} if result else {"found": False}

    @http.route("/kiosk/search", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_search(self, query=None, token=None, **kw):
        guard = self._guard_token(token, [])
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.search_members(query or "")

    @http.route("/kiosk/member/profile", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_member_profile(self, member_id=None, session_id=None, token=None, **kw):
        if not member_id:
            return None
        guard = self._guard_token(token, None)
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_member_profile(member_id, session_id=session_id)

    @http.route("/kiosk/member/enrolled_sessions", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_enrolled_sessions(self, member_id=None, date=None, token=None, **kw):
        if not member_id:
            return []
        guard = self._guard_token(token, [])
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_enrolled_sessions_today(member_id, date=date)

    # ------------------------------------------------------------------
    # Check-in / Check-out
    # ------------------------------------------------------------------

    @http.route("/kiosk/checkin", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_checkin(self, member_id=None, session_id=None, token=None, **kw):
        if not member_id or not session_id:
            return {"success": False, "error": "member_id and session_id are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.checkin_member(member_id, session_id)

    @http.route("/kiosk/checkout", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_checkout(self, member_id=None, session_id=None, token=None, **kw):
        if not member_id or not session_id:
            return {"success": False, "error": "member_id and session_id are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.checkout_member(member_id, session_id)

    # ------------------------------------------------------------------
    # Instructor PIN
    # ------------------------------------------------------------------

    @http.route("/kiosk/auth/pin", type="jsonrpc", auth="public", methods=["POST"], csrf=False)
    def kiosk_auth_pin(self, pin=None, token=None, config_id=None, **kw):
        if not pin:
            return {"success": False, "error": "wrong_pin"}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.verify_pin(pin, token=token, config_id=config_id)

    # ------------------------------------------------------------------
    # Instructor -- attendance
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/attendance",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_mark_attendance(self, session_id=None, member_id=None, status=None, token=None, **kw):
        if not all([session_id, member_id, status]):
            return {"success": False, "error": "session_id, member_id, and status are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.mark_attendance(session_id, member_id, status)

    # ------------------------------------------------------------------
    # Instructor -- roster management
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/roster/add",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_roster_add(
        self, session_id=None, member_id=None,
        override_settings=False, override_capacity=False,
        token=None, **kw
    ):
        if not session_id or not member_id:
            return {"success": False, "error": "session_id and member_id are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.roster_add(
            session_id, member_id,
            override_settings=bool(override_settings),
            override_capacity=bool(override_capacity),
        )

    @http.route(
        "/kiosk/instructor/roster/bulk_add",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_roster_bulk_add(
        self, session_id=None, member_ids=None,
        override_capacity=False, override_settings=False,
        enroll_type="single", date_from=None, date_to=None,
        pref_mon=False, pref_tue=False, pref_wed=False, pref_thu=False,
        pref_fri=False, pref_sat=False, pref_sun=False,
        token=None, **kw
    ):
        if not session_id or not member_ids:
            return {"success": False, "error": "session_id and member_ids are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.bulk_roster_add(
            session_id, member_ids,
            override_capacity=override_capacity,
            override_settings=override_settings,
            enroll_type=enroll_type,
            date_from=date_from,
            date_to=date_to,
            pref_mon=bool(pref_mon),
            pref_tue=bool(pref_tue),
            pref_wed=bool(pref_wed),
            pref_thu=bool(pref_thu),
            pref_fri=bool(pref_fri),
            pref_sat=bool(pref_sat),
            pref_sun=bool(pref_sun),
        )

    @http.route(
        "/kiosk/instructor/roster/remove",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_roster_remove(self, session_id=None, member_id=None, token=None, **kw):
        if not session_id or not member_id:
            return {"success": False, "error": "session_id and member_id are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.roster_remove(session_id, member_id)

    # ------------------------------------------------------------------
    # Instructor -- session close
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/session/close",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_session_close(self, session_id=None, token=None, **kw):
        if not session_id:
            return {"success": False, "error": "session_id is required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.close_session(session_id)

    @http.route(
        "/kiosk/instructor/session/delete",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_session_delete(self, session_id=None, token=None, **kw):
        if not session_id:
            return {"success": False, "error": "session_id is required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.delete_session(session_id)

    @http.route(
        "/kiosk/instructor/session/update",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_session_update(self, session_id=None, capacity=None, token=None, **kw):
        if not session_id:
            return {"success": False, "error": "session_id is required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.update_session(session_id, capacity=capacity)

    @http.route(
        "/kiosk/instructor/templates",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_templates(self, token=None, **kw):
        """Return active class templates for use in the Create Session modal."""
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_templates()

    @http.route(
        "/kiosk/instructor/session/create",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_session_create(self, template_id=None, start_time=None, capacity=None, date=None, token=None, **kw):
        """Create a new open session for today (or a given date) from a template."""
        if not template_id or not start_time:
            return {"success": False, "error": "template_id and start_time are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.create_session_today(
            int(template_id),
            start_time,
            capacity=int(capacity) if capacity is not None else None,
            date=date,
        )

    # ------------------------------------------------------------------
    # Instructor -- belt rank management
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/belt_ranks",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_belt_ranks(self, member_id=None, program_id=None, token=None, **kw):
        if not member_id:
            return {"success": False, "error": "member_id is required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_available_belt_ranks(member_id, program_id=program_id)

    @http.route(
        "/kiosk/instructor/award_rank",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_award_rank(self, member_id=None, rank_id=None, program_id=None, notes="", token=None, **kw):
        if not member_id or not rank_id:
            return {"success": False, "error": "member_id and rank_id are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.award_belt_rank(member_id, rank_id, program_id=program_id, notes=notes)

    # ------------------------------------------------------------------
    # Instructor -- contact parent / guardian
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/send_message",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_send_message(
        self, member_id=None, subject=None, message=None,
        send_sms=True, send_email=True, guardian_member_ids=None, token=None, **kw
    ):
        if not member_id or not message:
            return {"success": False, "error": "member_id and message are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.send_parent_message(
            member_id,
            subject=subject or "Message from your Dojo",
            message=message,
            send_sms=bool(send_sms),
            send_email=bool(send_email),
            guardian_member_ids=guardian_member_ids or [],
        )

    # ------------------------------------------------------------------
    # Instructor -- next rank / available sessions / voice command
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/next_rank",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_next_rank(self, member_id=None, program_id=None, token=None, **kw):
        if not member_id:
            return {"success": False, "error": "member_id is required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_next_belt_rank(member_id, program_id=program_id)

    @http.route(
        "/kiosk/instructor/available_sessions",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_available_sessions(self, member_id=None, token=None, **kw):
        if not member_id:
            return {"success": False, "error": "member_id is required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_available_sessions(member_id)

    @http.route(
        "/kiosk/instructor/voice_command",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_voice_command(
        self, member_id=None, session_id=None, audio_data_b64=None, token=None, dry_run=False, **kw
    ):
        if not member_id or not audio_data_b64:
            return {"success": False, "error": "member_id and audio_data_b64 are required."}
        if not token:
            return {"success": False, "error": "token is required."}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.process_voice_command(token, member_id, session_id, audio_data_b64,
                                         dry_run=bool(dry_run))

    @http.route(
        "/kiosk/instructor/voice_command/execute",
        type="jsonrpc", auth="public", methods=["POST"], csrf=False,
    )
    def kiosk_voice_execute(
        self, member_id=None, session_id=None, action=None, params=None, token=None, **kw
    ):
        """Execute a previously-interpreted voice action after instructor confirmation."""
        if not member_id or not action:
            return {"success": False, "error": "member_id and action are required."}
        guard = self._guard_token(token, {"success": False, "error": "Invalid kiosk token."})
        if guard is not None:
            return guard
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.execute_voice_action(
            int(member_id), session_id, action, params or {}
        )


# ------------------------------------------------------------------
# Utils
# ------------------------------------------------------------------

def _kiosk_error_page(message):
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><title>Kiosk</title>
<style>
body{{background:#111;color:#f87171;font-family:sans-serif;
     display:flex;align-items:center;justify-content:center;
     height:100vh;margin:0;}}
.box{{text-align:center;max-width:480px;padding:40px;}}
h2{{font-size:1.4rem;margin-bottom:16px;}}
p{{font-size:0.95rem;color:#aaa;line-height:1.6;}}
</style>
</head>
<body><div class="box">
<h2>Kiosk Not Configured</h2>
<p>{message}</p>
</div></body></html>"""
