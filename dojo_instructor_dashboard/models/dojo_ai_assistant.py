# -*- coding: utf-8 -*-
"""
Dojo AI Assistant — backend logic for the instructor / admin voice assistant.

Builds a dojo-specific system prompt, routes through the configured AI provider
(OpenAI or Gemini via `ai.processor`), parses optional action blocks, looks up
members / guardians, and sends parent messages.
"""

import json
import logging
import re

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ─── Action sentinel tokens (must match frontend parsing) ───────────────────
_ACTION_START = "##ACTION##"
_ACTION_END = "##END_ACTION##"

# ─── System prompt ───────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a helpful AI assistant for a dojo martial arts school, supporting instructors and administrators.
You help with:
- Looking up student (member) information such as attendance, belt rank, subscription status
- Composing messages to parents / guardians of students
- Answering questions about today's classes, schedules, and enrollments

Use ONLY the real data provided in "Database Context" below. Do not guess or invent numbers.

{db_context}

---
IMPORTANT ACTION PROTOCOL:
When the user explicitly asks to contact, send a message, or notify a parent/guardian, include a JSON
action block at the VERY END of your reply in this exact format (nothing after ##END_ACTION##):

{action_start}
{{"type": "contact_parent", "member_name": "<exact student name as listed above>", "suggested_subject": "<short email subject>", "suggested_body": "<full friendly message to the parent>"}}
{action_end}

Do NOT include this block for informational/lookup questions. Only include it when the user
wants to actually send a message to a parent.

Keep all answers concise and friendly.
"""


class DojoAiAssistant(models.AbstractModel):
    _name = "dojo.ai.assistant"
    _description = "Dojo AI Assistant"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def process_text_query(self, text):
        """
        Main entry point: process a text query through the dojo-aware AI assistant.

        Returns:
            dict: {
                "response": str,
                "action": dict | None   # contact_parent action if AI requested one
            }
        """
        text = (text or "").strip()
        if not text:
            return {"response": "Please type or say something.", "action": None}

        # Build context and system prompt
        db_context = self._build_db_context(text)
        system_prompt = _SYSTEM_PROMPT.format(
            db_context=db_context,
            action_start=_ACTION_START,
            action_end=_ACTION_END,
        )

        # Call AI provider with custom system prompt
        try:
            ai_proc = self.env["ai.processor"]
            provider = ai_proc._get_provider()

            if provider in ("openai", "odoo_native"):
                raw = ai_proc._process_openai(text, system_prompt, {})
            elif provider == "gemini":
                raw = ai_proc._process_gemini(text, system_prompt, {})
            else:
                # Fallback to process_query which handles all unknown providers
                raw = ai_proc.process_query(text, {"system_prompt": system_prompt})
        except UserError as exc:
            return {"response": str(exc), "action": None}
        except Exception as exc:
            _logger.error("Dojo AI assistant query failed: %s", exc, exc_info=True)
            return {
                "response": "Sorry, I encountered an error processing your request. Please try again.",
                "action": None,
            }

        # Parse action block
        clean_text, action = self._parse_action_block(raw or "")

        if action:
            action = self._resolve_action(action)

        return {"response": clean_text, "action": action}

    @api.model
    def send_parent_message(self, member_id, subject, body, send_email=True, send_sms=True):
        """
        Send a message to the primary guardian of member_id.
        Delegates to dojo.send.message.wizard for consistent delivery logic.
        """
        member = self.env["dojo.member"].browse(int(member_id))
        if not member.exists():
            raise UserError("Member not found.")

        wizard = self.env["dojo.send.message.wizard"].create({
            "member_ids": [(6, 0, [member.id])],
            "subject": subject or "Message from Dojo",
            "message_body": body or "",
            "send_email": bool(send_email),
            "send_sms": bool(send_sms),
        })
        wizard.action_send()
        return {
            "success": True,
            "message": "Message sent to the guardian of {}.".format(member.name),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # DB context builder
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _build_db_context(self, query_text=""):
        """Build a text block describing relevant dojo data for the AI prompt."""
        lines = []

        # ── Members matching any name-like tokens in the query ───────────────
        potential_name = self._extract_name_tokens(query_text)
        if potential_name:
            members = self._search_members(potential_name)
            if members:
                lines.append("=== Matching Students ===")
                for m in members[:6]:
                    guardian_str = self._guardian_summary(m)
                    sub = m.active_subscription_id
                    plan_str = " plan:{}".format(sub.plan_id.name) if sub and sub.plan_id else ""
                    rank_str = ""
                    if m.current_rank_id:
                        rank_str = " rank:{}".format(m.current_rank_id.name)
                    lines.append(
                        "  - {} [id:{}, role:{}, state:{}{}{}]{}".format(
                            m.name, m.id, m.role, m.membership_state,
                            plan_str, rank_str, guardian_str,
                        )
                    )

        # ── Today's sessions ─────────────────────────────────────────────────
        try:
            from datetime import date as _date
            today = _date.today().isoformat()
            sessions = self.env["dojo.class.session"].search_read(
                [
                    ["start_datetime", ">=", today + " 00:00:00"],
                    ["start_datetime", "<=", today + " 23:59:59"],
                ],
                ["template_id", "start_datetime", "seats_taken", "capacity", "state"],
                limit=10,
                order="start_datetime asc",
            )
            if sessions:
                lines.append("=== Today's Sessions ===")
                for s in sessions:
                    lines.append(
                        "  - {} at {} ({}/{} enrolled, state:{})".format(
                            s["template_id"][1] if s["template_id"] else "—",
                            s["start_datetime"][:16],
                            s["seats_taken"],
                            s["capacity"],
                            s["state"],
                        )
                    )
        except Exception as exc:
            _logger.warning("Could not fetch sessions for AI context: %s", exc)

        # ── School stats ─────────────────────────────────────────────────────
        try:
            active_count = self.env["dojo.member"].search_count(
                [["membership_state", "=", "active"]]
            )
            lines.append("=== School Stats ===")
            lines.append("  - Active members: {}".format(active_count))
        except Exception:
            pass

        return "\n".join(lines) if lines else "No specific context loaded."

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _extract_name_tokens(self, text):
        """Heuristic: extract a 1-3 word capitalised sequence from text."""
        if not text:
            return ""
        words = text.split()
        caps = [re.sub(r"[^a-zA-Z]", "", w) for w in words if w and w[0].isupper() and len(w) > 1]
        return " ".join(caps[:3])

    @api.model
    def _search_members(self, name, limit=6):
        """Case-insensitive ilike search on member name."""
        return self.env["dojo.member"].search([["name", "ilike", name]], limit=limit)

    @api.model
    def _guardian_summary(self, member):
        """Return a compact string describing the primary guardian."""
        household = member.household_id
        if household and household.primary_guardian_id:
            gp = household.primary_guardian_id.partner_id
            email_part = " email:{}".format(gp.email) if gp.email else ""
            phone_part = " phone:{}".format(gp.phone or gp.mobile or "") if (gp.phone or gp.mobile) else ""
            return " guardian:{}{}{}".format(gp.name, email_part, phone_part)
        return ""

    @api.model
    def _parse_action_block(self, text):
        """
        Extract the ##ACTION## … ##END_ACTION## block from AI response.

        Returns:
            (clean_text, action_dict | None)
        """
        start_idx = text.find(_ACTION_START)
        end_idx = text.find(_ACTION_END)
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return text.strip(), None

        json_str = text[start_idx + len(_ACTION_START): end_idx].strip()
        clean = (text[:start_idx] + text[end_idx + len(_ACTION_END):]).strip()

        try:
            action = json.loads(json_str)
            return clean, action
        except (json.JSONDecodeError, ValueError):
            _logger.warning("Could not parse AI action JSON: %s", json_str[:200])
            return clean, None

    @api.model
    def _resolve_action(self, action):
        """
        Enrich a parsed action dict with real member / guardian data looked up
        from the database.
        """
        if not action or action.get("type") != "contact_parent":
            return action

        member_name = (action.get("member_name") or "").strip()
        members = self._search_members(member_name, limit=3)

        if not members:
            action["error"] = "Could not find a student named '{}'.".format(member_name)
            return action

        member = members[0]
        household = member.household_id
        if household and household.primary_guardian_id:
            guardian_partner = household.primary_guardian_id.partner_id
        else:
            guardian_partner = member.partner_id

        action.update({
            "member_id": member.id,
            "member_name": member.name,
            "guardian_name": guardian_partner.name or "",
            "guardian_email": guardian_partner.email or "",
            "guardian_phone": guardian_partner.phone or guardian_partner.mobile or "",
        })
        return action
