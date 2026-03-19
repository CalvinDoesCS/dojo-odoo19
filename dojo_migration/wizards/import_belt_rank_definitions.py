"""
Belt Rank Definitions import wizard.

Expected CSV columns (case-insensitive after strip):
  name*         — dojo.belt.rank name (required)
  sequence      — sort order integer (default 10)
  dan_level     — dan degree integer (default 0)
  is_dan        — TRUE/FALSE boolean (default False)
  max_stripes   — integer (default 4)
  active        — TRUE/FALSE boolean (default True)

Dedup: skips ranks whose name already exists (case-insensitive).
"""
import base64
import csv
import io
import json
import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUIRED_COLS = {"name"}

TEMPLATE_ROWS = [
    ["name", "sequence", "dan_level", "is_dan", "max_stripes", "active"],
    ["White Belt", "1", "0", "FALSE", "4", "TRUE"],
    ["Yellow Belt", "2", "0", "FALSE", "4", "TRUE"],
    ["1st Degree Black Belt", "13", "1", "TRUE", "0", "TRUE"],
]


def _parse_bool(val, default=False):
    if not val:
        return default
    return val.strip().upper() in ("TRUE", "1", "YES", "T")


def _parse_int(val, default=0):
    try:
        return int(val.strip()) if val and val.strip() else default
    except (ValueError, AttributeError):
        return default


class DojoMigrationImportBeltRankDefinitions(models.TransientModel):
    _name = "dojo.migration.import.belt.rank.defs"
    _description = "Import Belt Rank Definitions from CSV"

    state = fields.Selection(
        [("upload", "Upload"), ("preview", "Preview"), ("done", "Done")],
        default="upload",
    )
    csv_file = fields.Binary(string="CSV File", required=True)
    filename = fields.Char()
    preview_html = fields.Html(string="Preview (first 5 rows)", readonly=True)
    log_id = fields.Many2one("dojo.migration.log", string="Import Log", readonly=True)

    # ── Template download ─────────────────────────────────────────────────

    def action_download_template(self):
        output = io.StringIO()
        writer = csv.writer(output)
        for row in TEMPLATE_ROWS:
            writer.writerow(row)
        data = base64.b64encode(output.getvalue().encode("utf-8"))
        attachment = self.env["ir.attachment"].create({
            "name": "belt_rank_definitions_template.csv",
            "datas": data,
            "mimetype": "text/csv",
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    # ── Preview ───────────────────────────────────────────────────────────

    def action_preview(self):
        self.ensure_one()
        rows, _ = self._parse_csv()
        self.preview_html = self._rows_to_html(rows[:5])
        self.state = "preview"
        return self._reopen()

    # ── Import ────────────────────────────────────────────────────────────

    def action_import(self):
        self.ensure_one()
        rows, header = self._parse_csv()
        missing = REQUIRED_COLS - set(header)
        if missing:
            raise UserError(f"Missing required columns: {', '.join(sorted(missing))}")

        log_lines = []
        success = skip = error = 0

        BeltRank = self.env["dojo.belt.rank"]

        for idx, row in enumerate(rows, start=2):  # row 1 = header
            raw = json.dumps(row)
            name = (row.get("name") or "").strip()
            if not name:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "error",
                    "message": "Missing required field: name", "raw_data": raw,
                }))
                error += 1
                continue

            existing = BeltRank.search([("name", "=ilike", name)], limit=1)
            if existing:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "skip",
                    "message": f"Belt rank '{name}' already exists (id={existing.id})",
                    "raw_data": raw,
                }))
                skip += 1
                continue

            try:
                vals = {
                    "name": name,
                    "sequence": _parse_int(row.get("sequence"), default=10),
                    "dan_level": _parse_int(row.get("dan_level"), default=0),
                    "is_dan": _parse_bool(row.get("is_dan"), default=False),
                    "max_stripes": _parse_int(row.get("max_stripes"), default=4),
                    "active": _parse_bool(row.get("active"), default=True),
                }
                BeltRank.create(vals)
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "success",
                    "message": f"Created belt rank '{name}'", "raw_data": raw,
                }))
                success += 1
            except Exception as exc:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "error",
                    "message": str(exc), "raw_data": raw,
                }))
                error += 1

        state = "done" if error == 0 else ("partial" if success + skip > 0 else "failed")
        log = self.env["dojo.migration.log"].create({
            "import_type": "belt_rank_defs",
            "filename": self.filename or "unknown.csv",
            "state": state,
            "date": fields.Datetime.now(),
            "total_rows": len(rows),
            "success_count": success,
            "skip_count": skip,
            "error_count": error,
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
        reader = csv.DictReader(io.StringIO(raw))
        header = [h.strip().lower() for h in (reader.fieldnames or [])]
        rows = []
        for row in reader:
            rows.append({k.strip().lower(): v for k, v in row.items()})
        return rows, header

    def _rows_to_html(self, rows):
        if not rows:
            return "<p>No data</p>"
        cols = list(rows[0].keys())
        th = "".join(f"<th>{c}</th>" for c in cols)
        body = ""
        for row in rows:
            tds = "".join(f"<td>{row.get(c, '')}</td>" for c in cols)
            body += f"<tr>{tds}</tr>"
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
