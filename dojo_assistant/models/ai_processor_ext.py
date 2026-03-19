# -*- coding: utf-8 -*-
"""
AI Processor Intent Extension — Adds structured intent parsing capabilities.

Extends the base ai.processor from elevenlabs_connector to support:
- Structured output parsing (JSON mode)
- Intent extraction with confidence scoring
- Function calling-like behavior for intents
- Fallback regex parsing when JSON mode unavailable
"""

import json
import logging
import re

import requests

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ─── Intent Parsing Tokens ────────────────────────────────────────────────────
_INTENT_START = "##INTENT##"
_INTENT_END = "##END_INTENT##"

# ─── System Prompt for Intent Parsing ─────────────────────────────────────────
_INTENT_SYSTEM_PROMPT = """\
You are an AI assistant that parses natural language commands into structured intents.

Your task is to analyze the user's input and extract:
1. The intent type (from the list of available intents)
2. Parameters for that intent
3. Your confidence level (0.0 to 1.0)

Available Intents:
{intent_definitions}

Database Context (use this to resolve entity references):
{db_context}

IMPORTANT RULES:
- Return ONLY a JSON object in your response, nothing else
- Use the exact intent_type from the available intents
- Extract parameters based on the intent's parameter schema
- Set confidence based on how certain you are about the intent (0.7+ is confident)
- If you cannot determine the intent, use intent_type "unknown" with confidence 0.0
- Resolve entity names to IDs when possible using the database context
- For member lookups, try to match names, member numbers, or partial names
- CRITICAL: For parameter VALUES, always use the ACTUAL values from the user's input, NEVER use template placeholders like {{member_name}}, {{target_belt}}, {{class_name}} etc.
  Example of CORRECT parameters: {{"member_name": "Mary Smith", "target_belt": "Blue Belt"}}
  Example of WRONG parameters: {{"member_name": "{{member_name}}", "target_belt": "{{target_belt}}"}}

Response format:
{{
  "intent_type": "<intent type>",
  "parameters": {{...}},
  "confidence": 0.0-1.0,
  "resolved_entities": {{
    "member_id": <id or null>,
    "member_name": "<resolved name>",
    "session_id": <id or null>,
    "class_name": "<resolved name>",
    ...
  }},
  "reasoning": "<brief explanation of why you chose this intent>"
}}

User input: {user_input}
"""

_CONVERSATION_SYSTEM_PROMPT = """\
You are a helpful AI assistant for a martial arts dojo. You help instructors and staff with:
- Looking up student/member information
- Managing class enrollments and attendance
- Tracking belt ranks and promotions
- Managing subscriptions and contracts
- Communicating with parents/guardians

{db_context}

Always be helpful, concise, and accurate. Use the database context to provide real information.
When you need to perform an action (not just answer a question), output a structured intent.

Valid intent_type values (use EXACTLY these strings — do not invent variants):
  member_lookup, class_list, belt_lookup, subscription_lookup, attendance_history,
  schedule_today, member_enroll, member_unenroll, belt_promote,
  subscription_create, subscription_cancel, contact_parent,
  attendance_checkin, attendance_checkout, member_create, member_update,
  class_create, class_cancel, course_enroll, belt_test_register, undo_action

CRITICAL INTENT DISAMBIGUATION — read carefully:
  • member_enroll      = reserve a spot in ONE specific class SESSION (e.g. "enroll in today's 6pm class")
  • course_enroll      = add to the PERMANENT ROSTER of a course template (e.g. "add to roster", "add to the course")
  • belt_lookup        = look up what belt rank someone currently has (e.g. "what belt is John?", "show belt ranks")
  • belt_test_register = REGISTER a member to take a belt promotion TEST (e.g. "register for a belt test", "sign up for blue belt test", "schedule a belt promotion")

KEYWORD RULES:
  - "roster", "course roster", "permanent roster", "add to the course" → ALWAYS use course_enroll
  - "today's class", "this session", "session at 6pm", "book for class today" → use member_enroll
  - "register for a belt test", "sign up for belt test", "schedule belt test", "belt test" + register/sign up → ALWAYS use belt_test_register (NOT belt_lookup)
  - "what belt is", "what rank", "belt rank" without register/test action → use belt_lookup

For actions, include at the very end of your response (ALWAYS use REAL values, NOT template placeholders like {{member_name}}):
{intent_start}
{{"intent_type": "course_enroll", "parameters": {{"member_name": "Mary Smith", "class_name": "Adult Fundamentals"}}, "confidence": 0.9}}
{intent_end}

Never put {{member_name}}, {{class_name}} etc. as parameter values. Always use the actual names from the user's message.

Only include the intent block for actions, not for informational questions.
"""


