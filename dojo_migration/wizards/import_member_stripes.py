"""
Member Stripe Update import wizard.

Handles 09_dojo_member_stripe_update.csv:
  id                  — __import__.* external ID of dojo.member
  current_stripe_count — target stripe count (integer)

Since dojo.member.current_stripe_count is a computed field (derived from
dojo.member.rank.stripe_count), this wizard updates the stripe_count on
the member's most recent dojo.member.rank record instead.

If the member has no rank history, the row is skipped with a warning.
"""
import base64
import csv
import io
import json
import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoMigrationImportMemberStripes(models.TransientModel):
    _name = "dojo.migration.import.member.stripes"
    _description = "Import Member Stripe Counts (CSV)"

    state = fields.Selection(
        [("upload", "Upload"), ("preview", "Preview"), ("done", "Done")],
        default="upload",
    )
    csv_file = fields.Binary(string="CSV File", required=True)
    filename = fields.Char()
    preview_html = fields.Html(string="Preview (first 5 rows)", readonly=True)
    log_id = fields.Many2one("dojo.migration.log", string="Import Log", readonly=True)

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

        if "id" not in header or "current_stripe_count" not in header:
            raise UserError(
                "CSV must have columns: id, current_stripe_count"
            )

        log_lines = []
        success = skip = error = 0
        IrModelData = self.env["ir.model.data"]
        MemberRank = self.env["dojo.member.rank"]

        for idx, row in enumerate(rows, start=2):
            raw = json.dumps(row)
            ext_id = (row.get("id") or "").strip()
            stripe_str = (row.get("current_stripe_count") or "0").strip()

            if not ext_id:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "error",
                    "message": "Missing 'id' value.", "raw_data": raw,
                }))
                error += 1
                continue

            try:
                stripe_count = int(stripe_str)
            except ValueError:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "error",
                    "message": f"Invalid stripe count '{stripe_str}' — must be an integer.",
                    "raw_data": raw,
                }))
                error += 1
                continue

            # Resolve external ID → dojo.member
            # External IDs are stored as "module.name" in ir.model.data
            if "." in ext_id:
                module, name = ext_id.split(".", 1)
            else:
                module, name = "__import__", ext_id

            imd = IrModelData.search([
                ("module", "=", module),
                ("name", "=", name),
                ("model", "=", "dojo.member"),
            ], limit=1)

            if not imd:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "error",
                    "message": f"No dojo.member found for external ID '{ext_id}'.",
                    "raw_data": raw,
                }))
                error += 1
                continue

            member = self.env["dojo.member"].browse(imd.res_id)
            if not member.exists():
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "error",
                    "message": f"Member record (id={imd.res_id}) no longer exists.",
                    "raw_data": raw,
                }))
                error += 1
                continue

            # Find the latest rank record for this member
            latest_rank = MemberRank.search(
                [("member_id", "=", member.id)],
                order="date_awarded desc, id desc",
                limit=1,
            )

            if not latest_rank:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "skip",
                    "message": f"Member '{member.name}' has no rank history — stripe update skipped.",
                    "raw_data": raw,
                }))
                skip += 1
                continue

            latest_rank.stripe_count = stripe_count
            log_lines.append((0, 0, {
                "row_number": idx, "status": "success",
                "message": (
                    f"Set stripe_count={stripe_count} on rank record "
                    f"'{latest_rank.rank_id.name}' for member '{member.name}'."
                ),
                "raw_data": raw,
            }))
            success += 1

        state = "done" if error == 0 else ("partial" if success + skip > 0 else "failed")
        log = self.env["dojo.migration.log"].create({
            "import_type": "member_stripe_update",
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
        rows = [{k.strip().lower(): v for k, v in row.items()} for row in reader]
        return rows, header

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
