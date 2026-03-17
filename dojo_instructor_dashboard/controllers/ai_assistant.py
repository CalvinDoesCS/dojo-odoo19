# -*- coding: utf-8 -*-
"""
HTTP / JSON-RPC endpoints consumed by the Dojo AI Voice Assistant Owl component.

Routes
------
POST /dojo/ai/text          (type=json)  – text query
POST /dojo/ai/voice         (type=http)  – multipart audio upload → STT → AI
POST /dojo/ai/send_message  (type=json)  – send confirmed parent message
"""

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DojoAiAssistantController(http.Controller):

    # ── Text query ────────────────────────────────────────────────────────────

    @http.route("/dojo/ai/text", type="json", auth="user", methods=["POST"])
    def text_query(self, text="", **kwargs):
        """
        Process a plain-text query through the dojo AI assistant.

        Returns:
            {success, response, action|None}
        """
        text = (text or "").strip()
        if not text:
            return {"success": False, "error": "No text provided."}
        try:
            assistant = request.env["dojo.ai.assistant"]
            result = assistant.process_text_query(text)
            return {"success": True, **result}
        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/text failed: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    # ── Voice upload → STT → AI ───────────────────────────────────────────────

    @http.route("/dojo/ai/voice", type="http", auth="user", methods=["POST"], csrf=False)
    def voice_query(self, **kwargs):
        """
        Accept a multipart audio file, transcribe it with ElevenLabs STT, then
        process through the dojo AI assistant.

        Returns JSON: {success, transcribed, response, action|None}
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
                return _json_resp({"success": False, "error": "No audio file provided."}, 400)

            audio_bytes = audio_file.read()
            if not audio_bytes:
                return _json_resp({"success": False, "error": "Empty audio file."}, 400)

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
                    {"success": False, "error": "Speech-to-text failed. Please check the ElevenLabs API key."},
                    500,
                )

            transcribed = (transcribed or "").strip()
            if not transcribed:
                return _json_resp(
                    {"success": False, "error": "Could not understand the audio. Please try again."}
                )

            # Step 2: Process through dojo AI assistant
            result = request.env["dojo.ai.assistant"].process_text_query(transcribed)
            return _json_resp({"success": True, "transcribed": transcribed, **result})

        except Exception as exc:
            _logger.error("Dojo AI /dojo/ai/voice failed: %s", exc, exc_info=True)
            return _json_resp({"success": False, "error": str(exc)}, 500)

    # ── Send confirmed message ────────────────────────────────────────────────

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

        Returns:
            {success, message} or {success: False, error}
        """
        if not member_id:
            return {"success": False, "error": "No member specified."}
        try:
            result = request.env["dojo.ai.assistant"].send_parent_message(
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
