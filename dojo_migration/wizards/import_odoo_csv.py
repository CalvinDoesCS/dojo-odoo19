"""
Universal Odoo-format CSV import wizard.

Handles CSVs that follow Odoo's native import format:
  - 'id' column with __import__.* external IDs
  - 'field/id' columns for Many2one by external ID
  - 'field/name' columns for Many2one by name (auto-resolved)
  - Boolean values as TRUE/FALSE strings

Leverages Model.load() internally, which handles all external ID
tracking and creation in ir.model.data automatically.

Covered CSV files (import in order):
  02_res_partner.csv              → model: res.partner
  03_dojo_household.csv           → model: dojo.household
  04_dojo_member.csv              → model: dojo.member
  05_dojo_household_update.csv    → model: dojo.household
  06_dojo_guardian_link.csv       → model: dojo.guardian.link
  07_dojo_emergency_contact.csv   → model: dojo.emergency.contact
  08_dojo_member_rank.csv         → model: dojo.member.rank
  10_dojo_program.csv             → model: dojo.program
  10_dojo_subscription_plan.csv   → model: dojo.subscription.plan
  11_dojo_class_template.csv      → model: dojo.class.template
  12_dojo_subscription_plan.csv   → model: dojo.subscription.plan
                                     (remap: template_ids → allowed_template_ids)
  13_dojo_member_subscription.csv → model: dojo.member.subscription
                                     (skip: program_id — readonly related field)
"""
import base64
import csv
import io
import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MODEL_CHOICES = [
    ("res.partner", "02. Partners (res.partner)"),
    ("dojo.household", "03 / 05. Households (dojo.household)"),
    ("dojo.member", "04. Members (dojo.member)"),
    ("dojo.guardian.link", "06. Guardian Links (dojo.guardian.link)"),
    ("dojo.emergency.contact", "07. Emergency Contacts (dojo.emergency.contact)"),
    ("dojo.member.rank", "08. Member Belt Ranks (dojo.member.rank)"),
    ("dojo.program", "10. Programs (dojo.program)"),
    ("dojo.class.template", "11. Class Templates (dojo.class.template)"),
    ("dojo.subscription.plan", "12. Subscription Plans (dojo.subscription.plan)"),
    ("dojo.member.subscription", "13. Member Subscriptions (dojo.member.subscription)"),
]

# Map model name → migration log import_type
MODEL_IMPORT_TYPE = {
    "res.partner":              "partners",
    "dojo.household":           "households",
    "dojo.member":              "members",
    "dojo.guardian.link":       "guardian_links",
    "dojo.emergency.contact":   "emergency_contacts",
    "dojo.member.rank":         "ranks",
    "dojo.program":             "programs",
    "dojo.class.template":      "class_templates",
    "dojo.subscription.plan":   "subscription_plans",
    "dojo.member.subscription": "member_subscriptions",
}

# Remap CSV column prefixes → actual Odoo field names (per model)
MODEL_FIELD_REMAP = {
    # CSV 12 uses 'template_ids/id' but the field is 'allowed_template_ids'
    "dojo.subscription.plan": {
        "template_ids": "allowed_template_ids",
    },
}

# CSV columns to drop before import (readonly/computed fields)
MODEL_SKIP_COLUMNS = {
    # 'program_id' on dojo.member.subscription is a readonly related field
    "dojo.member.subscription": {"program_id"},
    # 'current_rank_id' on dojo.member is a stored computed field (recomputes
    # automatically after belt rank history is imported in step 08)
    "dojo.member": {"current_rank_id"},
}

# Per-model, per-field value substitutions applied before load()
# Format: { model_name: { field_name: { old_value: new_value } } }
MODEL_VALUE_MAP = {
    # CSV uses 'recurring' (billing concept) as plan_type, but the field only
    # accepts 'program' or 'course'.  Plans in the CSV each have a program_id
    # set, so 'program' is the correct value.
    "dojo.subscription.plan": {
        "plan_type": {"recurring": "program"},
    },
}


