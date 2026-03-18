# -*- coding: utf-8 -*-
"""
Dojo AI Action Log — Audit trail for all AI assistant operations.

Tracks:
- Input (text/voice) and intent parsing
- Confirmation flow (pending → confirmed/rejected)
- Execution results and timing
- Undo capability and state
"""

import json
import logging
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoAiActionLog(models.Model):
    _name = "dojo.ai.action.log"
    _description = "AI Action Log"
    _order = "timestamp desc"
    _rec_name = "session_key"

    # ─── Session Identification ───────────────────────────────────────────────
    session_key = fields.Char(
        string="Session Key",
        required=True,
        index=True,
        default=lambda self: self._generate_session_key(),
        help="Unique key for this action session, used for confirmation flow",
    )
    timestamp = fields.Datetime(
        string="Timestamp",
        default=fields.Datetime.now,
        index=True,
    )

    # ─── User Context ─────────────────────────────────────────────────────────
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        index=True,
    )
    role = fields.Selection(
        [
            ("kiosk", "Kiosk"),
            ("instructor", "Instructor"),
            ("admin", "Admin"),
        ],
        string="Role",
        default="instructor",
        help="User role at time of action",
    )

    # ─── Input ────────────────────────────────────────────────────────────────
    input_type = fields.Selection(
        [
            ("text", "Text"),
            ("voice", "Voice"),
        ],
        string="Input Type",
        default="text",
    )
    input_text = fields.Text(
        string="Input Text",
        help="Original user input (or transcribed voice)",
    )
    audio_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Audio Attachment",
        help="Original audio file for voice input",
    )

    # ─── Intent Parsing ───────────────────────────────────────────────────────
    intent_type = fields.Char(
        string="Intent Type",
        index=True,
        help="Detected intent type (e.g., member_lookup, class_enroll)",
    )
    parsed_intent = fields.Text(
        string="Parsed Intent (JSON)",
        help="Full parsed intent structure from AI",
    )
    confidence = fields.Float(
        string="Confidence",
        digits=(3, 2),
        help="AI confidence in intent classification (0.0 - 1.0)",
    )
    resolved_data = fields.Text(
        string="Resolved Data (JSON)",
        help="Resolved entity data (member IDs, session IDs, etc.)",
    )

    # ─── Confirmation Flow ────────────────────────────────────────────────────
    requires_confirmation = fields.Boolean(
        string="Requires Confirmation",
        default=True,
    )
    confirmation_prompt = fields.Text(
        string="Confirmation Prompt",
        help="Human-readable prompt shown to user for confirmation",
    )
    confirmation_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("confirmed", "Confirmed"),
            ("rejected", "Rejected"),
            ("auto", "Auto-Executed"),
        ],
        string="Confirmation Status",
        default="pending",
        index=True,
    )
    confirmed_by = fields.Many2one(
        "res.users",
        string="Confirmed By",
    )
    confirmed_at = fields.Datetime(
        string="Confirmed At",
    )

    # ─── Execution ────────────────────────────────────────────────────────────
    execution_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("success", "Success"),
            ("error", "Error"),
        ],
        string="Execution Status",
        default="pending",
        index=True,
    )
    execution_result = fields.Text(
        string="Execution Result (JSON)",
    )
    error_message = fields.Text(
        string="Error Message",
    )
    execution_time_ms = fields.Integer(
        string="Execution Time (ms)",
    )

    # ─── Bulk Operations ──────────────────────────────────────────────────────
    is_bulk = fields.Boolean(
        string="Bulk Operation",
        default=False,
    )
    bulk_count = fields.Integer(
        string="Bulk Count",
        help="Number of items in bulk operation",
    )
    parent_action_id = fields.Many2one(
        "dojo.ai.action.log",
        string="Parent Action",
        help="Parent action for bulk sub-operations",
    )
    child_action_ids = fields.One2many(
        "dojo.ai.action.log",
        "parent_action_id",
        string="Child Actions",
    )

    # ─── Undo Tracking ────────────────────────────────────────────────────────
    is_undoable = fields.Boolean(
        string="Undoable",
        default=False,
    )
    undone = fields.Boolean(
        string="Undone",
        default=False,
    )
    undone_at = fields.Datetime(
        string="Undone At",
    )
    undo_snapshot_ids = fields.One2many(
        "dojo.ai.undo.snapshot",
        "action_log_id",
        string="Undo Snapshots",
    )

    # ─── Session Key Generator ────────────────────────────────────────────────
    @api.model
    def _generate_session_key(self):
        """Generate a unique session key."""
        return f"ai-{uuid.uuid4().hex[:12]}"

    # ─── Logging Helpers ──────────────────────────────────────────────────────
    @api.model
    def log_parse(
        self,
        input_text,
        role,
        intent_type,
        parsed_intent,
        confidence,
        resolved_data=None,
        confirmation_prompt=None,
        requires_confirmation=True,
        input_type="text",
        audio_attachment_id=None,
    ):
        """
        Create a new action log entry for a parsed intent.
        
        Returns:
            dojo.ai.action.log record
        """
        vals = {
            "input_text": input_text,
            "role": role,
            "intent_type": intent_type,
            "parsed_intent": json.dumps(parsed_intent) if parsed_intent else None,
            "confidence": confidence,
            "resolved_data": json.dumps(resolved_data) if resolved_data else None,
            "confirmation_prompt": confirmation_prompt,
            "requires_confirmation": requires_confirmation,
            "input_type": input_type,
            "audio_attachment_id": audio_attachment_id,
            "confirmation_status": "pending" if requires_confirmation else "auto",
        }
        return self.create(vals)

    def log_confirmation(self, confirmed, confirmed_by_id=None):
        """Record confirmation or rejection of the action."""
        self.ensure_one()
        self.write({
            "confirmation_status": "confirmed" if confirmed else "rejected",
            "confirmed_by": confirmed_by_id or self.env.user.id,
            "confirmed_at": fields.Datetime.now(),
        })

    def log_execution(self, success, result=None, error=None, execution_time_ms=None, is_undoable=False):
        """Record execution result."""
        self.ensure_one()
        self.write({
            "execution_status": "success" if success else "error",
            "execution_result": json.dumps(result) if result else None,
            "error_message": error,
            "execution_time_ms": execution_time_ms,
            "is_undoable": is_undoable,
        })

    def log_undo(self, undone_by_id=None):
        """Mark this action as undone."""
        self.ensure_one()
        self.write({
            "undone": True,
            "undone_at": fields.Datetime.now(),
        })

    # ─── Lookup Methods ───────────────────────────────────────────────────────
    @api.model
    def find_by_session_key(self, session_key):
        """Find action log by session key."""
        return self.search([("session_key", "=", session_key)], limit=1)

    @api.model
    def get_last_undoable(self, user_id=None, minutes=60):
        """Get the most recent undoable action for a user."""
        domain = [
            ("is_undoable", "=", True),
            ("undone", "=", False),
            ("execution_status", "=", "success"),
            ("timestamp", ">=", fields.Datetime.now() - timedelta(minutes=minutes)),
        ]
        if user_id:
            domain.append(("user_id", "=", user_id))
        
        return self.search(domain, order="timestamp desc", limit=1)

    # ─── Cleanup Cron ─────────────────────────────────────────────────────────
    @api.model
    def _cron_cleanup_old_logs(self, days=90):
        """Delete action logs older than specified days."""
        cutoff = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search([("timestamp", "<", cutoff)])
        count = len(old_logs)
        old_logs.unlink()
        _logger.info("AI Action Log cleanup: deleted %d logs older than %d days", count, days)
        return count

    # ─── Analytics Helpers ────────────────────────────────────────────────────
    @api.model
    def get_intent_statistics(self, days=30):
        """Get intent usage statistics for the last N days."""
        cutoff = fields.Datetime.now() - timedelta(days=days)
        logs = self.search([("timestamp", ">=", cutoff)])
        
        stats = {}
        for log in logs:
            intent = log.intent_type or "unknown"
            if intent not in stats:
                stats[intent] = {
                    "count": 0,
                    "success": 0,
                    "error": 0,
                    "avg_confidence": 0,
                    "total_confidence": 0,
                }
            stats[intent]["count"] += 1
            stats[intent]["total_confidence"] += log.confidence or 0
            if log.execution_status == "success":
                stats[intent]["success"] += 1
            elif log.execution_status == "error":
                stats[intent]["error"] += 1
        
        # Calculate averages
        for intent in stats:
            if stats[intent]["count"] > 0:
                stats[intent]["avg_confidence"] = (
                    stats[intent]["total_confidence"] / stats[intent]["count"]
                )
            del stats[intent]["total_confidence"]
        
        return stats

    # ─── UI Actions ───────────────────────────────────────────────────────────
    def action_view_undo_snapshots(self):
        """Open the undo snapshots for this action."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Undo Snapshots",
            "res_model": "dojo.ai.undo.snapshot",
            "view_mode": "list,form",
            "domain": [("action_log_id", "=", self.id)],
            "context": {"default_action_log_id": self.id},
        }
