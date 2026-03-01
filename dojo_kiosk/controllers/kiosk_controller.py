from odoo import http
from odoo.http import request


class KioskController(http.Controller):
    """
    Public JSON API for the Dojo Kiosk SPA.
    All mutating operations run via sudo() on the tightly-scoped
    dojo.kiosk.service AbstractModel.
    """

    # ------------------------------------------------------------------
    # SPA shell
    # ------------------------------------------------------------------

    @http.route("/kiosk", auth="public", type="http", methods=["GET"], csrf=False)
    def kiosk_index(self, config=None, **kw):
        # Validate optional per-tablet config ID
        config_id = None
        if config:
            try:
                cid = int(config)
                cfg = request.env["dojo.kiosk.config"].sudo().browse(cid)
                if cfg.exists() and cfg.active:
                    config_id = cid
            except (ValueError, TypeError):
                pass

        config_js = str(config_id) if config_id is not None else "null"
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"/>
    <meta name="robots" content="noindex,nofollow"/>
    <title>Dojo Kiosk</title>
    <link rel="stylesheet" href="/dojo_kiosk/static/src/kiosk.css"/>
</head>
<body class="dojo-kiosk-body">
    <div id="kiosk-root"></div>
    <script>window.KIOSK_CONFIG_ID = {config_js};</script>
    <script>
        window.onerror = function(msg, src, line, col, err) {{
            document.getElementById('kiosk-root').innerHTML =
                '<pre style="color:red;background:#111;padding:20px;font-size:13px;white-space:pre-wrap">'
                + 'JS ERROR:\\n' + msg + '\\n\\nSource: ' + src + ':' + line + ':' + col
                + (err ? '\\n\\nStack:\\n' + err.stack : '') + '</pre>';
        }};
    </script>
    <script src="/web/static/lib/owl/owl.js"></script>
    <script src="/dojo_kiosk/static/src/kiosk_app.js"></script>
</body>
</html>"""
        return request.make_response(
            html, headers=[("Content-Type", "text/html; charset=utf-8")]
        )

    # ------------------------------------------------------------------
    # Session data
    # ------------------------------------------------------------------

    @http.route("/kiosk/sessions", type="json", auth="public", methods=["POST"], csrf=False)
    def kiosk_sessions(self, **kw):
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_todays_sessions()

    @http.route("/kiosk/roster", type="json", auth="public", methods=["POST"], csrf=False)
    def kiosk_roster(self, session_id=None, **kw):
        if not session_id:
            return []
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_session_roster(session_id)

    # ------------------------------------------------------------------
    # Member lookup / search
    # ------------------------------------------------------------------

    @http.route("/kiosk/lookup", type="json", auth="public", methods=["POST"], csrf=False)
    def kiosk_lookup(self, barcode=None, **kw):
        if not barcode:
            return {"found": False}
        svc = request.env["dojo.kiosk.service"].sudo()
        result = svc.lookup_member_by_barcode(barcode)
        if result:
            return {"found": True, "member": result}
        return {"found": False}

    @http.route("/kiosk/search", type="json", auth="public", methods=["POST"], csrf=False)
    def kiosk_search(self, query=None, **kw):
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.search_members(query or "")

    @http.route("/kiosk/member/profile", type="json", auth="public", methods=["POST"], csrf=False)
    def kiosk_member_profile(self, member_id=None, session_id=None, **kw):
        if not member_id:
            return None
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.get_member_profile(member_id, session_id=session_id)

    # ------------------------------------------------------------------
    # Student check-in
    # ------------------------------------------------------------------

    @http.route("/kiosk/checkin", type="json", auth="public", methods=["POST"], csrf=False)
    def kiosk_checkin(self, member_id=None, session_id=None, **kw):
        if not member_id or not session_id:
            return {"success": False, "error": "member_id and session_id are required."}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.checkin_member(member_id, session_id)

    # ------------------------------------------------------------------
    # Instructor PIN
    # ------------------------------------------------------------------

    @http.route("/kiosk/auth/pin", type="json", auth="public", methods=["POST"], csrf=False)
    def kiosk_auth_pin(self, pin=None, config_id=None, **kw):
        if not pin:
            return {"success": False}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.verify_pin(pin, config_id=config_id)

    # ------------------------------------------------------------------
    # Instructor — attendance
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/attendance",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def kiosk_mark_attendance(self, session_id=None, member_id=None, status=None, **kw):
        if not all([session_id, member_id, status]):
            return {"success": False, "error": "session_id, member_id, and status are required."}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.mark_attendance(session_id, member_id, status)

    # ------------------------------------------------------------------
    # Instructor — roster management
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/roster/add",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def kiosk_roster_add(self, session_id=None, member_id=None, **kw):
        if not session_id or not member_id:
            return {"success": False, "error": "session_id and member_id are required."}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.roster_add(session_id, member_id)

    @http.route(
        "/kiosk/instructor/roster/remove",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def kiosk_roster_remove(self, session_id=None, member_id=None, **kw):
        if not session_id or not member_id:
            return {"success": False, "error": "session_id and member_id are required."}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.roster_remove(session_id, member_id)

    # ------------------------------------------------------------------
    # Instructor — session close
    # ------------------------------------------------------------------

    @http.route(
        "/kiosk/instructor/session/close",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def kiosk_session_close(self, session_id=None, **kw):
        if not session_id:
            return {"success": False, "error": "session_id is required."}
        svc = request.env["dojo.kiosk.service"].sudo()
        return svc.close_session(session_id)