class DojoMigrationImportOdooCsv(models.TransientModel):
    _name = "dojo.migration.import.odoo.csv"
    _description = "Universal Odoo-Format CSV Import"

    state = fields.Selection(
        [("upload", "Upload"), ("preview", "Preview"), ("done", "Done")],
        default="upload",
    )
    model_name = fields.Selection(
        MODEL_CHOICES,
        string="Target Model",
        required=True,
    )
    csv_file = fields.Binary(string="CSV File", required=True)
    filename = fields.Char()
    preview_html = fields.Html(string="Preview (first 5 rows)", readonly=True)
    log_id = fields.Many2one("dojo.migration.log", string="Import Log", readonly=True)

    # ── Preview ───────────────────────────────────────────────────────────

    def action_preview(self):
        self.ensure_one()
        headers, data = self._parse_csv()
        # Build preview rows as dicts for HTML rendering
        preview_rows = [dict(zip(headers, row)) for row in data[:5]]
        self.preview_html = self._rows_to_html(preview_rows)
        self.state = "preview"
        return self._reopen()

    # ── Import ────────────────────────────────────────────────────────────

    def action_import(self):
        self.ensure_one()
        if not self.model_name:
            raise UserError("Please select a target model.")

        headers, data = self._parse_csv()
        if not data:
            raise UserError("CSV contains no data rows.")

        # Pre-process: resolve field/name columns to field/.id
        headers, data = self._resolve_name_columns(headers, data)
        # Pre-process: remap column names and drop readonly/computed columns
        headers, data = self._remap_and_skip_columns(headers, data)

        Model = self.env[self.model_name].with_context(
            tracking_disable=True,
            import_compat=True,
        )

        try:
            result = Model.load(headers, data)
        except Exception as exc:
            raise UserError(f"Import failed: {exc}") from exc

        # Handle both dict-style and object-style return (Odoo version compat)
        if isinstance(result, dict):
            ids = result.get("ids") or []
            messages = result.get("messages") or []
        else:
            ids = getattr(result, "ids", []) or []
            messages = getattr(result, "messages", []) or []

        # Count successes, errors, warnings
        errors = [m for m in messages if (m.get("type") if isinstance(m, dict) else getattr(m, "type", "")) == "error"]
        warnings = [m for m in messages if (m.get("type") if isinstance(m, dict) else getattr(m, "type", "")) in ("warning", "info")]

        success = len(ids)
        error_count = len(errors)

        log_lines = []
        for m in messages:
            if isinstance(m, dict):
                msg_type = m.get("type", "info")
                msg_text = m.get("message", str(m))
                rows_range = m.get("rows", {})
                row_num = rows_range.get("from", 0) + 2 if isinstance(rows_range, dict) else 0
            else:
                msg_type = getattr(m, "type", "info")
                msg_text = getattr(m, "message", str(m))
                row_num = 0

            status = "error" if msg_type == "error" else ("warning" if msg_type == "warning" else "success")
            log_lines.append((0, 0, {
                "row_number": row_num,
                "status": status,
                "message": msg_text,
                "raw_data": "",
            }))

        if not log_lines and success > 0:
            log_lines.append((0, 0, {
                "row_number": 0,
                "status": "success",
                "message": f"Successfully imported {success} record(s) into {self.model_name}.",
                "raw_data": "",
            }))

        if error_count == 0:
            state = "done"
        elif success > 0:
            state = "partial"
        else:
            state = "failed"

        import_type = MODEL_IMPORT_TYPE.get(self.model_name, "members")
        log = self.env["dojo.migration.log"].create({
            "import_type": import_type,
            "filename": self.filename or "unknown.csv",
            "state": state,
            "date": fields.Datetime.now(),
            "total_rows": len(data),
            "success_count": success,
            "skip_count": 0,
            "error_count": error_count,
            "log_line_ids": log_lines,
        })
        self.log_id = log
        self.state = "done"
        return self._open_log(log)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _parse_csv(self):
        if not self.csv_file:
            raise UserError("Please upload a CSV file first.")
        raw = base64.b64decode(self.csv_file).decode("utf-8-sig")
        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)
        if not rows:
            raise UserError("CSV file is empty.")
        headers = [h.strip() for h in rows[0]]
        data = [row for row in rows[1:] if any(cell.strip() for cell in row)]
        return headers, data

    def _resolve_name_columns(self, headers, data):
        """
        Resolve any 'field/subfield' column (where subfield is NOT 'id' or
        '.id') to 'field/.id' by looking up the related record by that
        subfield's value.

        Handles common patterns such as:
          currency_id/name  → search res.currency by name
          country_id/code   → search res.country by code
          state_id/code     → search res.country.state by code
          parent_id/name    → search res.partner by name
          etc.

        Odoo's load() only understands field/id (external ID) and field/.id
        (database ID). Any other field/subfield causes "Can not create
        Many-To-One records indirectly" errors.
        """
        if not self.model_name or self.model_name not in self.env:
            return headers, data

        ModelClass = self.env[self.model_name]
        new_headers = list(headers)
        # col_index → (db_id_header, related_model_name, lookup_field)
        converters = {}

        for i, h in enumerate(headers):
            if "/" not in h:
                continue
            # Split into field name and subfield (only handle single-level)
            parts = h.split("/")
            if len(parts) != 2:
                continue
            field_name, sub_field = parts
            # Already a valid load() format — leave alone
            if sub_field in ("id", ".id"):
                continue
            field_obj = ModelClass._fields.get(field_name)
            if field_obj and field_obj.type == "many2one":
                related_model = field_obj.comodel_name
                converters[i] = (field_name + "/.id", related_model, sub_field)
                new_headers[i] = field_name + "/.id"

        if not converters:
            return headers, data

        # Cache lookups to avoid repeated DB queries for the same value
        lookup_cache = {}  # (model, sub_field, value) → db_id_str

        new_data = []
        for row in data:
            new_row = list(row)
            for col_idx, (new_col, rel_model, sub_field) in converters.items():
                if col_idx >= len(new_row):
                    continue
                raw_val = (new_row[col_idx] or "").strip()
                if not raw_val:
                    new_row[col_idx] = ""
                    continue
                cache_key = (rel_model, sub_field, raw_val)
                if cache_key not in lookup_cache:
                    rec = self.env[rel_model].search(
                        [(sub_field, "=", raw_val)], limit=1
                    )
                    lookup_cache[cache_key] = str(rec.id) if rec else ""
                new_row[col_idx] = lookup_cache[cache_key]
            new_data.append(new_row)

        return new_headers, new_data

    def _remap_and_skip_columns(self, headers, data):
        """
        Apply per-model column renaming (MODEL_FIELD_REMAP), column removal
        (MODEL_SKIP_COLUMNS), and cell-level value substitution (MODEL_VALUE_MAP)
        before passing to Model.load().
        """
        field_remap = MODEL_FIELD_REMAP.get(self.model_name, {})
        skip_fields = MODEL_SKIP_COLUMNS.get(self.model_name, set())
        value_map = MODEL_VALUE_MAP.get(self.model_name, {})
        if not field_remap and not skip_fields and not value_map:
            return headers, data

        keep_indices = []
        new_headers = []
        final_field_names = []  # field prefix after remap, for value substitution
        for i, h in enumerate(headers):
            field_prefix = h.split("/")[0]
            if field_prefix in skip_fields:
                continue
            if field_prefix in field_remap:
                suffix = h[len(field_prefix):]
                new_h = field_remap[field_prefix] + suffix
                final_prefix = field_remap[field_prefix]
            else:
                new_h = h
                final_prefix = field_prefix
            keep_indices.append(i)
            new_headers.append(new_h)
            final_field_names.append(final_prefix)

        new_data = []
        for row in data:
            new_row = [row[i] for i in keep_indices if i < len(row)]
            if value_map:
                for col_idx, field_name in enumerate(final_field_names):
                    if field_name in value_map and col_idx < len(new_row):
                        cell = new_row[col_idx]
                        new_row[col_idx] = value_map[field_name].get(cell, cell)
            new_data.append(new_row)
        return new_headers, new_data

    def _rows_to_html(self, rows):
        if not rows:
            return "<p>No data</p>"
        cols = list(rows[0].keys())
        th = "".join(f"<th>{c}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{row.get(c, '')}</td>" for c in cols) + "</tr>"
            for row in rows
        )
        return (
            f'<table class="table table-sm table-bordered">'
            f"<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
        )

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "main",
        }

    def _open_log(self, log):
        return {
            "type": "ir.actions.act_window",
            "name": "Import Log",
            "res_model": "dojo.migration.log",
            "res_id": log.id,
            "view_mode": "form",
            "target": "current",
        }
