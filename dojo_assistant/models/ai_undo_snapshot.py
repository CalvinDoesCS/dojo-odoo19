# -*- coding: utf-8 -*-
"""
Dojo AI Undo Snapshot — Stores pre-action state for undo capability.

Captures the state of records before AI-initiated modifications,
allowing users to reverse actions within a configurable time window.
"""

import json
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoAiUndoSnapshot(models.Model):
    _name = "dojo.ai.undo.snapshot"
    _description = "AI Undo Snapshot"
    _order = "create_date desc"

    # ─── Core Fields ──────────────────────────────────────────────────────────
    action_log_id = fields.Many2one(
        "dojo.ai.action.log",
        string="Action Log",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # ─── Target Record ────────────────────────────────────────────────────────
    model_name = fields.Char(
        string="Model",
        required=True,
        help="Technical name of the model (e.g., dojo.class.enrollment)",
    )
    record_id = fields.Integer(
        string="Record ID",
        required=True,
        help="ID of the affected record",
    )
    record_display = fields.Char(
        string="Record Display",
        help="Human-readable representation of the record at snapshot time",
    )

    # ─── Operation Type ───────────────────────────────────────────────────────
    operation = fields.Selection(
        [
            ("create", "Create"),
            ("write", "Update"),
            ("unlink", "Delete"),
        ],
        string="Operation",
        required=True,
        help="Type of operation performed on the record",
    )

    # ─── Snapshot Data ────────────────────────────────────────────────────────
    snapshot_data = fields.Text(
        string="Snapshot Data (JSON)",
        help="JSON containing field values before the change",
    )
    changed_fields = fields.Char(
        string="Changed Fields",
        help="Comma-separated list of fields that were modified",
    )

    # ─── Undo State ───────────────────────────────────────────────────────────
    undo_available = fields.Boolean(
        string="Undo Available",
        default=True,
        index=True,
    )
    undo_expires_at = fields.Datetime(
        string="Undo Expires At",
        index=True,
    )
    undo_executed = fields.Boolean(
        string="Undo Executed",
        default=False,
    )
    undo_executed_at = fields.Datetime(
        string="Undo Executed At",
    )
    undone_by = fields.Many2one(
        "res.users",
        string="Undone By",
    )
    undo_error = fields.Text(
        string="Undo Error",
        help="Error message if undo failed",
    )

    # ─── Computed Fields ──────────────────────────────────────────────────────
    time_remaining = fields.Char(
        string="Time Remaining",
        compute="_compute_time_remaining",
    )
    is_expired = fields.Boolean(
        string="Expired",
        compute="_compute_is_expired",
    )

    @api.depends("undo_expires_at")
    def _compute_time_remaining(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.undo_expires_at and rec.undo_available:
                delta = rec.undo_expires_at - now
                if delta.total_seconds() > 0:
                    minutes = int(delta.total_seconds() / 60)
                    rec.time_remaining = f"{minutes} min"
                else:
                    rec.time_remaining = "Expired"
            else:
                rec.time_remaining = "N/A"

    @api.depends("undo_expires_at", "undo_available")
    def _compute_is_expired(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_expired = (
                not rec.undo_available
                or (rec.undo_expires_at and rec.undo_expires_at < now)
            )

    # ─── Model Methods ────────────────────────────────────────────────────────
    @api.model
    def create(self, vals):
        """Set expiration time on creation."""
        if "undo_expires_at" not in vals:
            expiry_minutes = int(
                self.env["ir.config_parameter"].sudo().get_param(
                    "dojo_assistant.undo_expiry_minutes", "60"
                )
            )
            vals["undo_expires_at"] = fields.Datetime.now() + timedelta(minutes=expiry_minutes)

        return super().create(vals)

    # ─── Snapshot Creation Helpers ────────────────────────────────────────────
    @api.model
    def create_snapshot(self, action_log_id, model_name, record_id, operation, snapshot_data=None, changed_fields=None):
        """
        Create an undo snapshot for an action.
        
        Args:
            action_log_id: ID of dojo.ai.action.log record
            model_name: Technical model name (e.g., 'dojo.class.enrollment')
            record_id: ID of the affected record
            operation: 'create', 'write', or 'unlink'
            snapshot_data: Dict of field values before the change (for write/unlink)
            changed_fields: List of field names that were changed
        
        Returns:
            Created snapshot record
        """
        # Get record display name
        record_display = None
        try:
            record = self.env[model_name].browse(record_id)
            if record.exists():
                record_display = record.display_name or str(record_id)
        except Exception:
            record_display = f"{model_name}:{record_id}"

        vals = {
            "action_log_id": action_log_id,
            "model_name": model_name,
            "record_id": record_id,
            "record_display": record_display,
            "operation": operation,
            "snapshot_data": json.dumps(snapshot_data) if snapshot_data else None,
            "changed_fields": ",".join(changed_fields) if changed_fields else None,
        }

        return self.create(vals)

    @api.model
    def snapshot_before_create(self, action_log_id, model_name, record_id):
        """Create snapshot for a newly created record (undo = delete)."""
        return self.create_snapshot(action_log_id, model_name, record_id, "create")

    @api.model
    def snapshot_before_write(self, action_log_id, model_name, record_id, old_vals, changed_fields):
        """Create snapshot before updating a record (undo = restore old values)."""
        return self.create_snapshot(
            action_log_id, model_name, record_id, "write",
            snapshot_data=old_vals, changed_fields=changed_fields
        )

    @api.model
    def snapshot_before_unlink(self, action_log_id, model_name, record_id, full_record_data):
        """Create snapshot before deleting a record (undo = recreate)."""
        return self.create_snapshot(
            action_log_id, model_name, record_id, "unlink",
            snapshot_data=full_record_data
        )

    # ─── Undo Execution ───────────────────────────────────────────────────────
    def execute_undo(self):
        """
        Execute the undo operation for this snapshot.
        
        Returns:
            dict: {success: bool, message: str, record_id: int|None}
        """
        self.ensure_one()

        if self.is_expired:
            return {"success": False, "message": "Undo has expired.", "record_id": None}

        if not self.undo_available:
            return {"success": False, "message": "Undo is no longer available.", "record_id": None}

        try:
            result = self._execute_undo_operation()

            # Mark as undone
            self.write({
                "undo_available": False,
                "undo_executed": True,
                "undo_executed_at": fields.Datetime.now(),
                "undone_by": self.env.user.id,
            })

            # Mark the action log as undone
            if self.action_log_id:
                self.action_log_id.log_undo(self.env.user.id)

            return result

        except Exception as e:
            _logger.exception("Undo failed for snapshot %s", self.id)
            self.write({
                "undo_error": str(e),
            })
            return {"success": False, "message": f"Undo failed: {e}", "record_id": None}

    def _execute_undo_operation(self):
        """Internal method to perform the actual undo operation."""
        self.ensure_one()

        Model = self.env[self.model_name]

        if self.operation == "create":
            # Undo create = delete the record
            record = Model.browse(self.record_id)
            if record.exists():
                record.unlink()
                return {
                    "success": True,
                    "message": f"Deleted {self.record_display}",
                    "record_id": None,
                }
            else:
                return {
                    "success": True,
                    "message": "Record already deleted",
                    "record_id": None,
                }

        elif self.operation == "write":
            # Undo write = restore old values
            record = Model.browse(self.record_id)
            if not record.exists():
                return {
                    "success": False,
                    "message": "Record no longer exists",
                    "record_id": None,
                }

            old_vals = json.loads(self.snapshot_data) if self.snapshot_data else {}
            if old_vals:
                # Filter to only changed fields
                if self.changed_fields:
                    fields_to_restore = self.changed_fields.split(",")
                    old_vals = {k: v for k, v in old_vals.items() if k in fields_to_restore}

                record.write(old_vals)

            return {
                "success": True,
                "message": f"Restored {self.record_display}",
                "record_id": self.record_id,
            }

        elif self.operation == "unlink":
            # Undo unlink = recreate the record
            old_vals = json.loads(self.snapshot_data) if self.snapshot_data else {}
            if not old_vals:
                return {
                    "success": False,
                    "message": "No snapshot data available for recreation",
                    "record_id": None,
                }

            # Remove computed/readonly fields that can't be set
            readonly_fields = {"id", "create_date", "create_uid", "write_date", "write_uid", "__last_update"}
            old_vals = {k: v for k, v in old_vals.items() if k not in readonly_fields}

            new_record = Model.create(old_vals)
            return {
                "success": True,
                "message": f"Recreated {self.record_display}",
                "record_id": new_record.id,
            }

        return {"success": False, "message": f"Unknown operation: {self.operation}", "record_id": None}

    # ─── Cleanup Cron ─────────────────────────────────────────────────────────
    @api.model
    def _cron_cleanup_expired_snapshots(self):
        """Delete expired snapshots and those that have been used."""
        now = fields.Datetime.now()

        # Delete expired snapshots
        expired = self.search([
            "|",
            ("undo_expires_at", "<", now),
            ("undo_executed", "=", True),
        ])

        count = len(expired)
        expired.unlink()

        _logger.info("AI Undo Snapshot cleanup: deleted %d expired/used snapshots", count)
        return count

    # ─── Lookup Methods ───────────────────────────────────────────────────────
    @api.model
    def get_available_for_action(self, action_log_id):
        """Get all available undo snapshots for an action log."""
        return self.search([
            ("action_log_id", "=", action_log_id),
            ("undo_available", "=", True),
            ("undo_expires_at", ">", fields.Datetime.now()),
        ])
