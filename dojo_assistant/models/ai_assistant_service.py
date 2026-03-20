# -*- coding: utf-8 -*-
#test update
"""
AI Assistant Service — Central service for handling AI assistant commands.

This is a reusable service model that can be used by:
- Instructor Dashboard
- Kiosk module
- Other applications needing AI assistant capabilities

Provides:
- Two-phase confirmation flow (parse → confirm → execute)
- Structured intent parsing via ai.processor extension
- Intent handlers for CRUD operations
- Audit logging of all actions
- Undo capability for reversible actions
- Bulk operation support
"""

import json
import logging
import re
import time

from odoo import api, fields, models
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)

# ─── Action sentinel tokens (legacy, for backward compatibility) ─────────────
_ACTION_START = "##ACTION##"
_ACTION_END = "##END_ACTION##"

# ─── Confidence threshold ────────────────────────────────────────────────────
_MIN_CONFIDENCE = 0.7

# ─── Read-only intents that auto-execute without confirmation ────────────────
_AUTO_EXECUTE_INTENTS = {
    "member_lookup",
    "class_list",
    "belt_lookup",
    "subscription_lookup",
    "attendance_history",
    "schedule_today",
    "at_risk_members",
    "campaign_lookup",
    "marketing_card_lookup",
    "unknown",
}

# ─── All recognised intent types (must match handler keys in _execute_intent) ─
_KNOWN_INTENT_TYPES = {
    "member_lookup", "class_list", "belt_lookup", "subscription_lookup",
    "attendance_history", "schedule_today",
    "member_enroll", "member_unenroll", "belt_promote",
    "subscription_create", "subscription_cancel", "contact_parent",
    "attendance_checkin", "attendance_checkout",
    "member_create", "member_update",
    "class_create", "class_cancel",
    "course_enroll", "belt_test_register",
    "undo_action", "unknown",
    # Extended intents
    "subscription_pause", "subscription_resume",
    "at_risk_members", "campaign_lookup", "marketing_card_lookup",
    "campaign_create", "campaign_activate",
    "social_post_create", "social_post_schedule",
}

# ─── Intent Handler Configuration (for generic read handler) ──────────────────
# Maps intent_type → handler config for read-only operations
# Structure: {
#     "model": "model_name",
#     "domain_builder": "method_name" | static domain list,
#     "fields": [list of field names to return],
#     "limit": max records,
#     "limit_from_params": "parameter_name" (optional, if limit comes from intent params)
# }
_INTENT_HANDLER_CONFIG = {
    "member_lookup": {
        "model": "dojo.member",
        "domain_builder": "_domain_member_lookup",
        "fields": ["id", "name", "email", "phone", "current_rank_id", "membership_state"],
        "limit": 5,
    },
    "class_list": {
        "model": "dojo.class.session",
        "domain_builder": "_domain_class_list",
        "fields": ["id", "template_id", "start_datetime", "capacity", "state", "seats_taken"],
        "limit": 20,
    },
    "belt_lookup": {
        "model": "dojo.belt.rank",
        "domain": [("active", "=", True)],
        "fields": ["id", "name", "sequence"],
        "limit": 15,
    },
    "subscription_lookup": {
        "model": "dojo.subscription",
        "domain_builder": "_domain_subscription_lookup",
        "fields": ["id", "member_id", "plan_id", "state", "start_date", "end_date"],
        "limit": 1,
    },
    "attendance_history": {
        "model": "dojo.attendance.log",
        "domain_builder": "_domain_attendance_history",
        "fields": ["id", "member_id", "checkin_datetime", "checkout_datetime", "session_id"],
        "limit": 10,
        "limit_from_params": "limit",
    },
    "schedule_today": {
        "model": "dojo.class.session",
        "domain_builder": "_domain_schedule_today",
        "fields": ["id", "template_id", "start_datetime", "capacity", "state", "seats_taken"],
        "limit": 20,
    },
}

# ─── CRUD Handler Configuration (for generic create/update/delete) ──────────────
# Maps intent_type → CRUD config for mutating operations
# Structure: {
#     "model": "model_name",
#     "operation": "create" | "update" | "delete",
#     "fields": {
#         "field_name": {
#             "type": "char|many2one|datetime|...",
#             "required": True|False,
#             "resolver": "method_name" | None (for field lookups),
#         }
#     },
#     "target_domain_builder": "_domain_method" (for update/delete targeting),
#     "allow_undo": True|False,
# }
_CRUD_HANDLER_CONFIG = {
    "member_create": {
        "model": "dojo.member",
        "operation": "create",
        "fields": {
            "name": {"required": True, "type": "char"},
            "email": {"required": False, "type": "char"},
            "phone": {"required": False, "type": "char"},
            "role": {"required": False, "type": "selection", "default": "student"},
            "membership_state": {"required": False, "type": "selection", "default": "pending"},
        },
        "allow_undo": True,
    },
    "member_update": {
        "model": "dojo.member",
        "operation": "update",
        "target_domain_builder": "_domain_crud_member",
        "fields": {
            "name": {"required": False, "type": "char"},
            "email": {"required": False, "type": "char"},
            "phone": {"required": False, "type": "char"},
            "role": {"required": False, "type": "selection"},
        },
        "allow_undo": True,
    },
    "class_create": {
        "model": "dojo.class.session",
        "operation": "create",
        "fields": {
            "template_id": {"required": True, "type": "many2one", "resolver": "_resolve_class_template"},
            "start_datetime": {"required": True, "type": "datetime"},
            "state": {"required": False, "type": "selection", "default": "scheduled"},
        },
        "allow_undo": True,
    },
    "class_cancel": {
        "model": "dojo.class.session",
        "operation": "delete",
        "target_domain_builder": "_domain_crud_session",
        "allow_undo": True,
    },
    "subscription_create": {
        "model": "dojo.subscription",
        "operation": "create",
        "fields": {
            "member_id": {"required": True, "type": "many2one", "resolver": "_resolve_member"},
            "plan_id": {"required": True, "type": "many2one", "resolver": "_resolve_subscription_plan"},
            "start_date": {"required": False, "type": "date", "default_builder": "_default_today"},
            "state": {"required": False, "type": "selection", "default": "active"},
        },
        "allow_undo": True,
    },
    "subscription_cancel": {
        "model": "dojo.subscription",
        "operation": "delete",
        "target_domain_builder": "_domain_crud_subscription",
        "allow_undo": True,
    },
    "program_create": {
        "model": "dojo.program",
        "operation": "create",
        "fields": {
            "name": {"required": True, "type": "char"},
            "description": {"required": False, "type": "text"},
            "active": {"required": False, "type": "boolean", "default": True},
        },
        "allow_undo": True,
    },
    "belt_test_register_crud": {
        "model": "dojo.member.rank",
        "operation": "create",
        "fields": {
            "member_id": {"required": True, "type": "many2one", "resolver": "_resolve_member"},
            "test_rank_id": {"required": True, "type": "many2one"},
            "test_date": {"required": False, "type": "date", "default_builder": "_default_today"},
            "state": {"required": False, "type": "selection", "default": "registered"},
        },
        "allow_undo": True,
    },
    "class_template_create": {
        "model": "dojo.class.template",
        "operation": "create",
        "fields": {
            "name": {"required": True, "type": "char"},
            "program_id": {"required": True, "type": "many2one", "resolver": "_resolve_program"},
            "capacity": {"required": False, "type": "integer", "default": 20},
            "active": {"required": False, "type": "boolean", "default": True},
        },
        "allow_undo": True,
    },
    "class_enrollment_create": {
        "model": "dojo.class.enrollment",
        "operation": "create",
        "fields": {
            "member_id": {"required": True, "type": "many2one", "resolver": "_resolve_member"},
            "session_id": {"required": True, "type": "many2one"},
            "state": {"required": False, "type": "selection", "default": "confirmed"},
        },
        "allow_undo": True,
    },
    "class_enrollment_cancel": {
        "model": "dojo.class.enrollment",
        "operation": "delete",
        "target_domain_builder": "_domain_crud_enrollment",
        "allow_undo": True,
    },
    # ─── NEW: Extended Model CRUD Operations ───────────────────────────────
    "belt_test_create": {
        "model": "dojo.belt.test",
        "operation": "create",
        "fields": {
            "name": {"required": True, "type": "char"},
            "test_rank_id": {"required": True, "type": "many2one"},
            "test_date": {"required": False, "type": "date", "default_builder": "_default_today"},
            "location": {"required": False, "type": "char"},
        },
        "allow_undo": True,
    },
    "attendance_log_create": {
        "model": "dojo.attendance.log",
        "operation": "create",
        "fields": {
            "member_id": {"required": True, "type": "many2one", "resolver": "_resolve_member"},
            "session_id": {"required": False, "type": "many2one"},
            "checkin_datetime": {"required": True, "type": "datetime"},
            "checkout_datetime": {"required": False, "type": "datetime"},
        },
        "allow_undo": True,
    },
    "credit_transaction_create": {
        "model": "dojo.credit.transaction",
        "operation": "create",
        "fields": {
            "member_id": {"required": True, "type": "many2one", "resolver": "_resolve_member"},
            "amount": {"required": True, "type": "float"},
            "transaction_type": {"required": True, "type": "selection"},
            "description": {"required": False, "type": "text"},
        },
        "allow_undo": True,
    },
    "marketing_campaign_create": {
        "model": "dojo.marketing.campaign",
        "operation": "create",
        "fields": {
            "name": {"required": True, "type": "char"},
            "campaign_type": {"required": True, "type": "selection"},
            "target_audience": {"required": False, "type": "char"},
            "send_date": {"required": False, "type": "date"},
        },
        "allow_undo": True,
    },
    "social_post_create": {
        "model": "dojo.social.post",
        "operation": "create",
        "fields": {
            "content": {"required": True, "type": "text"},
            "account_id": {"required": True, "type": "many2one"},
            "post_date": {"required": False, "type": "datetime"},
            "published": {"required": False, "type": "boolean", "default": False},
        },
        "allow_undo": True,
    },
    "instructor_profile_update": {
        "model": "dojo.instructor.profile",
        "operation": "update",
        "fields": {
            "user_id": {"required": False, "type": "many2one"},
            "speciality": {"required": False, "type": "char"},
            "bio": {"required": False, "type": "text"},
            "years_experience": {"required": False, "type": "integer"},
        },
        "allow_undo": True,
    },
    "emergency_contact_create": {
        "model": "dojo.emergency.contact",
        "operation": "create",
        "fields": {
            "member_id": {"required": True, "type": "many2one", "resolver": "_resolve_member"},
            "contact_name": {"required": True, "type": "char"},
            "phone": {"required": True, "type": "char"},
            "relationship": {"required": False, "type": "char"},
        },
        "allow_undo": True,
    },
}


