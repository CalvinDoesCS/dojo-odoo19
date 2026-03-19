"""
Persistent records that track every CSV import run.
dojo.migration.log       — one record per import batch
dojo.migration.log.line  — one row per CSV row processed
"""
import csv
import io
import base64
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DojoMigrationLog(models.Model):
    _name = "dojo.migration.log"
    _description = "Migration Import Log"
    _order = "create_date desc"

    name = fields.Char(string="Reference", readonly=True, copy=False)
    import_type = fields.Selection(
        [
            ("programs", "Programs & Styles"),
            ("belt_rank_defs", "Belt Rank Definitions"),
            ("partners", "Partners"),
            ("households", "Households"),
            ("members", "Members & Households"),
            ("emergency_contacts", "Emergency Contacts"),
            ("subscriptions", "Subscriptions"),
            ("class_templates", "Class Templates"),
            ("subscription_plans", "Subscription Plans"),
            ("member_subscriptions", "Member Subscriptions"),
            ("ranks", "Belt Ranks"),
            ("member_stripe_update", "Member Stripe Update"),
            ("attendance", "Attendance"),
        ],
        string="Import Type",
        required=True,
        readonly=True,
    )
    filename = fields.Char(string="Source File", readonly=True)
    state = fields.Selection(
        [
            ("done", "Done"),
            ("partial", "Partial (some errors)"),
            ("failed", "Failed"),
        ],
        string="Result",
        readonly=True,
    )
    date = fields.Datetime(string="Imported On", readonly=True)
    total_rows = fields.Integer(string="Total Rows", readonly=True)
    success_count = fields.Integer(string="Imported", readonly=True)
    skip_count = fields.Integer(string="Skipped (duplicate)", readonly=True)
    error_count = fields.Integer(string="Errors", readonly=True)
    log_line_ids = fields.One2many(
        "dojo.migration.log.line", "log_id", string="Row Log"
    )
    error_report = fields.Binary(string="Error Report (CSV)", readonly=True)
    error_report_filename = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("name"):
                vals["name"] = seq.next_by_code("dojo.migration.log") or "MIG-NEW"
        return super().create(vals_list)

    # ── Error report download ─────────────────────────────────────────────

    def action_download_error_report(self):
        """Generate and return a CSV of all skip/error lines."""
        self.ensure_one()
        error_lines = self.log_line_ids.filtered(
            lambda l: l.status in ("skip", "error")
        )
        if not error_lines:
            return {"type": "ir.actions.act_window_close"}

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["row_number", "status", "message", "raw_data"])
        for line in error_lines:
            writer.writerow([line.row_number, line.status, line.message, line.raw_data])

        csv_bytes = output.getvalue().encode("utf-8")
        self.error_report = base64.b64encode(csv_bytes)
        self.error_report_filename = f"errors_{self.name}.csv"

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/dojo.migration.log/{self.id}/error_report/{self.error_report_filename}?download=true",
            "target": "self",
        }


class DojoMigrationLogLine(models.Model):
    _name = "dojo.migration.log.line"
    _description = "Migration Log Line"
    _order = "row_number asc"

    log_id = fields.Many2one(
        "dojo.migration.log", required=True, ondelete="cascade", index=True
    )
    row_number = fields.Integer(string="Row #", readonly=True)
    status = fields.Selection(
        [
            ("success", "Imported"),
            ("skip", "Skipped"),
            ("error", "Error"),
        ],
        readonly=True,
    )
    message = fields.Text(string="Message", readonly=True)
    raw_data = fields.Text(string="Raw Row (JSON)", readonly=True)
