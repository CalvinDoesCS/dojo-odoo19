# -*- coding: utf-8 -*-
"""
Dojo AI Intent Schema — Defines available AI assistant intents and their configuration.

Each intent specifies:
- Parameter schema (JSON) for validation
- Role permissions (who can execute)
- Confirmation requirements
- Example phrases for LLM context
"""

import json
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class DojoAiIntentSchema(models.Model):
    _name = "dojo.ai.intent.schema"
    _description = "AI Intent Schema"
    _order = "sequence, intent_type"
    _rec_name = "name"

    # ─── Identification ───────────────────────────────────────────────────────
    intent_type = fields.Char(
        string="Intent Type",
        required=True,
        index=True,
        help="Unique identifier for this intent (e.g., member_lookup, class_enroll)",
    )
    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
        help="Human-readable name for this intent",
    )
    description = fields.Text(
        string="Description",
        translate=True,
        help="Detailed description of what this intent does",
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
    )
    active = fields.Boolean(
        string="Active",
        default=True,
    )
    category = fields.Selection(
        [
            ("read", "Read-Only"),
            ("member", "Member/Student"),
            ("class", "Class/Session"),
            ("enrollment", "Enrollment"),
            ("belt", "Belt/Rank"),
            ("attendance", "Attendance"),
            ("subscription", "Subscription/Contract"),
            ("communication", "Communication"),
            ("system", "System"),
        ],
        string="Category",
        default="system",
        index=True,
    )

    # ─── Parameters ───────────────────────────────────────────────────────────
    parameters_schema = fields.Text(
        string="Parameters Schema (JSON)",
        help="JSON Schema defining expected parameters for this intent",
    )
    example_phrases = fields.Text(
        string="Example Phrases",
        help="Example natural language phrases that trigger this intent (one per line)",
    )

    # ─── Permissions ──────────────────────────────────────────────────────────
    allowed_roles = fields.Char(
        string="Allowed Roles",
        default="instructor,admin",
        help="Comma-separated list of roles that can execute this intent (kiosk,instructor,admin)",
    )

    # ─── Confirmation ─────────────────────────────────────────────────────────
    requires_confirmation = fields.Boolean(
        string="Requires Confirmation",
        default=True,
        help="If False, intent executes immediately without user confirmation (for read-only operations)",
    )
    confirmation_template = fields.Char(
        string="Confirmation Template",
        help="Template for confirmation prompt. Use {field_name} placeholders.",
    )

    # ─── Undo Configuration ───────────────────────────────────────────────────
    is_undoable = fields.Boolean(
        string="Undoable",
        default=False,
        help="Whether actions from this intent can be undone",
    )
    undo_handler = fields.Char(
        string="Undo Handler",
        help="Method name in ai.assistant.service for undoing this intent",
    )

    # ─── Bulk Support ─────────────────────────────────────────────────────────
    supports_bulk = fields.Boolean(
        string="Supports Bulk",
        default=False,
        help="Whether this intent can operate on multiple records",
    )
    bulk_intent_type = fields.Char(
        string="Bulk Intent Type",
        help="Intent type for bulk version (e.g., class_enroll → class_enroll_bulk)",
    )
    max_bulk_size = fields.Integer(
        string="Max Bulk Size",
        default=50,
        help="Maximum number of items in a single bulk operation",
    )

    # ─── Constraints ──────────────────────────────────────────────────────────
    _sql_constraints = [
        (
            "intent_type_unique",
            "UNIQUE(intent_type)",
            "Intent type must be unique!",
        ),
    ]

    @api.constrains("parameters_schema")
    def _check_parameters_schema(self):
        """Validate that parameters_schema is valid JSON."""
        for rec in self:
            if rec.parameters_schema:
                try:
                    json.loads(rec.parameters_schema)
                except json.JSONDecodeError as e:
                    raise ValidationError(f"Invalid JSON in parameters schema: {e}")

    # ─── Helpers ──────────────────────────────────────────────────────────────
    def get_parameters_schema_dict(self):
        """Return parameters schema as a Python dict."""
        self.ensure_one()
        if self.parameters_schema:
            try:
                return json.loads(self.parameters_schema)
            except json.JSONDecodeError:
                return {}
        return {}

    def get_example_phrases_list(self):
        """Return example phrases as a list."""
        self.ensure_one()
        if self.example_phrases:
            return [p.strip() for p in self.example_phrases.strip().split("\n") if p.strip()]
        return []

    def check_role_permission(self, role):
        """Check if the given role is allowed to execute this intent."""
        self.ensure_one()
        
        if not self.allowed_roles:
            return False
        
        allowed = [r.strip().lower() for r in self.allowed_roles.split(",")]
        return role.lower() in allowed

    def format_confirmation_prompt(self, intent_data=None, resolved_data=None):
        """Format confirmation template with resolved data."""
        self.ensure_one()
        
        if not self.confirmation_template:
            return f"Execute {self.name}?"
        
        # Merge data sources for placeholder replacement
        data = {}
        if intent_data and isinstance(intent_data, dict):
            data.update(intent_data.get("parameters", {}))
        if resolved_data and isinstance(resolved_data, dict):
            data.update(resolved_data)
        
        try:
            return self.confirmation_template.format(**data)
        except KeyError as e:
            _logger.warning("Missing key in confirmation template: %s", e)
            return self.confirmation_template

    # ─── Lookup Methods ───────────────────────────────────────────────────────
    @api.model
    def get_by_type(self, intent_type):
        """Get intent schema by type."""
        return self.search([("intent_type", "=", intent_type), ("active", "=", True)], limit=1)

    @api.model
    def get_all_active(self):
        """Get all active intent schemas."""
        return self.search([("active", "=", True)])

    @api.model
    def get_for_role(self, role):
        """Get all intents accessible by a specific role."""
        all_intents = self.get_all_active()
        return all_intents.filtered(lambda i: i.check_role_permission(role))

    @api.model
    def get_intent_definitions_for_llm(self, role=None):
        """
        Get intent definitions formatted for LLM system prompt.
        
        Returns a list of dicts with intent info for structured output parsing.
        """
        intents = self.get_for_role(role) if role else self.get_all_active()
        
        definitions = []
        for intent in intents:
            definitions.append({
                "intent_type": intent.intent_type,
                "name": intent.name,
                "description": intent.description or "",
                "parameters": intent.get_parameters_schema_dict(),
                "examples": intent.get_example_phrases_list(),
                "requires_confirmation": intent.requires_confirmation,
            })
        
        return definitions

    # ─── Action: Test Intent Parsing ──────────────────────────────────────────
    def action_test_intent(self):
        """Open wizard to test intent parsing (dry-run mode)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Test Intent: {self.name}",
            "res_model": "dojo.ai.test.intent.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_intent_schema_id": self.id,
            },
        }
