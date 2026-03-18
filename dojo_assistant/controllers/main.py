# -*- coding: utf-8 -*-
"""
HTTP / JSON-RPC endpoints for the Dojo AI Assistant.

This controller provides a reusable API that can be consumed by:
- Instructor Dashboard voice assistant component
- Kiosk application
- Other frontend applications

Routes
------
POST /dojo/ai/text          (type=json)  – text query → parse + auto-execute or confirmation
POST /dojo/ai/voice         (type=http)  – multipart audio upload → STT → parse + confirm
POST /dojo/ai/confirm       (type=json)  – confirm or reject pending action
POST /dojo/ai/undo          (type=json)  – undo last undoable action
POST /dojo/ai/send_message  (type=json)  – send confirmed parent message (legacy)
GET  /dojo/ai/history       (type=json)  – get recent AI action history
GET  /dojo/ai/intents       (type=json)  – get available intent schemas
"""

import json
import logging
import base64

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DojoAiAssistantController(http.Controller):

    # ═══════════════════════════════════════════════════════════════════════════
    # New Two-Phase Confirmation API
    # ═══════════════════════════════════════════════════════════════════════════

    @http.route("/dojo/ai/text", type="json", auth="user", methods=["POST"])
    def text_query(self, text="", role=None, **kwargs):
        """
        Process a plain-text query through the dojo AI assistant.
        
        Uses the new two-phase confirmation flow:
        - Read-only queries auto-execute and return results
        - Mutating queries return a confirmation prompt and session_key
        
        Args:
            text: Natural language query
            role: Optional role override (kiosk/instructor/admin)
        
        Returns:
            {
                success: bool,
                state: "pending_confirmation" | "executed" | "error",
                session_key: str (for confirmation),
                intent: dict | None,
                confirmation_prompt: str | None,
                resolved_data: dict | None,
                auto_executed: bool,
                result: dict | None,
                response: str | None,
                error: str | None
            }
        """
        text = (text or "").strip()
        if not text:
            return {"success": False, "state": "error", "error": "No text provided."}

        # Determine role from user groups if not specified
        if not role:
            role = self._get_user_role()

        try:
            assistant = request.env["ai.assistant.service"]
            result = assistant.handle_command(text, role=role, input_type="text")
            return result
        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/text failed: %s", exc, exc_info=True)
            return {"success": False, "state": "error", "error": str(exc)}

    @http.route("/dojo/ai/confirm", type="json", auth="user", methods=["POST"])
    def confirm_action(self, session_key="", confirmed=True, **kwargs):
        """
        Confirm or reject a pending action from parse_and_confirm.
        
        Args:
            session_key: Session key from the parse_and_confirm response
            confirmed: True to execute, False to reject
        
        Returns:
            {
                success: bool,
                state: "executed" | "rejected" | "error",
                result: dict | None,
                undo_available: bool,
                undo_expires_in_minutes: int | None,
                error: str | None
            }
        """
        if not session_key:
            return {"success": False, "state": "error", "error": "No session_key provided."}

        try:
            assistant = request.env["ai.assistant.service"]
            result = assistant.execute_confirmed(session_key, confirmed=bool(confirmed))
            return result
        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/confirm failed: %s", exc, exc_info=True)
            return {"success": False, "state": "error", "error": str(exc)}

    @http.route("/dojo/ai/undo", type="json", auth="user", methods=["POST"])
    def undo_action(self, **kwargs):
        """
        Initiate undo of the most recent undoable action.
        
        Returns a confirmation prompt for the undo operation.
        Use /dojo/ai/confirm to execute or cancel the undo.
        
        Returns:
            {
                success: bool,
                state: "pending_confirmation" | "error",
                session_key: str | None,
                confirmation_prompt: str | None,
                undo_target: dict | None,
                error: str | None
            }
        """
        try:
            assistant = request.env["ai.assistant.service"]
            result = assistant.undo_last_action(user_id=request.env.user.id)
            return result
        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/undo failed: %s", exc, exc_info=True)
            return {"success": False, "state": "error", "error": str(exc)}

    # ═══════════════════════════════════════════════════════════════════════════
    # Voice Input (STT → Text → AI)
    # ═══════════════════════════════════════════════════════════════════════════

    @http.route("/dojo/ai/voice", type="http", auth="user", methods=["POST"], csrf=False)
    def voice_query(self, role=None, **kwargs):
        """
        Accept a multipart audio file, transcribe it with ElevenLabs STT, then
        process through the dojo AI assistant with confirmation flow.

        Returns JSON: {
            success: bool,
            transcribed: str,
            state: str,
            session_key: str | None,
            intent: dict | None,
            confirmation_prompt: str | None,
            resolved_data: dict | None,
            auto_executed: bool,
            result: dict | None,
            response: str | None,
            error: str | None
        }
        """
        def _json_resp(data, status=200):
            return request.make_response(
                json.dumps(data, ensure_ascii=False).encode("utf-8"),
                headers=[("Content-Type", "application/json; charset=utf-8")],
                status=status,
            )

        try:
            audio_file = request.httprequest.files.get("audio")
            if not audio_file:
                return _json_resp({"success": False, "state": "error", "error": "No audio file provided."}, 400)

            audio_bytes = audio_file.read()
            if not audio_bytes:
                return _json_resp({"success": False, "state": "error", "error": "Empty audio file."}, 400)

            # Store audio as attachment for audit trail
            attachment = None
            try:
                attachment = request.env["ir.attachment"].sudo().create({
                    "name": f"voice_input_{audio_file.filename or 'audio.webm'}",
                    "datas": base64.b64encode(audio_bytes),
                    "mimetype": audio_file.content_type or "audio/webm",
                    "res_model": "dojo.ai.action.log",
                })
            except Exception as e:
                _logger.warning("Could not save audio attachment: %s", e)

            # Step 1: Speech-to-text via ElevenLabs
            lang = request.env["ir.config_parameter"].sudo().get_param(
                "elevenlabs_connector.language", "en"
            )
            try:
                transcribed = request.env["elevenlabs.service"].transcribe_audio(
                    audio_bytes, language=lang
                )
            except Exception as exc:
                _logger.error("Dojo AI STT failed: %s", exc)
                return _json_resp(
                    {"success": False, "state": "error", "error": "Speech-to-text failed. Please check the ElevenLabs API key."},
                    500,
                )

            transcribed = (transcribed or "").strip()
            if not transcribed:
                return _json_resp(
                    {"success": False, "state": "error", "error": "Could not understand the audio. Please try again."}
                )

            # Determine role
            if not role:
                role = self._get_user_role()

            # Step 2: Process through dojo AI assistant with confirmation flow
            assistant = request.env["ai.assistant.service"]
            result = assistant.handle_command(
                transcribed,
                role=role,
                input_type="voice",
                audio_attachment_id=attachment.id if attachment else None,
            )

            result["transcribed"] = transcribed
            return _json_resp(result)

        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/voice failed: %s", exc, exc_info=True)
            return _json_resp({"success": False, "state": "error", "error": str(exc)}, 500)

    # ═══════════════════════════════════════════════════════════════════════════
    # Admin / Monitoring Endpoints
    # ═══════════════════════════════════════════════════════════════════════════

    @http.route("/dojo/ai/history", type="json", auth="user", methods=["GET", "POST"])
    def get_history(self, limit=20, offset=0, user_only=True, **kwargs):
        """
        Get recent AI action history.
        
        Args:
            limit: Maximum records to return (default 20, max 100)
            offset: Pagination offset
            user_only: If True, show only current user's actions
        
        Returns:
            {
                success: bool,
                records: list[dict],
                total: int,
                error: str | None
            }
        """
        try:
            ActionLog = request.env["dojo.ai.action.log"]

            domain = []
            if user_only:
                domain.append(("user_id", "=", request.env.user.id))

            limit = min(int(limit or 20), 100)
            offset = int(offset or 0)

            total = ActionLog.search_count(domain)
            logs = ActionLog.search(
                domain,
                order="timestamp desc",
                limit=limit,
                offset=offset,
            )

            records = []
            for log in logs:
                records.append({
                    "id": log.id,
                    "session_key": log.session_key,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "input_text": log.input_text,
                    "intent_type": log.intent_type,
                    "confidence": log.confidence,
                    "confirmation_status": log.confirmation_status,
                    "execution_status": log.execution_status,
                    "is_undoable": log.is_undoable,
                    "undone": log.undone,
                })

            return {"success": True, "records": records, "total": total, "error": None}

        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/history failed: %s", exc, exc_info=True)
            return {"success": False, "records": [], "total": 0, "error": str(exc)}

    @http.route("/dojo/ai/intents", type="json", auth="user", methods=["GET", "POST"])
    def get_intents(self, role=None, **kwargs):
        """
        Get available intent schemas for the current user's role.
        
        Args:
            role: Optional role override
        
        Returns:
            {
                success: bool,
                intents: list[dict],
                error: str | None
            }
        """
        try:
            if not role:
                role = self._get_user_role()

            Schema = request.env["dojo.ai.intent.schema"]
            schemas = Schema.search([("active", "=", True)])

            intents = []
            for schema in schemas:
                if schema.check_role_permission(role):
                    intents.append({
                        "intent_type": schema.intent_type,
                        "name": schema.name,
                        "description": schema.description,
                        "category": schema.category,
                        "requires_confirmation": schema.requires_confirmation,
                        "is_undoable": schema.is_undoable,
                        "supports_bulk": schema.supports_bulk,
                    })

            return {"success": True, "intents": intents, "role": role, "error": None}

        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/intents failed: %s", exc, exc_info=True)
            return {"success": False, "intents": [], "error": str(exc)}

    # ═══════════════════════════════════════════════════════════════════════════
    # Legacy Endpoints (Backward Compatibility)
    # ═══════════════════════════════════════════════════════════════════════════

    @http.route("/dojo/ai/send_message", type="json", auth="user", methods=["POST"])
    def send_message(
        self,
        member_id=None,
        subject="",
        body="",
        send_email=True,
        send_sms=True,
        **kwargs,
    ):
        """
        Execute the confirmed send-to-parent action.
        
        DEPRECATED: Use the new confirmation flow with /confirm endpoint.

        Returns:
            {success, message} or {success: False, error}
        """
        if not member_id:
            return {"success": False, "error": "No member specified."}
        try:
            result = request.env["ai.assistant.service"].send_parent_message(
                int(member_id),
                subject=subject,
                body=body,
                send_email=bool(send_email),
                send_sms=bool(send_sms),
            )
            return result
        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/send_message failed: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    # ═══════════════════════════════════════════════════════════════════════════
    # Helper Methods
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_user_role(self):
        """Determine the current user's role from group membership."""
        user = request.env.user

        # Check for admin role
        if user.has_group("dojo_base.group_dojo_admin"):
            return "admin"

        # Check for instructor role
        if user.has_group("dojo_base.group_dojo_instructor"):
            return "instructor"

        # Default to kiosk (limited permissions)
        return "kiosk"