class AiAssistantService(models.AbstractModel):
    """
    Central AI Assistant Service.
    
    This abstract model provides the core AI assistant functionality
    that can be used by multiple modules (instructor dashboard, kiosk, etc.)
    """
    _name = "ai.assistant.service"
    _description = "AI Assistant Service"

    # ═══════════════════════════════════════════════════════════════════════════
    # Main API: Two-Phase Confirmation Flow
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def handle_command(self, text, role="instructor", input_type="text", audio_attachment_id=None, context=None):
        """
        Main entry point for the AI assistant.
        
        This is the primary method that should be called by consuming modules.
        Aliases: parse_and_confirm (for backward compatibility)
        
        Args:
            text: User's natural language input
            role: User role (kiosk/instructor/admin)
            input_type: 'text' or 'voice'
            audio_attachment_id: ID of stored audio attachment (for voice)
            context: Optional dict of additional context data
        
        Returns:
            dict: {
                "success": bool,
                "state": "pending_confirmation" | "executed" | "error",
                "session_key": str (for confirmation flow),
                "intent": dict | None,
                "confirmation_prompt": str | None,
                "resolved_data": dict | None,
                "auto_executed": bool,
                "result": dict | None (if auto-executed),
                "response": str | None (AI conversational response),
                "error": str | None
            }
        """
        return self.parse_and_confirm(text, role, input_type, audio_attachment_id)

    @api.model
    def parse_and_confirm(self, text, role="instructor", input_type="text", audio_attachment_id=None):
        """
        Phase 1: Parse natural language input into a structured intent.
        
        For read-only intents, auto-executes and returns result.
        For mutating intents, returns confirmation prompt.
        
        Args:
            text: User's natural language input
            role: User role (kiosk/instructor/admin)
            input_type: 'text' or 'voice'
            audio_attachment_id: ID of stored audio attachment (for voice)
        
        Returns:
            dict: Standard response format (see handle_command)
        """
        text = (text or "").strip()
        if not text:
            return self._error_response("Please type or say something.")

        start_time = time.time()

        try:
            # Get conversational response with potential intent
            ai_proc = self.env["ai.processor"]
            result = ai_proc.process_conversational_query(text, role, self._build_db_context(text))

            response_text = result.get("response", "")
            intent_data = result.get("intent")

            # Determine the raw intent type from the conversational query
            conv_intent_type = intent_data.get("intent_type", "unknown") if intent_data else "unknown"

            # Fall back to structured intent parsing if:
            #  - no intent was detected at all
            #  - conversational intent is "unknown"
            #  - conversational intent is not a recognised handler key
            #    (the AI sometimes invents variants like "member_enrollment")
            if not intent_data or conv_intent_type not in _KNOWN_INTENT_TYPES or conv_intent_type == "unknown":
                db_ctx = self._build_db_context(text)
                intent_result = ai_proc.process_intent_query(text, role, db_ctx)
                if intent_result.get("confidence", 0) >= _MIN_CONFIDENCE:
                    intent_data = intent_result
                    _logger.info(
                        "AI: using structured intent %s (conv was '%s')",
                        intent_result.get("intent_type"), conv_intent_type,
                    )

            # Determine intent type and check permissions
            intent_type = intent_data.get("intent_type", "unknown") if intent_data else "unknown"
            # Final safety net: if the AI still returned an unrecognised type, reset to unknown
            if intent_type not in _KNOWN_INTENT_TYPES:
                _logger.warning("AI returned unrecognised intent_type '%s', treating as unknown", intent_type)
                intent_type = "unknown"

            # Keyword-based override for common AI confusion patterns
            text_lower = text.lower()
            if intent_type == "member_enroll" and any(
                kw in text_lower for kw in ("roster", "course roster", "permanent roster", "add to the course", "add to course")
            ):
                _logger.info("Keyword override: member_enroll → course_enroll (user said 'roster')")
                intent_type = "course_enroll"
                if intent_data:
                    intent_data["intent_type"] = "course_enroll"

            # belt_lookup → belt_test_register when the user is asking to register/schedule a test
            if intent_type in ("belt_lookup", "unknown") and "belt test" in text_lower and any(
                kw in text_lower for kw in ("register", "sign up", "schedule", "add", "book", "testing for")
            ):
                _logger.info("Keyword override: %s → belt_test_register (user said 'belt test' + action verb)", intent_type)
                intent_type = "belt_test_register"
                # Ensure intent_data has the right type and try to extract belt name
                if intent_data is None:
                    intent_data = {"intent_type": "belt_test_register", "parameters": {}, "confidence": 0.8}
                else:
                    intent_data["intent_type"] = "belt_test_register"

            # For belt_test_register, recover any dropped params (AI sometimes uses placeholder strings)
            if intent_type == "belt_test_register":
                if intent_data is None:
                    intent_data = {"intent_type": "belt_test_register", "parameters": {}, "confidence": 0.8}
                params = intent_data.setdefault("parameters", {})
                # Recover belt name from user text if missing or was a placeholder
                if not params.get("target_belt") and not params.get("belt_name") and not params.get("new_belt"):
                    import re as _re2
                    belt_match = _re2.search(
                        r'\b(white|yellow|orange|green|blue|purple|brown|red|black|stripe)\s+(?:stripe\s+)?belt\b',
                        text_lower
                    )
                    if belt_match:
                        params["target_belt"] = belt_match.group(0).title()
                        _logger.info("Recovered target_belt from user text: %s", params["target_belt"])
                # Recover member name from user text if missing
                if not params.get("member_name") and not params.get("member_id"):
                    members = self.env["dojo.member"].search([], limit=200, order="name asc")
                    for m in members:
                        if m.name.lower() in text_lower:
                            params["member_name"] = m.name
                            _logger.info("Recovered member_name from user text: %s", m.name)
                            break

            # For belt_promote, recover belt name if AI returned a placeholder
            if intent_type == "belt_promote" and intent_data is not None:
                params = intent_data.setdefault("parameters", {})
                _BELT_PLACEHOLDERS = {"new_belt", "belt", "next_belt", "target_belt", "blue_belt", ""}
                current = (params.get("new_belt") or params.get("target_belt") or "").lower().strip()
                if not current or current in _BELT_PLACEHOLDERS:
                    import re as _re3
                    belt_match = _re3.search(
                        r'\b(white|yellow|orange|green|blue|purple|brown|red|black|stripe)\s+(?:stripe\s+)?belt\b',
                        text_lower
                    )
                    if belt_match:
                        params["new_belt"] = belt_match.group(0).title()
                        _logger.info("Recovered new_belt from user text: %s", params["new_belt"])

            # For contact_parent, ensure subject has a readable default for confirmation
            if intent_type == "contact_parent" and intent_data is not None:
                params = intent_data.setdefault("parameters", {})
                if not params.get("subject"):
                    # Build a default subject from the body or user text
                    body = params.get("body", params.get("message", ""))
                    if body:
                        # Use first ~50 chars of body as subject
                        default_subj = body[:50].rstrip().rstrip(".,!?") + ("..." if len(body) > 50 else "")
                    else:
                        default_subj = "Message from Dojo"
                    params["subject"] = default_subj

            # Validate role permission
            if intent_type != "unknown":
                schema = self.env["dojo.ai.intent.schema"].get_by_type(intent_type)
                if schema and not schema.check_role_permission(role):
                    return self._error_response(f"You don't have permission to execute '{intent_type}'.")

            # General member name recovery — runs for all member-related intents
            # (belt_test_register has its own recovery above; this covers everything else)
            _MEMBER_INTENTS = {
                "member_lookup", "attendance_history", "subscription_lookup", "belt_lookup",
                "attendance_checkin", "attendance_checkout", "member_enroll", "member_unenroll",
                "course_enroll", "belt_promote", "subscription_cancel", "contact_parent",
                "member_update", "subscription_pause", "subscription_resume",
            }
            if intent_type in _MEMBER_INTENTS and intent_data is not None:
                params = intent_data.setdefault("parameters", {})
                if not params.get("member_name") and not params.get("member_id"):
                    members = self.env["dojo.member"].search([], limit=200, order="name asc")
                    for m in members:
                        if m.name.lower() in text_lower:
                            params["member_name"] = m.name
                            _logger.info("General recovery: member_name=%s for %s", m.name, intent_type)
                            break

            # Resolve entities (member IDs, session IDs, etc.)
            resolved_data = self._resolve_entities(intent_data) if intent_data else {}

            # Check if this intent requires confirmation
            requires_confirmation = self._requires_confirmation(intent_type)

            # Create action log entry
            ActionLog = self.env["dojo.ai.action.log"]
            log = ActionLog.log_parse(
                input_text=text,
                role=role,
                intent_type=intent_type,
                parsed_intent=intent_data,
                confidence=round((intent_data.get("confidence", 0) if intent_data else 0) * 100, 1),
                resolved_data=resolved_data,
                confirmation_prompt=None,  # Set below if needed
                requires_confirmation=requires_confirmation,
                input_type=input_type,
                audio_attachment_id=audio_attachment_id,
            )

            # If read-only intent, auto-execute
            if not requires_confirmation:
                exec_result = self._execute_intent(intent_type, intent_data, resolved_data, log)
                execution_time_ms = int((time.time() - start_time) * 1000)

                log.log_execution(
                    success=exec_result.get("success", False),
                    result=exec_result,
                    execution_time_ms=execution_time_ms,
                    is_undoable=False,
                )

                # Use formatted execution result as the response so the user
                # sees actual data rather than the AI's conversational fallback.
                formatted = self._format_exec_result_as_response(intent_type, exec_result)
                final_response = formatted or response_text

                return {
                    "success": True,
                    "state": "executed",
                    "session_key": log.session_key,
                    "intent": intent_data,
                    "auto_executed": True,
                    "result": exec_result,
                    "response": final_response,
                    "confirmation_prompt": None,
                    "resolved_data": resolved_data,
                    "error": None,
                }

            # Build confirmation prompt
            confirmation_prompt = self._build_confirmation_prompt(intent_type, intent_data, resolved_data)
            log.write({"confirmation_prompt": confirmation_prompt})

            return {
                "success": True,
                "state": "pending_confirmation",
                "session_key": log.session_key,
                "intent": intent_data,
                "confirmation_prompt": confirmation_prompt,
                "resolved_data": resolved_data,
                "auto_executed": False,
                "result": None,
                "response": response_text,
                "error": None,
            }

        except UserError as e:
            return self._error_response(str(e))
        except Exception as e:
            _logger.error("AI assistant parse failed: %s", e, exc_info=True)
            return self._error_response(f"An error occurred: {e}")

    @api.model
    def execute_confirmed(self, session_key, confirmed=True):
        """
        Phase 2: Execute or reject a pending intent.
        
        Args:
            session_key: Session key from parse_and_confirm
            confirmed: True to execute, False to reject
        
        Returns:
            dict: {
                "success": bool,
                "state": "executed" | "rejected" | "error",
                "result": dict | None,
                "undo_available": bool,
                "undo_expires_in_minutes": int | None,
                "error": str | None
            }
        """
        ActionLog = self.env["dojo.ai.action.log"]
        log = ActionLog.find_by_session_key(session_key)

        if not log:
            return self._error_response("Session not found or expired.")

        if log.confirmation_status != "pending":
            return self._error_response(f"This action is already {log.confirmation_status}.")

        # Record confirmation
        log.log_confirmation(confirmed, self.env.user.id)

        if not confirmed:
            return {
                "success": True,
                "state": "rejected",
                "result": {"message": "Action cancelled."},
                "undo_available": False,
                "undo_expires_in_minutes": None,
                "error": None,
            }

        # Execute the intent
        start_time = time.time()

        try:
            intent_data = json.loads(log.parsed_intent) if log.parsed_intent else {}
            resolved_data = json.loads(log.resolved_data) if log.resolved_data else {}

            result = self._execute_intent(log.intent_type, intent_data, resolved_data, log)
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Check if this action is undoable
            schema = self.env["dojo.ai.intent.schema"].get_by_type(log.intent_type)
            is_undoable = schema.is_undoable if schema else False

            log.log_execution(
                success=result.get("success", False),
                result=result,
                execution_time_ms=execution_time_ms,
                is_undoable=is_undoable,
            )

            # Calculate undo expiry
            undo_minutes = None
            if is_undoable:
                undo_minutes = int(self.env["ir.config_parameter"].sudo().get_param(
                    "dojo_assistant.undo_expiry_minutes", "60"
                ))

            return {
                "success": result.get("success", False),
                "state": "executed",
                "result": result,
                "undo_available": is_undoable,
                "undo_expires_in_minutes": undo_minutes,
                "error": result.get("error"),
            }

        except Exception as e:
            _logger.error("AI assistant execution failed: %s", e, exc_info=True)
            log.log_execution(success=False, error=str(e))
            return self._error_response(f"Execution failed: {e}")

    @api.model
    def undo_last_action(self, user_id=None):
        """
        Undo the most recent undoable action.
        
        Returns:
            dict: {
                "success": bool,
                "state": "pending_confirmation" | "executed" | "error",
                "session_key": str | None,
                "confirmation_prompt": str | None,
                "undo_target": dict | None,
                "result": dict | None,
                "error": str | None
            }
        """
        ActionLog = self.env["dojo.ai.action.log"]
        log = ActionLog.get_last_undoable(user_id)

        if not log:
            return {
                "success": False,
                "state": "error",
                "error": "No undoable actions found in the last hour.",
                "session_key": None,
                "confirmation_prompt": None,
                "undo_target": None,
                "result": None,
            }

        # Get the undo snapshots
        snapshots = self.env["dojo.ai.undo.snapshot"].get_available_for_action(log.id)
        if not snapshots:
            return self._error_response("Undo data is no longer available.")

        # Build undo target info
        intent_data = json.loads(log.parsed_intent) if log.parsed_intent else {}
        undo_target = {
            "action_log_id": log.id,
            "intent_type": log.intent_type,
            "created_at": log.timestamp.isoformat() if log.timestamp else None,
            "input_text": log.input_text,
            "snapshot_count": len(snapshots),
        }

        # Create confirmation prompt for undo
        time_ago = self._format_time_ago(log.timestamp)
        confirmation_prompt = f"Undo {log.intent_type} from {time_ago}? ({log.input_text[:50]}...)" \
            if len(log.input_text or "") > 50 else f"Undo {log.intent_type} from {time_ago}? ({log.input_text})"

        # Create a new action log for the undo operation
        undo_log = ActionLog.log_parse(
            input_text=f"Undo: {log.input_text}",
            role=log.role,
            intent_type="undo_action",
            parsed_intent={"original_action_log_id": log.id},
            confidence=100.0,
            resolved_data={"snapshots": [s.id for s in snapshots]},
            confirmation_prompt=confirmation_prompt,
            requires_confirmation=True,
        )

        return {
            "success": True,
            "state": "pending_confirmation",
            "session_key": undo_log.session_key,
            "confirmation_prompt": confirmation_prompt,
            "undo_target": undo_target,
            "result": None,
            "error": None,
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # Legacy API: Backward Compatibility
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def process_text_query(self, text):
        """
        Legacy entry point: process a text query through the AI assistant.
        
        DEPRECATED: Use handle_command() or parse_and_confirm() for the new two-phase flow.

        Returns:
            dict: {
                "response": str,
                "action": dict | None
            }
        """
        result = self.parse_and_confirm(text, role="instructor")

        if not result.get("success"):
            return {"response": result.get("error", "An error occurred."), "action": None}

        # For auto-executed intents, return the result
        if result.get("auto_executed"):
            return {
                "response": result.get("response") or str(result.get("result", {}).get("message", "")),
                "action": None,
            }

        # For pending confirmation, return the prompt as response with action
        intent = result.get("intent", {})
        resolved = result.get("resolved_data", {})

        # Build legacy action format for contact_parent
        action = None
        if intent.get("intent_type") == "contact_parent":
            action = {
                "type": "contact_parent",
                "member_id": resolved.get("member_id"),
                "member_name": resolved.get("member_name"),
                "guardian_name": resolved.get("guardian_name"),
                "guardian_email": resolved.get("guardian_email"),
                "guardian_phone": resolved.get("guardian_phone"),
                "suggested_subject": intent.get("parameters", {}).get("subject"),
                "suggested_body": intent.get("parameters", {}).get("body"),
            }

        return {
            "response": result.get("response") or result.get("confirmation_prompt", ""),
            "action": action,
            "session_key": result.get("session_key"),
            "requires_confirmation": True,
        }

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
    # DB Context Builder
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
                    sub = m.active_subscription_id if hasattr(m, 'active_subscription_id') else None
                    plan_str = " plan:{}".format(sub.plan_id.name) if sub and sub.plan_id else ""
                    rank_str = ""
                    if hasattr(m, 'current_rank_id') and m.current_rank_id:
                        rank_str = " rank:{}".format(m.current_rank_id.name)
                    lines.append(
                        "  - {} [id:{}, state:{}{}{}]{}".format(
                            m.name, m.id,
                            getattr(m, 'membership_state', 'unknown'),
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
                    dt = s["start_datetime"]
                    time_str = dt.strftime("%H:%M") if hasattr(dt, "strftime") else str(dt)[:16]
                    lines.append(
                        "  - {} at {} ({}/{} enrolled, state:{})".format(
                            s["template_id"][1] if s["template_id"] else "—",
                            time_str,
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
        household = member.partner_id.parent_id if hasattr(member, 'partner_id') else None
        if household and household.is_household and household.primary_guardian_id:
            gp = household.primary_guardian_id
            email_part = " email:{}".format(gp.email) if gp.email else ""
            phone_part = " phone:{}".format(gp.phone or gp.mobile or "") if (gp.phone or gp.mobile) else ""
            return " guardian:{}{}{}".format(gp.name, email_part, phone_part)
        return ""

    @api.model
    def _error_response(self, error_msg):
        """Build a standard error response dict."""
        return {
            "success": False,
            "state": "error",
            "session_key": None,
            "intent": None,
            "confirmation_prompt": None,
            "resolved_data": None,
            "auto_executed": False,
            "result": None,
            "response": None,
            "error": error_msg,
        }

    @api.model
    def _requires_confirmation(self, intent_type):
        """
        Check if an intent requires user confirmation before execution.
        Read-only intents auto-execute; mutating intents require confirmation.
        """
        if intent_type in _AUTO_EXECUTE_INTENTS:
            return False

        # Check schema for explicit configuration
        schema = self.env["dojo.ai.intent.schema"].get_by_type(intent_type)
        if schema:
            return schema.requires_confirmation

        # Default to requiring confirmation for unknown mutating intents
        return True

    @api.model
    def _build_confirmation_prompt(self, intent_type, intent_data, resolved_data):
        """Build a human-readable confirmation prompt for an intent."""
        params = intent_data.get("parameters", {}) if intent_data else {}

        # Check for custom template in schema
        schema = self.env["dojo.ai.intent.schema"].get_by_type(intent_type)
        if schema and schema.confirmation_template:
            return schema.format_confirmation_prompt(intent_data, resolved_data)

        # Default confirmation prompts by intent type
        prompts = {
            "member_enroll": lambda: "Enroll {} in {}?".format(
                resolved_data.get("member_name", params.get("member_name", "member")),
                resolved_data.get("session_name", params.get("class_name", "the class"))
            ),
            "member_unenroll": lambda: "Remove {} from {}?".format(
                resolved_data.get("member_name", "member"),
                resolved_data.get("session_name", "the class")
            ),
            "belt_promote": lambda: "Promote {} to {}?".format(
                resolved_data.get("member_name", "member"),
                resolved_data.get("new_rank_name", params.get("new_belt", "next belt"))
            ),
            "subscription_create": lambda: "Create {} subscription for {}?".format(
                params.get("plan_name", "a"),
                resolved_data.get("member_name", "member")
            ),
            "subscription_cancel": lambda: "Cancel subscription for {}?".format(
                resolved_data.get("member_name", "member")
            ),
            "contact_parent": lambda: "Send message to {}'s guardian?".format(
                resolved_data.get("member_name", "member")
            ),
            "attendance_checkin": lambda: "Check in {}?".format(
                resolved_data.get("member_name", params.get("member_name", "member"))
            ),
            "attendance_checkout": lambda: "Check out {}?".format(
                resolved_data.get("member_name", "member")
            ),
            "member_create": lambda: "Create new member {}?".format(
                params.get("name", "record")
            ),
            "member_update": lambda: "Update {} profile?".format(
                resolved_data.get("member_name", "member")
            ),
            "class_create": lambda: "Create new class {}?".format(
                params.get("class_name", "template")
            ),
            "class_cancel": lambda: "Cancel {}?".format(
                resolved_data.get("session_name", "the session")
            ),
            "course_enroll": lambda: "Add {} to the {} course roster?".format(
                resolved_data.get("member_name", params.get("member_name", "member")),
                resolved_data.get("template_name", params.get("class_name", "the course"))
            ),
            "belt_test_register": lambda: "Register {} for a belt test (testing for {})?".format(
                resolved_data.get("member_name", params.get("member_name", "member")),
                resolved_data.get("new_rank_name", params.get("target_belt", "next rank"))
            ),
            "undo_action": lambda: "Undo the previous action?",
        }

        if intent_type in prompts:
            try:
                return prompts[intent_type]()
            except Exception as e:
                _logger.warning("Error building confirmation prompt: %s", e)

        return f"Confirm {intent_type.replace('_', ' ')}?"

    @api.model
    def _resolve_entities(self, intent_data):
        """
        Resolve named entities to database IDs.
        
        Takes parsed intent parameters like {member_name: "John Doe"} and
        resolves to {member_id: 123, member_name: "John Doe"}.
        """
        if not intent_data:
            return {}

        resolved = {}
        raw_params = intent_data.get("parameters", {}) or {}
        # Strip unfilled template placeholders like "{name}" or "{{member}}"
        # that the AI occasionally emits instead of real values.
        _placeholder = re.compile(r'^\{[^}]*\}$')
        params = {
            k: v for k, v in raw_params.items()
            if not (isinstance(v, str) and _placeholder.match(v.strip()))
        }

        # Resolve member by name or ID
        if params.get("member_name"):
            members = self._search_members(params["member_name"], limit=3)
            if members:
                member = members[0]
                resolved["member_id"] = member.id
                resolved["member_name"] = member.name
                resolved["member_rank"] = member.current_rank_id.name if hasattr(member, 'current_rank_id') and member.current_rank_id else None
                resolved["member_state"] = getattr(member, 'membership_state', None)

                # Include guardian info
                household = member.partner_id.parent_id if hasattr(member, 'partner_id') else None
                if household and household.is_household and household.primary_guardian_id:
                    g = household.primary_guardian_id
                    resolved["guardian_id"] = g.id
                    resolved["guardian_name"] = g.name
                    resolved["guardian_email"] = g.email
                    resolved["guardian_phone"] = g.phone or g.mobile

        elif params.get("member_id"):
            member = self.env["dojo.member"].browse(int(params["member_id"]))
            if member.exists():
                resolved["member_id"] = member.id
                resolved["member_name"] = member.name
                resolved["member_rank"] = member.current_rank_id.name if hasattr(member, 'current_rank_id') and member.current_rank_id else None

        # Resolve class/session
        # Also check resolved_entities the AI may have already identified
        ai_resolved = intent_data.get("resolved_entities", {}) or {}
        raw_class_name = (
            params.get("class_name")
            or ai_resolved.get("class_name")
        )
        raw_session_id = params.get("session_id") or ai_resolved.get("session_id")

        if raw_class_name or raw_session_id:
            session = None
            from datetime import date as _date
            today = _date.today().isoformat()
            today_domain = [
                ("start_datetime", ">=", today + " 00:00:00"),
                ("start_datetime", "<=", today + " 23:59:59"),
            ]

            if raw_session_id:
                try:
                    session = self.env["dojo.class.session"].browse(int(raw_session_id))
                    if not session.exists():
                        session = None
                except Exception:
                    session = None

            if not session and raw_class_name:
                # 1. Try exact ilike on the full name
                sessions = self.env["dojo.class.session"].search(
                    [("template_id.name", "ilike", raw_class_name)] + today_domain,
                    limit=5,
                )
                if sessions:
                    session = sessions[0]

            if not session and raw_class_name:
                # 2. Word-by-word fallback: score each today-session by how many
                #    significant words from the user query appear in its name.
                #    Weighted by character length so longer/more-specific words
                #    win ties (e.g. "fundamental" beats "advanced").
                all_today = self.env["dojo.class.session"].search(today_domain, limit=50)
                query_words = [
                    w.lower() for w in re.split(r"\W+", raw_class_name)
                    if len(w) > 2
                ]
                best_score, best_session = 0, None
                for s in all_today:
                    tname = (s.template_id.name or "").lower() if s.template_id else ""
                    score = sum(len(w) for w in query_words if w in tname)
                    if score > best_score:
                        best_score, best_session = score, s
                if best_score > 0:
                    session = best_session
                    _logger.info(
                        "AI session fuzzy-matched '%s' → '%s' (score %d)",
                        raw_class_name,
                        session.template_id.name if session.template_id else session.id,
                        best_score,
                    )

            if session and session.exists():
                resolved["session_id"] = session.id
                resolved["session_name"] = session.template_id.name if session.template_id else f"Session #{session.id}"
                resolved["session_datetime"] = session.start_datetime.isoformat() if session.start_datetime else None

        # Resolve belt rank
        if params.get("belt_name") or params.get("new_belt") or params.get("target_belt"):
            belt_name = params.get("target_belt") or params.get("new_belt") or params.get("belt_name")
            ranks = self.env["dojo.belt.rank"].search([
                ("name", "ilike", belt_name)
            ], limit=1)
            if ranks:
                resolved["new_rank_id"] = ranks[0].id
                resolved["new_rank_name"] = ranks[0].name
                resolved["target_belt"] = ranks[0].name  # alias used by belt_test_register confirmation template

        # Resolve class template (for course_enroll — no session lookup needed)
        intent_type_for_resolve = (intent_data.get("intent_type", "") or "").lower()
        # For course_enroll, always resolve the template and ignore any session_id
        if params.get("class_name") and (
            intent_type_for_resolve == "course_enroll" or not resolved.get("session_id")
        ):
            templates = self.env["dojo.class.template"].search([
                ("name", "ilike", params["class_name"])
            ], limit=5)
            if templates:
                # Pick best match by char-length scoring
                query_words = [
                    w.lower() for w in re.split(r"\W+", params["class_name"])
                    if len(w) > 2
                ]
                best_score, best_tmpl = 0, templates[0]
                for t in templates:
                    tname = (t.name or "").lower()
                    score = sum(len(w) for w in query_words if w in tname)
                    if score > best_score:
                        best_score, best_tmpl = score, t
                resolved["template_id"] = best_tmpl.id
                resolved["template_name"] = best_tmpl.name

        # Resolve subscription plan
        if params.get("plan_name") or params.get("plan_id"):
            plan = None
            if params.get("plan_id"):
                plan = self.env["dojo.subscription.plan"].browse(int(params["plan_id"]))
            elif params.get("plan_name"):
                plans = self.env["dojo.subscription.plan"].search([
                    ("name", "ilike", params["plan_name"])
                ], limit=1)
                plan = plans[0] if plans else None

            if plan and plan.exists():
                resolved["plan_id"] = plan.id
                resolved["plan_name"] = plan.name

        return resolved

    # ═══════════════════════════════════════════════════════════════════════════
    # Result Formatter — converts execution data into human-readable text
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def _format_exec_result_as_response(self, intent_type, exec_result):
        """Convert an intent execution result dict into a chat-friendly string."""
        if not exec_result or not exec_result.get("success"):
            return exec_result.get("error") if exec_result else None

        data = exec_result.get("data")
        msg = exec_result.get("message", "")

        if intent_type in ("schedule_today", "class_list"):
            if not data:
                return "No classes scheduled for today."
            lines = ["Here's today's schedule:"]
            for s in data:
                enrolled = s.get("enrolled", 0)
                capacity = s.get("capacity", 0)
                lines.append("  • {} at {} — {}/{} enrolled".format(
                    s.get("name", "Class"),
                    s.get("time", "?"),
                    enrolled,
                    capacity,
                ))
            return "\n".join(lines)

        if intent_type == "member_lookup":
            if not data:
                return msg
            lines = ["{} — {}".format(data.get("name", "Member"), data.get("state", "unknown"))]
            if data.get("rank"):
                lines.append("  Rank: {}".format(data["rank"]))
            sub = data.get("subscription")
            if sub:
                lines.append("  Subscription: {} ({})".format(sub.get("plan", "?"), sub.get("status", "?")))
            if data.get("guardian"):
                lines.append("  Guardian: {}".format(data["guardian"]))
            return "\n".join(lines)

        if intent_type == "belt_lookup":
            if not data:
                return msg
            if isinstance(data, list):
                return "Belt ranks:\n" + "\n".join("  • {}".format(r.get("name", "")) for r in data)
            return "Belt: {}".format(data.get("name", msg))

        if intent_type == "subscription_lookup":
            return msg

        if intent_type == "attendance_history":
            if not data:
                return msg
            lines = [msg]
            for rec in data[:5]:
                session = rec.get("session") or "Open mat"
                lines.append("  • {} — {}".format(rec.get("date", "?"), session))
            return "\n".join(lines)

        # Default: return the message
        return msg

    # ═══════════════════════════════════════════════════════════════════════════
    # Intent Execution Router
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def _execute_intent(self, intent_type, intent_data, resolved_data, action_log):
        """
        Route intent to appropriate handler and execute.
        
        Supports config-driven generic handlers (read & CRUD) and custom handler fallbacks.
        For undoable actions, creates snapshots before execution.
        """
        # Priority 1: Check if this intent uses the generic read handler
        read_config = _INTENT_HANDLER_CONFIG.get(intent_type)
        if read_config:
            try:
                return self._handle_generic_read(intent_type, intent_data, resolved_data, read_config)
            except Exception as e:
                _logger.error("Generic read handler for %s failed: %s", intent_type, e, exc_info=True)
                return {"success": False, "error": f"Handler error: {e}"}
        
        # Priority 2: Check if this intent uses the generic CRUD handler
        crud_config = _CRUD_HANDLER_CONFIG.get(intent_type)
        if crud_config:
            try:
                return self._handle_generic_crud(intent_type, intent_data, resolved_data, action_log, crud_config)
            except UserError as e:
                return {"success": False, "error": str(e)}
            except Exception as e:
                _logger.error("Generic CRUD handler for %s failed: %s", intent_type, e, exc_info=True)
                return {"success": False, "error": f"Handler error: {e}"}
        
        # Priority 3: Fall back to custom handlers for special intents
        handlers = {
            # Mutating intents (complex business logic - cannot be generalized)
            "member_enroll": self._handle_member_enroll,
            "member_unenroll": self._handle_member_unenroll,
            "belt_promote": self._handle_belt_promote,
            "contact_parent": self._handle_contact_parent,
            "attendance_checkin": self._handle_attendance_checkin,
            "attendance_checkout": self._handle_attendance_checkout,
            "course_enroll": self._handle_course_enroll,
            "belt_test_register": self._handle_belt_test_register,

            # Special intents
            "undo_action": self._handle_undo_action,
            "unknown": self._handle_unknown,

            # Extended intents (with complex business logic)
            "subscription_pause": self._handle_subscription_pause,
            "subscription_resume": self._handle_subscription_resume,
            "at_risk_members": self._handle_at_risk_members,
            "campaign_lookup": self._handle_campaign_lookup,
            "marketing_card_lookup": self._handle_marketing_card_lookup,
            "campaign_create": self._handle_campaign_create,
            "campaign_activate": self._handle_campaign_activate,
            "social_post_create": self._handle_social_post_create,
            "social_post_schedule": self._handle_social_post_schedule,
        }

        handler = handlers.get(intent_type, self._handle_unknown)

        try:
            return handler(intent_data, resolved_data, action_log)
        except UserError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            _logger.error("Intent handler %s failed: %s", intent_type, e, exc_info=True)
            return {"success": False, "error": f"Handler error: {e}"}

    # ═══════════════════════════════════════════════════════════════════════════
    # Generic Read Handler (Config-Driven)
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def _handle_generic_read(self, intent_type, intent_data, resolved_data, config):
        """
        Generic handler for all read-only intent operations.
        
        Replaces individual intent handlers for data retrieval.
        Supports dynamic field selection, filtering, and formatting.
        
        Args:
            intent_type: Type of intent (for logging)
            intent_data: Parsed intent with parameters
            resolved_data: Pre-resolved entity IDs
            config: Handler config from _INTENT_HANDLER_CONFIG
        
        Returns:
            dict: {success, message, data}
        """
        model_name = config.get("model")
        if not model_name:
            return {"success": False, "error": f"No model configured for {intent_type}"}
        
        try:
            Model = self.env[model_name]
        except KeyError:
            return {"success": False, "error": f"Model '{model_name}' does not exist"}
        
        # Step 1: Build domain (static or dynamic)
        domain = config.get("domain", [])
        if "domain_builder" in config:
            builder_method_name = config["domain_builder"]
            builder_method = getattr(self, builder_method_name, None)
            if builder_method:
                domain = builder_method(intent_data, resolved_data) or domain
        
        # Step 2: Determine limit (static or from intent parameters)
        limit = config.get("limit", 20)
        if "limit_from_params" in config:
            param_name = config["limit_from_params"]
            params = intent_data.get("parameters", {}) if intent_data else {}
            limit = params.get(param_name, limit)
        
        # Step 3: Get readable fields (respect model field restrictions)
        requested_fields = config.get("fields", [])
        model_fields = Model._fields
        readable_fields = [
            f for f in requested_fields
            if f in model_fields and not model_fields[f].groups
        ]
        
        if not readable_fields:
            readable_fields = list(model_fields.keys())[:10]  # Safety fallback
        
        # Step 4: Search records
        records = Model.search(domain, limit=limit, order="name asc")
        
        if not records:
            return {
                "success": True,
                "message": f"No records found in {model_name}",
                "data": []
            }
        
        # Step 5: Format results by field type
        raw_data = records.read(readable_fields)
        formatted_data = []
        
        for record in raw_data:
            formatted_record = {}
            for field_name in readable_fields:
                value = record.get(field_name)
                field_obj = model_fields[field_name]
                
                # Auto-format based on field type
                if field_obj.type == "many2one" and isinstance(value, (list, tuple)):
                    formatted_record[field_name] = value[1] if value else None
                elif field_obj.type in ("datetime", "date") and value:
                    formatted_record[field_name] = value.isoformat() if hasattr(value, "isoformat") else str(value)
                elif field_obj.type == "many2many" and isinstance(value, list):
                    formatted_record[field_name] = value  # Already IDs
                elif field_obj.type == "selection" and value:
                    # Try to get human-readable label
                    if hasattr(field_obj, "selection"):
                        selection_dict = dict(field_obj.selection if callable(field_obj.selection) else field_obj.selection)
                        formatted_record[field_name] = selection_dict.get(value, value)
                    else:
                        formatted_record[field_name] = value
                else:
                    formatted_record[field_name] = value
            
            formatted_data.append(formatted_record)
        
        return {
            "success": True,
            "message": f"Found {len(formatted_data)} records in {model_name}",
            "data": formatted_data
        }

    # ─── Domain Builders for config-driven intents ────────────────────────────
    
    @api.model
    def _domain_member_lookup(self, intent_data, resolved_data):
        """
        Build domain for member lookup.
        Supports lookup by member_id or member_name.
        """
        member_id = resolved_data.get("member_id")
        if member_id:
            return [("id", "=", member_id)]
        
        params = intent_data.get("parameters", {}) if intent_data else {}
        name = params.get("member_name", "")
        if name:
            return [("name", "ilike", name)]
        
        return []
    
    @api.model
    def _domain_class_list(self, intent_data, resolved_data):
        """
        Build domain for class session list.
        Filters by date if provided in intent parameters.
        """
        params = intent_data.get("parameters", {}) if intent_data else {}
        target_date = params.get("date") or fields.Date.today().isoformat()
        
        return [
            ("start_datetime", ">=", f"{target_date} 00:00:00"),
            ("start_datetime", "<=", f"{target_date} 23:59:59"),
        ]
    
    @api.model
    def _domain_schedule_today(self, intent_data, resolved_data):
        """
        Build domain for today's schedule (same as class_list for today).
        """
        today = fields.Date.today().isoformat()
        return [
            ("start_datetime", ">=", f"{today} 00:00:00"),
            ("start_datetime", "<=", f"{today} 23:59:59"),
        ]
    
    @api.model
    def _domain_subscription_lookup(self, intent_data, resolved_data):
        """
        Build domain for subscription lookup.
        Returns active subscriptions for a member.
        """
        member_id = resolved_data.get("member_id")
        if not member_id:
            return [("id", "=", -1)]  # Return nothing
        
        return [
            ("member_id", "=", member_id),
            ("state", "=", "active"),
        ]
    
    @api.model
    def _domain_attendance_history(self, intent_data, resolved_data):
        """
        Build domain for attendance history.
        Returns recent attendance logs for a member.
        """
        member_id = resolved_data.get("member_id")
        if not member_id:
            return [("id", "=", -1)]  # Return nothing
        
        return [("member_id", "=", member_id)]

    # ═══════════════════════════════════════════════════════════════════════════
    # Generic CRUD Handler (Config-Driven)
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def _handle_generic_crud(self, intent_type, intent_data, resolved_data, action_log, config):
        """
        Generic CRUD handler for create, update, delete operations.
        
        Supports:
        - Field validation (required, type checking)
        - Relationship resolution (many2one lookups)
        - Default values and builders
        - Audit trail via mail.thread
        - Undo snapshots
        
        Args:
            intent_type: Type of intent (for logging)
            intent_data: Parsed intent with parameters
            resolved_data: Pre-resolved entity IDs
            action_log: Action log record
            config: CRUD config from _CRUD_HANDLER_CONFIG
        
        Returns:
            dict: {success, message, data}
        """
        model_name = config.get("model")
        operation = config.get("operation", "create")
        
        try:
            Model = self.env[model_name]
        except KeyError:
            return {"success": False, "error": f"Model '{model_name}' does not exist"}
        
        # ─── CREATE Operation ─────────────────────────────────────────────────
        if operation == "create":
            return self._crud_create(Model, model_name, intent_data, config, action_log)
        
        # ─── UPDATE Operation ─────────────────────────────────────────────────
        elif operation == "update":
            domain = config.get("domain", [])
            if "target_domain_builder" in config:
                builder_method = getattr(self, config["target_domain_builder"], None)
                if builder_method:
                    domain = builder_method(intent_data, resolved_data) or domain
            return self._crud_update(Model, model_name, intent_data, domain, config, action_log)
        
        # ─── DELETE Operation ─────────────────────────────────────────────────
        elif operation == "delete":
            domain = config.get("domain", [])
            if "target_domain_builder" in config:
                builder_method = getattr(self, config["target_domain_builder"], None)
                if builder_method:
                    domain = builder_method(intent_data, resolved_data) or domain
            return self._crud_delete(Model, model_name, domain, config, action_log)
        
        return {"success": False, "error": f"Unknown CRUD operation: {operation}"}

    @api.model
    def _crud_create(self, Model, model_name, intent_data, config, action_log):
        """Create a new record."""
        params = intent_data.get("parameters", {}) if intent_data else {}
        fields_config = config.get("fields", {})
        
        # ─── Validate required fields ─────────────────────────────────────────
        values = {}
        for field_name, field_cfg in fields_config.items():
            if field_cfg.get("required") and field_name not in params:
                return {"success": False, "error": f"Required field '{field_name}' not provided"}
            
            if field_name in params:
                value = params[field_name]
                
                # Resolve relationships (many2one)
                if field_cfg.get("type") == "many2one" and field_cfg.get("resolver"):
                    resolver = getattr(self, field_cfg["resolver"], None)
                    if resolver:
                        resolved_id = resolver(value, Model)
                        if not resolved_id:
                            return {"success": False, "error": f"Could not resolve {field_name}: {value}"}
                        values[field_name] = resolved_id
                    else:
                        values[field_name] = value
                else:
                    values[field_name] = value
            elif "default" in field_cfg:
                values[field_name] = field_cfg["default"]
            elif "default_builder" in field_cfg:
                builder = getattr(self, field_cfg["default_builder"], None)
                if builder:
                    values[field_name] = builder()
        
        # ─── Create record ────────────────────────────────────────────────────
        try:
            record = Model.create(values)
            
            # Create undo snapshot if enabled
            if config.get("allow_undo", True):
                Snapshot = self.env["dojo.ai.undo.snapshot"]
                Snapshot.create_snapshot(action_log.id, model_name, record.id, "create")
            
            return {
                "success": True,
                "message": f"Created {record._rec_name or model_name}",
                "data": {"id": record.id, "record": record.name_get()[0][1] if hasattr(record, 'name_get') else str(record)},
            }
        except Exception as e:
            _logger.error("CRUD create failed: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    @api.model
    def _crud_update(self, Model, model_name, intent_data, domain, config, action_log):
        """Update existing records."""
        params = intent_data.get("parameters", {}) if intent_data else {}
        fields_config = config.get("fields", {})
        
        # ─── Find target record ───────────────────────────────────────────────
        records = Model.search(domain, limit=1)
        if not records:
            return {"success": False, "error": f"No {model_name} found to update"}
        
        record = records[0]
        
        # ─── Build update values ──────────────────────────────────────────────
        values = {}
        for field_name, value in params.items():
            if field_name in fields_config:
                field_cfg = fields_config[field_name]
                
                # Resolve relationships (many2one)
                if field_cfg.get("type") == "many2one" and field_cfg.get("resolver"):
                    resolver = getattr(self, field_cfg["resolver"], None)
                    if resolver:
                        resolved_id = resolver(value, Model)
                        values[field_name] = resolved_id
                    else:
                        values[field_name] = value
                else:
                    values[field_name] = value
        
        if not values:
            return {"success": False, "error": "No fields to update"}
        
        # ─── Create snapshot of old values ────────────────────────────────────
        try:
            if config.get("allow_undo", True):
                Snapshot = self.env["dojo.ai.undo.snapshot"]
                old_values = {k: getattr(record, k, None) for k in values.keys()}
                Snapshot.create_snapshot(
                    action_log.id, model_name, record.id, "write",
                    snapshot_data=old_values
                )
            
            # Update record
            record.write(values)
            
            return {
                "success": True,
                "message": f"Updated {record._rec_name or model_name}",
                "data": {"id": record.id, "updated_fields": list(values.keys())},
            }
        except Exception as e:
            _logger.error("CRUD update failed: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    @api.model
    def _crud_delete(self, Model, model_name, domain, config, action_log):
        """Delete records."""
        # ─── Find target record ───────────────────────────────────────────────
        records = Model.search(domain, limit=1)
        if not records:
            return {"success": False, "error": f"No {model_name} found to delete"}
        
        record = records[0]
        record_display = record.name_get()[0][1] if hasattr(record, 'name_get') else str(record)
        
        # ─── Create snapshot of record ────────────────────────────────────────
        try:
            if config.get("allow_undo", True):
                Snapshot = self.env["dojo.ai.undo.snapshot"]
                # Store full record data for potential restoration
                record_data = record.read()[0] if record else {}
                Snapshot.create_snapshot(
                    action_log.id, model_name, record.id, "unlink",
                    snapshot_data=record_data
                )
            
            # Delete record
            record.unlink()
            
            return {
                "success": True,
                "message": f"Deleted {record_display}",
                "data": {"id": record.id},
            }
        except Exception as e:
            _logger.error("CRUD delete failed: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    # ─── CRUD Helper: Resolvers for relationships ──────────────────────────────
    
    @api.model
    def _resolve_member(self, value, model=None):
        """Resolve member by name or ID."""
        if isinstance(value, int):
            return value
        Member = self.env["dojo.member"]
        members = Member.search([("name", "ilike", value)], limit=1)
        return members[0].id if members else None
    
    @api.model
    def _resolve_class_template(self, value, model=None):
        """Resolve class template by name or ID."""
        if isinstance(value, int):
            return value
        Template = self.env["dojo.class.template"]
        templates = Template.search([("name", "ilike", value), ("active", "=", True)], limit=1)
        return templates[0].id if templates else None
    
    @api.model
    def _resolve_subscription_plan(self, value, model=None):
        """Resolve subscription plan by name or ID."""
        if isinstance(value, int):
            return value
        Plan = self.env["dojo.subscription.plan"]
        plans = Plan.search([("name", "ilike", value), ("active", "=", True)], limit=1)
        return plans[0].id if plans else None
    
    @api.model
    def _resolve_program(self, value, model=None):
        """Resolve program by name or ID."""
        if isinstance(value, int):
            return value
        Program = self.env["dojo.program"]
        programs = Program.search([("name", "ilike", value), ("active", "=", True)], limit=1)
        return programs[0].id if programs else None
    
    @api.model
    def _resolve_belt_rank(self, value, model=None):
        """Resolve belt rank by name or ID."""
        if isinstance(value, int):
            return value
        Rank = self.env["dojo.belt.rank"]
        ranks = Rank.search([("name", "ilike", value), ("active", "=", True)], limit=1)
        return ranks[0].id if ranks else None
    
    # ─── CRUD Helper: Default value builders ───────────────────────────────────
    
    @api.model
    def _default_today(self):
        """Return today's date."""
        return fields.Date.today()

    # ─── CRUD Helper: Target domain builders ───────────────────────────────────
    
    @api.model
    def _domain_crud_member(self, intent_data, resolved_data):
        """Domain for update/delete on members."""
        member_id = resolved_data.get("member_id")
        if member_id:
            return [("id", "=", member_id)]
        
        params = intent_data.get("parameters", {}) if intent_data else {}
        name = params.get("member_name")
        if name:
            return [("name", "ilike", name)]
        
        return [("id", "=", -1)]  # Return nothing
    
    @api.model
    def _domain_crud_session(self, intent_data, resolved_data):
        """Domain for update/delete on class sessions."""
        session_id = resolved_data.get("session_id")
        return [("id", "=", session_id)] if session_id else [("id", "=", -1)]
    
    @api.model
    def _domain_crud_subscription(self, intent_data, resolved_data):
        """Domain for update/delete on subscriptions."""
        member_id = resolved_data.get("member_id")
        if member_id:
            return [("member_id", "=", member_id), ("state", "=", "active")]
        return [("id", "=", -1)]
    
    @api.model
    def _domain_crud_enrollment(self, intent_data, resolved_data):
        """Domain for update/delete on class enrollments."""
        member_id = resolved_data.get("member_id")
        session_id = resolved_data.get("session_id")
        
        if member_id and session_id:
            return [("member_id", "=", member_id), ("session_id", "=", session_id)]
        elif member_id:
            return [("member_id", "=", member_id)]
        elif session_id:
            return [("session_id", "=", session_id)]
        return [("id", "=", -1)]

    # ═══════════════════════════════════════════════════════════════════════════
    # Intent Handlers: Mutating (Require Confirmation)
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def _handle_member_enroll(self, intent_data, resolved_data, action_log):
        """Enroll a member in a class session."""
        member_id = resolved_data.get("member_id")
        session_id = resolved_data.get("session_id")

        if not member_id:
            return {"success": False, "error": "Member not found."}
        if not session_id:
            return {"success": False, "error": "Class session not found."}

        member = self.env["dojo.member"].browse(member_id)
        session = self.env["dojo.class.session"].browse(session_id)

        # Create undo snapshot
        Snapshot = self.env["dojo.ai.undo.snapshot"]

        # Check if already enrolled
        Enrollment = self.env["dojo.class.enrollment"]
        existing = Enrollment.search([
            ("member_id", "=", member.id),
            ("session_id", "=", session.id),
        ], limit=1)

        if existing:
            return {
                "success": False,
                "error": f"{member.name} is already enrolled in {session.template_id.name}.",
            }

        # Check capacity
        if session.seats_taken >= session.capacity:
            return {
                "success": False,
                "error": f"{session.template_id.name} is at capacity ({session.capacity}).",
            }

        # Create enrollment — bypass course-roster check since the instructor
        # is explicitly authorising this enrolment via the AI assistant.
        enrollment = Enrollment.with_context(
            skip_course_membership_check=True
        ).create({
            "member_id": member.id,
            "session_id": session.id,
            "status": "registered",
        })

        # Create snapshot for undo
        Snapshot.create_snapshot(action_log.id, Enrollment._name, enrollment.id, "create")

        return {
            "success": True,
            "message": f"Enrolled {member.name} in {session.template_id.name}.",
            "data": {"enrollment_id": enrollment.id},
        }

    @api.model
    def _handle_member_unenroll(self, intent_data, resolved_data, action_log):
        """Remove a member from a class session."""
        member_id = resolved_data.get("member_id")
        session_id = resolved_data.get("session_id")

        if not member_id or not session_id:
            return {"success": False, "error": "Member or session not found."}

        Enrollment = self.env["dojo.class.enrollment"]
        enrollment = Enrollment.search([
            ("member_id", "=", member_id),
            ("session_id", "=", session_id),
        ], limit=1)

        if not enrollment:
            return {"success": False, "error": "No enrollment found."}

        # Create snapshot for undo (capture before deletion)
        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(action_log.id, Enrollment._name, enrollment.id, "unlink")

        member_name = enrollment.member_id.name
        session_name = enrollment.session_id.template_id.name if enrollment.session_id.template_id else "the session"

        enrollment.unlink()

        return {
            "success": True,
            "message": f"Removed {member_name} from {session_name}.",
        }

    @api.model
    def _handle_belt_promote(self, intent_data, resolved_data, action_log):
        """Promote a member to a new belt rank."""
        member_id = resolved_data.get("member_id")
        new_rank_id = resolved_data.get("new_rank_id")

        if not member_id:
            return {"success": False, "error": "Member not found."}
        if not new_rank_id:
            return {"success": False, "error": "New belt rank not specified."}

        member = self.env["dojo.member"].browse(member_id)
        new_rank = self.env["dojo.belt.rank"].browse(new_rank_id)
        old_rank = member.current_rank_id if hasattr(member, 'current_rank_id') else None

        # Create snapshot of current rank
        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(
            action_log.id, "dojo.member", member.id, "write",
            snapshot_data={"current_rank_id": old_rank.id if old_rank else False}
        )

        # Create member rank record
        MemberRank = self.env["dojo.member.rank"]
        member_rank = MemberRank.create({
            "member_id": member.id,
            "rank_id": new_rank.id,
            "date_awarded": fields.Date.today(),
        })

        # Update member's current rank
        member.current_rank_id = new_rank.id

        old_name = old_rank.name if old_rank else "no belt"
        return {
            "success": True,
            "message": f"Promoted {member.name} from {old_name} to {new_rank.name}.",
            "data": {"member_rank_id": member_rank.id},
        }

    @api.model
    def _handle_contact_parent(self, intent_data, resolved_data, action_log):
        """Send a message to a member's guardian."""
        member_id = resolved_data.get("member_id")

        if not member_id:
            return {"success": False, "error": "Member not found."}

        params = intent_data.get("parameters", {}) if intent_data else {}
        subject = params.get("subject", "Message from Dojo")
        body = params.get("body", params.get("message", ""))

        if not body:
            return {"success": False, "error": "Message body is required."}

        result = self.send_parent_message(
            member_id=member_id,
            subject=subject,
            body=body,
            send_email=params.get("send_email", True),
            send_sms=params.get("send_sms", True),
        )

        return result

    @api.model
    def _handle_attendance_checkin(self, intent_data, resolved_data, action_log):
        """Check in a member for attendance."""
        member_id = resolved_data.get("member_id")
        session_id = resolved_data.get("session_id")

        if not member_id:
            return {"success": False, "error": "Member not found."}

        member = self.env["dojo.member"].browse(member_id)

        # Create attendance log
        AttLog = self.env["dojo.attendance.log"]

        # Check if already checked in today without checkout
        from datetime import datetime, date as _date
        today_start = datetime.combine(_date.today(), datetime.min.time())
        existing = AttLog.search([
            ("member_id", "=", member.id),
            ("checkin_datetime", ">=", today_start),
            ("checkout_datetime", "=", False),
        ], limit=1)

        if existing:
            return {
                "success": False,
                "error": f"{member.name} is already checked in.",
            }

        values = {
            "member_id": member.id,
            "checkin_datetime": fields.Datetime.now(),
        }
        if session_id:
            values["session_id"] = session_id

        log = AttLog.create(values)

        # Create snapshot for undo
        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(action_log.id, AttLog._name, log.id, "create")

        return {
            "success": True,
            "message": f"Checked in {member.name}.",
            "data": {"attendance_log_id": log.id},
        }

    @api.model
    def _handle_attendance_checkout(self, intent_data, resolved_data, action_log):
        """Check out a member from attendance."""
        member_id = resolved_data.get("member_id")

        if not member_id:
            return {"success": False, "error": "Member not found."}

        member = self.env["dojo.member"].browse(member_id)

        # Find unclosed attendance log
        AttLog = self.env["dojo.attendance.log"]
        from datetime import datetime, date as _date
        today_start = datetime.combine(_date.today(), datetime.min.time())

        log = AttLog.search([
            ("member_id", "=", member.id),
            ("checkin_datetime", ">=", today_start),
            ("checkout_datetime", "=", False),
        ], order="checkin_datetime desc", limit=1)

        if not log:
            return {"success": False, "error": f"{member.name} is not checked in."}

        # Create snapshot for undo
        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(
            action_log.id, AttLog._name, log.id, "write",
            snapshot_data={"checkout_datetime": False}
        )

        log.checkout_datetime = fields.Datetime.now()

        return {
            "success": True,
            "message": f"Checked out {member.name}.",
            "data": {"attendance_log_id": log.id},
        }

    @api.model
    def _handle_course_enroll(self, intent_data, resolved_data, action_log):
        """Add a member to a course's permanent roster (template.course_member_ids)."""
        member_id = resolved_data.get("member_id")
        template_id = resolved_data.get("template_id")

        if not member_id:
            params = intent_data.get("parameters", {}) if intent_data else {}
            return {"success": False, "error": f"Member '{params.get('member_name', '')}' not found."}
        if not template_id:
            params = intent_data.get("parameters", {}) if intent_data else {}
            return {"success": False, "error": f"Course '{params.get('class_name', '')}' not found."}

        member = self.env["dojo.member"].browse(member_id)
        template = self.env["dojo.class.template"].browse(template_id)

        # Check if already on the roster
        if member in template.course_member_ids:
            return {
                "success": False,
                "error": f"{member.name} is already on the {template.name} roster.",
            }

        # Add to roster
        template.course_member_ids = [(4, member.id)]

        # Create snapshot for undo (write snapshot on template)
        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(
            action_log.id, "dojo.class.template", template.id, "write",
            snapshot_data={"course_member_ids": [(3, member.id)]}
        )

        return {
            "success": True,
            "message": f"Added {member.name} to the {template.name} course roster.",
            "data": {"template_id": template.id, "member_id": member.id},
        }

    @api.model
    def _handle_belt_test_register(self, intent_data, resolved_data, action_log):
        """Register a member for an upcoming belt test."""
        member_id = resolved_data.get("member_id")
        new_rank_id = resolved_data.get("new_rank_id")

        if not member_id:
            params = intent_data.get("parameters", {}) if intent_data else {}
            return {"success": False, "error": f"Member '{params.get('member_name', '')}' not found."}
        if not new_rank_id:
            params = intent_data.get("parameters", {}) if intent_data else {}
            return {"success": False, "error": f"Belt rank '{params.get('target_belt', '')}' not found."}

        member = self.env["dojo.member"].browse(member_id)
        rank = self.env["dojo.belt.rank"].browse(new_rank_id)
        params = intent_data.get("parameters", {}) if intent_data else {}

        # Find an upcoming scheduled belt test
        BeltTest = self.env["dojo.belt.test"]
        domain = [("state", "=", "scheduled")]

        # Optionally filter by test_date if provided
        test_date = params.get("test_date")
        if test_date:
            domain.append(("test_date", "=", test_date))

        # Optionally filter by test name if provided
        test_name = params.get("test_name")
        if test_name:
            domain.append(("name", "ilike", test_name))

        belt_test = BeltTest.search(domain, order="test_date asc", limit=1)

        if not belt_test:
            # Create a new belt test if none is scheduled
            from datetime import date as _date, timedelta
            default_date = _date.today() + timedelta(days=14)
            belt_test = BeltTest.create({
                "name": f"Belt Test — {default_date.isoformat()}",
                "test_date": default_date,
                "state": "scheduled",
            })
            _logger.info("AI created new belt test %s for registration", belt_test.id)

        # Check for duplicate registration
        Registration = self.env["dojo.belt.test.registration"]
        existing = Registration.search([
            ("test_id", "=", belt_test.id),
            ("member_id", "=", member.id),
        ], limit=1)

        if existing:
            return {
                "success": False,
                "error": f"{member.name} is already registered for this belt test.",
            }

        # Create registration
        reg = Registration.create({
            "test_id": belt_test.id,
            "member_id": member.id,
            "target_rank_id": rank.id,
            "result": "pending",
        })

        # Create snapshot for undo
        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(action_log.id, Registration._name, reg.id, "create")

        test_date_str = belt_test.test_date.isoformat() if belt_test.test_date else "TBD"
        return {
            "success": True,
            "message": f"Registered {member.name} for belt test on {test_date_str} (testing for {rank.name}).",
            "data": {"registration_id": reg.id, "test_id": belt_test.id},
        }

    @api.model
    def _handle_undo_action(self, intent_data, resolved_data, action_log):
        """Execute an undo operation via chat — delegates to undo_last_action()."""
        user_id = self.env.user.id
        result = self.undo_last_action(user_id=user_id)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "No undo data available.")}
        return {
            "success": True,
            "message": result.get("confirmation_prompt") or "Undo complete.",
            "data": result,
        }

    @api.model
    def _handle_unknown(self, intent_data, resolved_data, action_log):
        """Handle unknown/unrecognized intents."""
        return {
            "success": False,
            "error": "I'm not sure what action you want. Could you please rephrase?",
            "data": None,
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # Extended Intent Handlers
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def _handle_at_risk_members(self, intent_data, resolved_data, action_log):
        """Return active members who haven't attended in N days."""
        from datetime import datetime, timedelta
        params = intent_data.get("parameters", {}) if intent_data else {}
        days = int(params.get("days", 14))
        cutoff = datetime.now() - timedelta(days=days)

        members = self.env["dojo.member"].search([("membership_state", "=", "active")])
        at_risk = []
        for m in members:
            last = self.env["dojo.attendance.log"].search(
                [("member_id", "=", m.id)], order="checkin_datetime desc", limit=1
            )
            if not last or last.checkin_datetime < cutoff:
                days_ago = (datetime.now() - last.checkin_datetime).days if last else None
                at_risk.append({
                    "name": m.name,
                    "days_since_visit": days_ago if days_ago is not None else "never",
                })

        if not at_risk:
            return {"success": True, "message": f"No members missing for more than {days} days.", "data": []}

        lines = [f"• {r['name']} — {r['days_since_visit']} days ago" for r in at_risk]
        return {
            "success": True,
            "message": f"{len(at_risk)} members haven't been in for {days}+ days:\n" + "\n".join(lines),
            "data": at_risk,
        }

    @api.model
    def _handle_campaign_lookup(self, intent_data, resolved_data, action_log):
        """Return recent campaign stats."""
        Campaign = self.env.get("dojo.marketing.campaign")
        if not Campaign:
            return {"success": False, "error": "Marketing module is not installed."}

        campaigns = Campaign.search([], order="last_sent_date desc", limit=5)
        if not campaigns:
            return {"success": True, "message": "No campaigns found.", "data": []}

        lines = []
        for c in campaigns:
            lines.append(f"• {c.name}: {c.sent_count} sent, last on {c.last_sent_date or 'never'}")
        return {
            "success": True,
            "message": "Recent campaigns:\n" + "\n".join(lines),
            "data": [{"name": c.name, "sent_count": c.sent_count} for c in campaigns],
        }

    @api.model
    def _handle_marketing_card_lookup(self, intent_data, resolved_data, action_log):
        """Return marketing cards published to the kiosk."""
        Card = self.env.get("dojo.marketing.card")
        if not Card:
            return {"success": False, "error": "Marketing module is not installed."}

        cards = Card.search([("publish_kiosk", "=", True)])
        if not cards:
            return {"success": True, "message": "No marketing cards are currently on the kiosk.", "data": []}

        lines = [f"• {c.name} ({c.card_type})" for c in cards]
        return {
            "success": True,
            "message": f"{len(cards)} card(s) on the kiosk:\n" + "\n".join(lines),
            "data": [{"name": c.name, "type": c.card_type} for c in cards],
        }

    @api.model
    def _handle_subscription_pause(self, intent_data, resolved_data, action_log):
        """Pause a member's active subscription."""
        member_id = resolved_data.get("member_id")
        if not member_id:
            return {"success": False, "error": "Could not identify the member."}

        sub = self.env["dojo.member.subscription"].search(
            [("member_id", "=", member_id), ("state", "=", "active")], limit=1
        )
        if not sub:
            return {"success": False, "error": "No active subscription found for this member."}

        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(action_log.id, "dojo.member.subscription", sub.id, "write", snapshot_data={"state": sub.state})
        sub.write({"state": "paused"})
        member = self.env["dojo.member"].browse(member_id)
        return {
            "success": True,
            "message": f"Paused {member.name}'s subscription ({sub.plan_id.name if sub.plan_id else 'subscription'}).",
            "data": {"subscription_id": sub.id},
        }

    @api.model
    def _handle_subscription_resume(self, intent_data, resolved_data, action_log):
        """Resume a member's paused subscription."""
        member_id = resolved_data.get("member_id")
        if not member_id:
            return {"success": False, "error": "Could not identify the member."}

        sub = self.env["dojo.member.subscription"].search(
            [("member_id", "=", member_id), ("state", "=", "paused")], limit=1
        )
        if not sub:
            return {"success": False, "error": "No paused subscription found for this member."}

        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(action_log.id, "dojo.member.subscription", sub.id, "write", snapshot_data={"state": sub.state})
        sub.write({"state": "active"})
        member = self.env["dojo.member"].browse(member_id)
        return {
            "success": True,
            "message": f"Resumed {member.name}'s subscription.",
            "data": {"subscription_id": sub.id},
        }

    @api.model
    def _handle_campaign_create(self, intent_data, resolved_data, action_log):
        """Create a new marketing campaign in draft state."""
        Campaign = self.env.get("dojo.marketing.campaign")
        if not Campaign:
            return {"success": False, "error": "Marketing module is not installed."}

        params = intent_data.get("parameters", {}) if intent_data else {}
        name = params.get("campaign_name", "New Campaign")
        send_email = params.get("send_email", True)
        send_sms = params.get("send_sms", False)

        campaign = Campaign.create({
            "name": name,
            "send_email": send_email,
            "send_sms": send_sms,
            "state": "draft",
        })
        Snapshot = self.env["dojo.ai.undo.snapshot"]
        Snapshot.create_snapshot(action_log.id, "dojo.marketing.campaign", campaign.id, "create")
        return {
            "success": True,
            "message": f"Created campaign '{name}' in draft state. Activate it when ready to send.",
            "data": {"campaign_id": campaign.id, "name": name},
        }

    @api.model
    def _handle_campaign_activate(self, intent_data, resolved_data, action_log):
        """Activate a draft marketing campaign."""
        Campaign = self.env.get("dojo.marketing.campaign")
        if not Campaign:
            return {"success": False, "error": "Marketing module is not installed."}

        params = intent_data.get("parameters", {}) if intent_data else {}
        name = params.get("campaign_name", "")
        campaign_id = resolved_data.get("campaign_id")

        if campaign_id:
            campaign = Campaign.browse(campaign_id)
        elif name:
            campaign = Campaign.search([("name", "ilike", name), ("state", "=", "draft")], limit=1)
        else:
            campaign = Campaign.search([("state", "=", "draft")], order="id desc", limit=1)

        if not campaign:
            return {"success": False, "error": "No draft campaign found to activate."}

        campaign.action_activate()
        return {
            "success": True,
            "message": f"Campaign '{campaign.name}' is now active and will send on the next scheduled run.",
            "data": {"campaign_id": campaign.id},
        }

    @api.model
    def _handle_social_post_create(self, intent_data, resolved_data, action_log):
        """Create and immediately publish a social post."""
        Post = self.env.get("dojo.social.post")
        if not Post:
            return {"success": False, "error": "Social media module is not installed."}

        params = intent_data.get("parameters", {}) if intent_data else {}
        message = params.get("message", "")
        account_id = resolved_data.get("social_account_id")

        if not message:
            return {"success": False, "error": "No post message provided."}

        account = self.env["dojo.social.account"].browse(account_id) if account_id else \
            self.env["dojo.social.account"].search([("status", "=", "connected")], limit=1)

        if not account:
            return {"success": False, "error": "No connected social account found."}

        post = Post.create({"message": message, "account_id": account.id})
        try:
            post.action_post_now()
        except Exception as e:
            return {"success": False, "error": str(e)}

        return {
            "success": True,
            "message": f"Posted to {account.name}: '{message[:60]}...'",
            "data": {"post_id": post.id},
        }

    @api.model
    def _handle_social_post_schedule(self, intent_data, resolved_data, action_log):
        """Create a scheduled social post."""
        Post = self.env.get("dojo.social.post")
        if not Post:
            return {"success": False, "error": "Social media module is not installed."}

        params = intent_data.get("parameters", {}) if intent_data else {}
        message = params.get("message", "")
        scheduled_date = params.get("scheduled_date")
        account_id = resolved_data.get("social_account_id")

        if not message:
            return {"success": False, "error": "No post message provided."}
        if not scheduled_date:
            return {"success": False, "error": "No scheduled date provided."}

        account = self.env["dojo.social.account"].browse(account_id) if account_id else \
            self.env["dojo.social.account"].search([("status", "=", "connected")], limit=1)

        if not account:
            return {"success": False, "error": "No connected social account found."}

        post = Post.create({
            "message": message,
            "account_id": account.id,
            "scheduled_date": scheduled_date,
            "state": "scheduled",
        })
        return {
            "success": True,
            "message": f"Scheduled post to {account.name} for {scheduled_date}: '{message[:60]}'",
            "data": {"post_id": post.id},
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # Utility Methods
    # ═══════════════════════════════════════════════════════════════════════════

    @api.model
    def _format_time_ago(self, dt):
        """Format a datetime as a human-readable time ago string."""
        if not dt:
            return "unknown time"

        from datetime import datetime
        now = datetime.now()
        if dt.tzinfo:
            now = now.replace(tzinfo=dt.tzinfo)

        diff = now - dt
        seconds = diff.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"