class AIProcessorIntentExt(models.AbstractModel):
    """Extends ai.processor with structured intent parsing."""

    _inherit = "ai.processor"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API: Intent Parsing
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def process_intent_query(self, text, role="instructor", db_context=None):
        """
        Parse natural language text into a structured intent.
        
        Args:
            text: User's natural language input
            role: User role for filtering available intents (kiosk/instructor/admin)
            db_context: Pre-built database context string (optional)
        
        Returns:
            dict: {
                "intent_type": str,
                "parameters": dict,
                "confidence": float,
                "resolved_entities": dict,
                "reasoning": str,
                "raw_response": str (optional, for debugging)
            }
        """
        text = (text or "").strip()
        if not text:
            return self._empty_intent("No input provided")

        # Get intent definitions for this role
        IntentSchema = self.env["dojo.ai.intent.schema"]
        intent_defs = IntentSchema.get_intent_definitions_for_llm(role)

        if not intent_defs:
            return self._empty_intent("No intents configured for this role")

        # Build database context if not provided
        if db_context is None:
            db_context = self._build_dojo_db_context(text)

        # Format intent definitions for the prompt
        intent_defs_str = self._format_intent_definitions(intent_defs)

        # Build system prompt
        system_prompt = _INTENT_SYSTEM_PROMPT.format(
            intent_definitions=intent_defs_str,
            db_context=db_context or "No specific context available.",
            user_input=text,
        )

        # Try to get structured response
        try:
            provider = self._get_provider()

            if provider in ("openai", "odoo_native"):
                raw_response = self._process_intent_openai(text, system_prompt)
            elif provider == "gemini":
                raw_response = self._process_intent_gemini(text, system_prompt)
            else:
                # Fallback to regular processing with intent block extraction
                raw_response = self.process_query(text, {"system_prompt": system_prompt})

            # Parse the structured response
            intent = self._parse_intent_response(raw_response)
            intent["raw_response"] = raw_response

            return intent

        except UserError:
            raise
        except Exception as e:
            _logger.error("Intent parsing failed: %s", e, exc_info=True)
            return self._empty_intent(f"Parsing error: {e}")

    @api.model
    def process_conversational_query(self, text, role="instructor", db_context=None):
        """
        Process a conversational query that may or may not contain an action intent.
        
        Returns both the AI response text and any extracted intent.
        
        Args:
            text: User's natural language input
            role: User role
            db_context: Pre-built database context string (optional)
        
        Returns:
            dict: {
                "response": str,
                "intent": dict | None,
                "has_intent": bool
            }
        """
        text = (text or "").strip()
        if not text:
            return {"response": "Please say or type something.", "intent": None, "has_intent": False}

        # Build database context if not provided
        if db_context is None:
            db_context = self._build_dojo_db_context(text)

        # Build system prompt for conversational mode
        system_prompt = _CONVERSATION_SYSTEM_PROMPT.format(
            db_context=db_context or "No specific context available.",
            intent_start=_INTENT_START,
            intent_end=_INTENT_END,
        )

        try:
            # Get AI response — call provider directly so our system_prompt is used,
            # bypassing the base process_query which ignores context["system_prompt"].
            provider = self._get_provider()
            if provider in ("openai", "odoo_native"):
                raw_response = self._process_conversational_openai(text, system_prompt)
            elif provider == "gemini":
                raw_response = self._process_conversational_gemini(text, system_prompt)
            else:
                raw_response = self.process_query(text, {"system_prompt": system_prompt})

            # Extract intent block if present
            response_text, intent = self._extract_intent_block(raw_response)

            return {
                "response": response_text.strip(),
                "intent": intent,
                "has_intent": intent is not None,
            }

        except UserError:
            raise
        except Exception as e:
            _logger.error("Conversational query failed: %s", e, exc_info=True)
            return {
                "response": f"Sorry, I encountered an error: {e}",
                "intent": None,
                "has_intent": False,
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Conversational (free-form text) API calls
    # ─────────────────────────────────────────────────────────────────────────

    def _process_conversational_openai(self, text, system_prompt):
        """Call OpenAI in normal (non-JSON) mode for a conversational reply."""
        api_key = self.env["ir.config_parameter"].sudo().get_param("openai.api_key") or \
                  self.env["ir.config_parameter"].sudo().get_param("elevenlabs_connector.openai_api_key")

        if not api_key:
            raise UserError("OpenAI API key not configured.")

        url = "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
            # No response_format — free-form text output
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            json_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response = requests.post(url, headers=headers, data=json_data, timeout=30)

            if response.encoding is None or response.encoding.lower() in ("iso-8859-1", "latin-1"):
                response.encoding = "utf-8"

            response.raise_for_status()
            result = json.loads(response.text)

            if "choices" in result and len(result["choices"]) > 0:
                return self._sanitize_text(result["choices"][0]["message"]["content"])
            else:
                raise UserError("Unexpected response format from OpenAI API")

        except requests.exceptions.RequestException as e:
            _logger.error("OpenAI conversational API request failed: %s", e, exc_info=True)
            raise UserError(f"OpenAI API error: {e}")

    def _process_conversational_gemini(self, text, system_prompt):
        """Call Gemini in normal (free-form text) mode for a conversational reply."""
        api_key = self.env["ir.config_parameter"].sudo().get_param("gemini.api_key") or \
                  self.env["ir.config_parameter"].sudo().get_param("elevenlabs_connector.gemini_api_key")

        if not api_key:
            raise UserError("Gemini API key not configured.")

        model = "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        full_prompt = f"{system_prompt}\n\nUser: {text}"

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000},
        }

        headers = {"Content-Type": "application/json; charset=utf-8"}

        try:
            json_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response = requests.post(url, headers=headers, data=json_data,
                                     params={"key": api_key}, timeout=30)

            if response.encoding is None or response.encoding.lower() in ("iso-8859-1", "latin-1"):
                response.encoding = "utf-8"

            response.raise_for_status()
            result = json.loads(response.text)

            if "candidates" in result and len(result["candidates"]) > 0:
                content = result["candidates"][0]["content"]["parts"][0].get("text", "")
                return self._sanitize_text(content)
            else:
                raise UserError("No response from Gemini API")

        except requests.exceptions.RequestException as e:
            _logger.error("Gemini conversational API request failed: %s", e, exc_info=True)
            raise UserError(f"Gemini API error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # OpenAI Intent Parsing (JSON Mode)
    # ─────────────────────────────────────────────────────────────────────────

    def _process_intent_openai(self, text, system_prompt):
        """Process intent using OpenAI with JSON mode for structured output."""
        api_key = self.env["ir.config_parameter"].sudo().get_param("openai.api_key") or \
                  self.env["ir.config_parameter"].sudo().get_param("elevenlabs_connector.openai_api_key")

        if not api_key:
            raise UserError("OpenAI API key not configured.")

        url = "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": "gpt-4o-mini",  # Use a model that supports JSON mode
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,  # Lower temperature for more consistent parsing
            "max_tokens": 1000,
            "response_format": {"type": "json_object"},  # JSON mode
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }

        try:
            json_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            response = requests.post(url, headers=headers, data=json_data, timeout=30)

            if response.encoding is None or response.encoding.lower() in ("iso-8859-1", "latin-1"):
                response.encoding = "utf-8"

            response.raise_for_status()
            result = json.loads(response.text)

            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                return self._sanitize_text(content)
            else:
                raise UserError("Unexpected response format from OpenAI API")

        except requests.exceptions.RequestException as e:
            _logger.error("OpenAI intent API request failed: %s", e, exc_info=True)
            raise UserError(f"OpenAI API error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Gemini Intent Parsing
    # ─────────────────────────────────────────────────────────────────────────

    def _process_intent_gemini(self, text, system_prompt):
        """Process intent using Gemini."""
        api_key = self.env["ir.config_parameter"].sudo().get_param("gemini.api_key") or \
                  self.env["ir.config_parameter"].sudo().get_param("elevenlabs_connector.gemini_api_key")

        if not api_key:
            raise UserError("Gemini API key not configured.")

        # Use a stable model
        model = "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        # Gemini doesn't have native JSON mode, so we instruct it firmly
        full_prompt = f"{system_prompt}\n\nIMPORTANT: Respond with ONLY valid JSON, no markdown or explanation."

        payload = {
            "contents": [{
                "parts": [{"text": f"{full_prompt}\n\nUser: {text}"}]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1000,
            }
        }

        headers = {"Content-Type": "application/json; charset=utf-8"}

        try:
            json_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            response = requests.post(
                url, headers=headers, data=json_data,
                params={"key": api_key}, timeout=30
            )

            if response.encoding is None or response.encoding.lower() in ("iso-8859-1", "latin-1"):
                response.encoding = "utf-8"

            response.raise_for_status()
            result = json.loads(response.text)

            if "candidates" in result and len(result["candidates"]) > 0:
                content = result["candidates"][0]["content"]["parts"][0].get("text", "")
                return self._sanitize_text(content)
            else:
                raise UserError("No response from Gemini API")

        except requests.exceptions.RequestException as e:
            _logger.error("Gemini intent API request failed: %s", e, exc_info=True)
            raise UserError(f"Gemini API error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Response Parsing
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_intent_response(self, raw_response):
        """Parse the AI response into a structured intent dict."""
        if not raw_response:
            return self._empty_intent("Empty response")

        # Try to parse as JSON directly
        try:
            # Clean up potential markdown code blocks
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            intent = json.loads(cleaned)

            # Validate required fields
            if "intent_type" not in intent:
                intent["intent_type"] = "unknown"
            if "parameters" not in intent:
                intent["parameters"] = {}
            if "confidence" not in intent:
                intent["confidence"] = 0.5
            if "resolved_entities" not in intent:
                intent["resolved_entities"] = {}
            if "reasoning" not in intent:
                intent["reasoning"] = ""

            return intent

        except json.JSONDecodeError:
            # Try to extract JSON from the response
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw_response, re.DOTALL)
            if json_match:
                try:
                    intent = json.loads(json_match.group())
                    intent.setdefault("intent_type", "unknown")
                    intent.setdefault("parameters", {})
                    intent.setdefault("confidence", 0.5)
                    intent.setdefault("resolved_entities", {})
                    intent.setdefault("reasoning", "")
                    return intent
                except json.JSONDecodeError:
                    pass

            return self._empty_intent("Could not parse response as JSON")

    def _extract_intent_block(self, raw_response):
        """
        Extract intent block from conversational response.
        
        Returns:
            tuple: (response_text, intent_dict or None)
        """
        if not raw_response:
            return "", None

        # Look for intent block markers
        start_idx = raw_response.find(_INTENT_START)
        end_idx = raw_response.find(_INTENT_END)

        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            # No intent block found
            return raw_response, None

        # Extract text before and after the intent block
        response_text = raw_response[:start_idx].strip()

        # Extract and parse the intent JSON
        intent_json = raw_response[start_idx + len(_INTENT_START):end_idx].strip()

        try:
            intent = json.loads(intent_json)
            intent.setdefault("intent_type", "unknown")
            intent.setdefault("parameters", {})
            intent.setdefault("confidence", 0.5)
            return response_text, intent
        except json.JSONDecodeError:
            _logger.warning("Could not parse intent block: %s", intent_json[:100])
            return raw_response, None

    def _empty_intent(self, reason=""):
        """Return an empty/unknown intent."""
        return {
            "intent_type": "unknown",
            "parameters": {},
            "confidence": 0.0,
            "resolved_entities": {},
            "reasoning": reason,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _format_intent_definitions(self, intent_defs):
        """Format intent definitions for the system prompt."""
        lines = []
        for intent in intent_defs:
            lines.append(f"\n## {intent['intent_type']}: {intent['name']}")
            if intent.get("description"):
                lines.append(f"   Description: {intent['description']}")
            if intent.get("parameters"):
                params = intent["parameters"]
                if isinstance(params, dict) and "properties" in params:
                    props = params["properties"]
                    required = params.get("required", [])
                    param_strs = []
                    for name, schema in props.items():
                        req = "(required)" if name in required else "(optional)"
                        desc = schema.get("description", "")
                        param_strs.append(f"      - {name} {req}: {desc}")
                    if param_strs:
                        lines.append("   Parameters:")
                        lines.extend(param_strs)
            if intent.get("examples"):
                lines.append("   Examples:")
                for ex in intent["examples"][:3]:  # Limit to 3 examples
                    lines.append(f"      - \"{ex}\"")

        return "\n".join(lines)

    def _build_dojo_db_context(self, query_text):
        """
        Build database context specific to dojo operations.
        
        Searches for members, classes, etc. based on query keywords.
        """
        context_parts = []
        query_lower = query_text.lower()

        try:
            # ── Member Search ─────────────────────────────────────────────────
            # Extract potential name tokens
            name_tokens = self._extract_name_tokens(query_text)
            if name_tokens:
                members = self._search_dojo_members(name_tokens)
                if members:
                    context_parts.append("=== Matching Members ===")
                    for m in members[:5]:
                        context_parts.append(self._format_member_context(m))

            # ── Today's Classes ───────────────────────────────────────────────
            if any(word in query_lower for word in ["class", "session", "today", "schedule", "tomorrow"]):
                sessions = self._get_upcoming_sessions()
                if sessions:
                    context_parts.append("\n=== Upcoming Class Sessions ===")
                    for s in sessions[:8]:
                        context_parts.append(self._format_session_context(s))

            # ── Belt Ranks ────────────────────────────────────────────────────
            if any(word in query_lower for word in ["belt", "rank", "promote", "promotion", "stripe"]):
                try:
                    ranks = self.env["dojo.belt.rank"].search([("active", "=", True)], order="sequence")
                    if ranks:
                        context_parts.append("\n=== Belt Ranks ===")
                        for r in ranks:
                            threshold = getattr(r, 'attendance_threshold', 0)
                            max_stripes = getattr(r, 'max_stripes', 0) or 0
                            stripe_info = f", max_stripes: {max_stripes}" if max_stripes > 0 else ""
                            context_parts.append(
                                f"- {r.name} (seq: {r.sequence}, threshold: {threshold}{stripe_info})"
                            )
                except Exception:
                    pass

            # ── Subscription Plans ────────────────────────────────────────────
            if any(word in query_lower for word in ["subscription", "plan", "contract", "membership"]):
                try:
                    plans = self.env["dojo.subscription.plan"].search([("active", "=", True)])
                    if plans:
                        context_parts.append("\n=== Subscription Plans ===")
                        for p in plans:
                            context_parts.append(f"- {p.name} (id: {p.id})")
                except Exception:
                    pass

        except Exception as e:
            _logger.warning("Error building DB context: %s", e)

        return "\n".join(context_parts) if context_parts else "No specific context available."

    def _extract_name_tokens(self, text):
        """Heuristic: extract a 1-3 word capitalised sequence from text."""
        if not text:
            return ""
        words = text.split()
        caps = [re.sub(r"[^a-zA-Z]", "", w) for w in words if w and w[0].isupper() and len(w) > 1]
        return " ".join(caps[:3])

    def _search_dojo_members(self, name_tokens, limit=5):
        """Search dojo members by name tokens."""
        try:
            return self.env["dojo.member"].search([("name", "ilike", name_tokens)], limit=limit)
        except Exception:
            return []

    def _format_member_context(self, member):
        """Format member info for context."""
        parts = [f"- {member.name} (id: {member.id}"]
        if hasattr(member, 'partner_id') and member.partner_id:
            flags = []
            if member.partner_id.is_student:
                flags.append("student")
            if member.partner_id.is_guardian:
                flags.append("guardian")
            if member.partner_id.is_minor:
                flags.append("minor")
            if flags:
                parts.append(f", flags: {'/'.join(flags)}")
        if hasattr(member, 'membership_state'):
            parts.append(f", state: {member.membership_state}")
        if hasattr(member, 'current_rank_id') and member.current_rank_id:
            rank = member.current_rank_id
            stripe_count = getattr(member, 'current_stripe_count', 0) or 0
            max_stripes = getattr(rank, 'max_stripes', 0) or 0
            rank_str = rank.name
            if max_stripes > 0:
                rank_str += f" ({stripe_count}/{max_stripes} stripes)"
            parts.append(f", rank: {rank_str}")
        parts.append(")")
        return "".join(parts)

    def _get_upcoming_sessions(self, limit=8):
        """Get upcoming class sessions."""
        try:
            from datetime import date as _date
            today = _date.today().isoformat()
            return self.env["dojo.class.session"].search([
                ("start_datetime", ">=", today + " 00:00:00"),
                ("start_datetime", "<=", today + " 23:59:59"),
            ], order="start_datetime asc", limit=limit)
        except Exception:
            return []

    def _format_session_context(self, session):
        """Format session info for context."""
        name = session.template_id.name if session.template_id else f"Session #{session.id}"
        time_str = session.start_datetime.strftime("%H:%M") if session.start_datetime else "?"
        return f"- {name} at {time_str} (id: {session.id}, enrolled: {session.seats_taken}/{session.capacity})"
