"""
Belt Rank History import wizard.

Expected CSV columns (case-insensitive after strip):
  member_email*     — matches dojo.member by email (required)
  rank_name*        — dojo.belt.rank name; auto-created if not found (required)
  program_name      — links rank to dojo.program; auto-creates program if missing
  date_awarded*     — YYYY-MM-DD or MM/DD/YYYY (required)
  awarded_by_name   — matches dojo.instructor.profile by name (optional)

Dedup: skips if dojo.member.rank exists for (member, rank, date_awarded).
After all rows are inserted the wizard triggers a recompute of current_rank_id
on every affected member.
"""
import base64
import csv
import io
import json
import logging
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUIRED_COLS = {"member_email", "rank_name", "date_awarded"}

TEMPLATE_ROWS = [
    ["member_email", "rank_name", "program_name", "date_awarded", "awarded_by_name"],
    ["john.doe@example.com", "White Belt", "Brazilian Jiu-Jitsu", "2020-01-15", "Sensei Mike"],
    ["john.doe@example.com", "Blue Belt", "Brazilian Jiu-Jitsu", "2022-06-10", "Sensei Mike"],
    ["sam.doe@example.com", "White Belt", "Brazilian Jiu-Jitsu", "2021-03-20", ""],
]


def _parse_date(val):
    if not val:
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    return None


class DojoMigrationImportRanks(models.TransientModel):
    _name = "dojo.migration.import.ranks"
    _description = "Import Belt Rank History from CSV"

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
            "name": "spark_ranks_template.csv",
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
        affected_members = set()

        Member = self.env["dojo.member"]
        Rank = self.env["dojo.belt.rank"]
        Program = self.env["dojo.program"]
        MemberRank = self.env["dojo.member.rank"]
        InstructorProfile = self.env["dojo.instructor.profile"]

        # Track auto-created belt ranks by name for sequence assignment
        max_seq = Rank.search([], order="sequence desc", limit=1)
        next_seq = (max_seq.sequence + 10) if max_seq else 10

        for idx, row in enumerate(rows, start=2):
            raw = json.dumps(row)
            try:
                email = (row.get("member_email") or "").strip().lower()
                rank_name = (row.get("rank_name") or "").strip()
                date_awarded = _parse_date(row.get("date_awarded"))

                if not email:
                    raise ValueError("member_email is required.")
                if not rank_name:
                    raise ValueError("rank_name is required.")
                if not date_awarded:
                    raise ValueError("date_awarded is required or has an invalid format.")

                member = Member.search([("email", "=", email)], limit=1)
                if not member:
                    raise ValueError(f"No member found with email '{email}'. Import members first.")

                # Resolve or create belt rank
                rank = Rank.search([("name", "=ilike", rank_name)], limit=1)
                if not rank:
                    rank = Rank.create({"name": rank_name, "sequence": next_seq})
                    next_seq += 10

                # Resolve program (optional)
                program_id = False
                program_name = (row.get("program_name") or "").strip()
                if program_name:
                    program = Program.search([("name", "=ilike", program_name)], limit=1)
                    if not program:
                        program = Program.create({"name": program_name})
                    program_id = program.id

                # Instructor (optional)
                instructor_id = False
                awarded_by = (row.get("awarded_by_name") or "").strip()
                if awarded_by:
                    instructor = InstructorProfile.search(
                        [("name", "=ilike", awarded_by)], limit=1
                    )
                    if instructor:
                        instructor_id = instructor.id

                # Dedup check
                existing = MemberRank.search([
                    ("member_id", "=", member.id),
                    ("rank_id", "=", rank.id),
                    ("date_awarded", "=", date_awarded),
                ], limit=1)
                if existing:
                    log_lines.append((0, 0, {
                        "row_number": idx, "status": "skip",
                        "message": (
                            f"Rank '{rank_name}' for '{email}' on {date_awarded} "
                            f"already exists (id={existing.id})"
                        ),
                        "raw_data": raw,
                    }))
                    skip += 1
                    continue

                rank_vals = {
                    "member_id": member.id,
                    "rank_id": rank.id,
                    "date_awarded": date_awarded,
                }
                if program_id:
                    rank_vals["program_id"] = program_id
                if instructor_id:
                    rank_vals["awarded_by"] = instructor_id

                MemberRank.create(rank_vals)
                affected_members.add(member.id)
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "success",
                    "message": f"Awarded '{rank_name}' to '{email}' on {date_awarded}",
                    "raw_data": raw,
                }))
                success += 1

            except Exception as exc:
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "error",
                    "message": str(exc), "raw_data": raw,
                }))
                error += 1

        # Trigger recompute of current_rank_id on affected members
        if affected_members:
            members_to_update = Member.browse(list(affected_members))
            members_to_update._compute_current_rank_id()

        state = "done" if error == 0 else ("partial" if success + skip > 0 else "failed")
        log = self.env["dojo.migration.log"].create({
            "import_type": "ranks",
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
            "target": "new",
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
