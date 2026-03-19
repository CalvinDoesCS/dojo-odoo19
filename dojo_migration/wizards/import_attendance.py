"""
Attendance History import wizard.

Expected CSV columns (case-insensitive after strip):
  member_email*   — matches dojo.member by email (required)
  class_date*     — YYYY-MM-DD or MM/DD/YYYY (required)
  class_name      — used to match/create a dojo.class.template (default: 'Imported Class')
  program_name    — links class template to dojo.program (optional)
  status          — present | late | absent | excused (default: present)
  class_time      — HH:MM 24-hour (default: 09:00); used for placeholder session start time

Session matching logic:
  1. Try to find an existing dojo.class.session whose start_datetime date == class_date
     AND template.name matches class_name (case-insensitive).
  2. If not found, find or create a dojo.class.template with that name, then create a
     placeholder dojo.class.session (is_import_placeholder=True, state='done').

Dedup: skips if dojo.attendance.log exists for (member, session).
"""
import base64
import csv
import io
import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUIRED_COLS = {"member_email", "class_date"}
DEFAULT_CLASS_NAME = "Imported Class"
DEFAULT_CLASS_TIME = "09:00"

TEMPLATE_ROWS = [
    ["member_email", "class_date", "class_name", "program_name", "status", "class_time"],
    ["john.doe@example.com", "2024-02-05", "BJJ Adult", "Brazilian Jiu-Jitsu", "present", "18:00"],
    ["sam.doe@example.com", "2024-02-05", "BJJ Kids", "Brazilian Jiu-Jitsu", "present", "16:00"],
    ["john.doe@example.com", "2024-02-07", "BJJ Adult", "Brazilian Jiu-Jitsu", "absent", "18:00"],
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


def _parse_time(val):
    """Return (hour, minute) tuple; default 9:00."""
    val = (val or DEFAULT_CLASS_TIME).strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            t = datetime.strptime(val, fmt)
            return t.hour, t.minute
        except ValueError:
            pass
    return 9, 0


class DojoMigrationImportAttendance(models.TransientModel):
    _name = "dojo.migration.import.attendance"
    _description = "Import Attendance History from CSV"

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
            "name": "spark_attendance_template.csv",
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

        Member = self.env["dojo.member"]
        ClassTemplate = self.env["dojo.class.template"]
        ClassSession = self.env["dojo.class.session"]
        AttendanceLog = self.env["dojo.attendance.log"]
        Program = self.env["dojo.program"]
        company = self.env.company

        # Cache to avoid repeated DB queries for same template + date combos
        session_cache = {}   # (class_name_lower, class_date_str) → session record
        template_cache = {}  # class_name_lower → template record

        valid_statuses = ("present", "late", "absent", "excused")

        for idx, row in enumerate(rows, start=2):
            raw = json.dumps(row)
            try:
                email = (row.get("member_email") or "").strip().lower()
                class_date = _parse_date(row.get("class_date"))
                class_name = (row.get("class_name") or DEFAULT_CLASS_NAME).strip()

                if not email:
                    raise ValueError("member_email is required.")
                if not class_date:
                    raise ValueError("class_date is required or has an invalid format.")

                member = Member.search([("email", "=", email)], limit=1)
                if not member:
                    raise ValueError(f"No member found with email '{email}'. Import members first.")

                status_raw = (row.get("status") or "present").strip().lower()
                status = status_raw if status_raw in valid_statuses else "present"

                # Resolve session
                cache_key = (class_name.lower(), str(class_date))
                session = session_cache.get(cache_key)

                if not session:
                    # Try to find existing session on this date with this template name
                    date_start = datetime.combine(class_date, datetime.min.time())
                    date_end = date_start + timedelta(days=1)
                    session = ClassSession.search([
                        ("start_datetime", ">=", date_start),
                        ("start_datetime", "<", date_end),
                        ("template_id.name", "=ilike", class_name),
                    ], limit=1)

                if not session:
                    # Find or create template
                    template = template_cache.get(class_name.lower())
                    if not template:
                        template = ClassTemplate.search(
                            [("name", "=ilike", class_name)], limit=1
                        )
                        if not template:
                            # Resolve program
                            program_id = False
                            program_name = (row.get("program_name") or "").strip()
                            if program_name:
                                program = Program.search(
                                    [("name", "=ilike", program_name)], limit=1
                                )
                                if not program:
                                    program = Program.create({"name": program_name})
                                program_id = program.id

                            tpl_vals = {
                                "name": class_name,
                                "company_id": company.id,
                            }
                            if program_id:
                                tpl_vals["program_id"] = program_id
                            template = ClassTemplate.create(tpl_vals)
                        template_cache[class_name.lower()] = template

                    # Create placeholder session
                    hour, minute = _parse_time(row.get("class_time"))
                    start_dt = datetime.combine(
                        class_date, datetime.min.time().replace(hour=hour, minute=minute)
                    )
                    end_dt = start_dt + timedelta(minutes=template.duration_minutes or 60)
                    session = ClassSession.create({
                        "template_id": template.id,
                        "start_datetime": start_dt,
                        "end_datetime": end_dt,
                        "state": "done",
                        "is_import_placeholder": True,
                        "company_id": company.id,
                    })
                    session_cache[cache_key] = session

                # Always cache for future rows with same key
                if cache_key not in session_cache:
                    session_cache[cache_key] = session

                # Dedup check
                existing_log = AttendanceLog.search([
                    ("member_id", "=", member.id),
                    ("session_id", "=", session.id),
                ], limit=1)
                if existing_log:
                    log_lines.append((0, 0, {
                        "row_number": idx, "status": "skip",
                        "message": (
                            f"Attendance for '{email}' in session "
                            f"'{session.display_name}' already exists (id={existing_log.id})"
                        ),
                        "raw_data": raw,
                    }))
                    skip += 1
                    continue

                AttendanceLog.create({
                    "member_id": member.id,
                    "session_id": session.id,
                    "status": status,
                    "checkin_datetime": datetime.combine(class_date, datetime.min.time().replace(
                        hour=_parse_time(row.get("class_time"))[0],
                        minute=_parse_time(row.get("class_time"))[1],
                    )),
                })
                log_lines.append((0, 0, {
                    "row_number": idx, "status": "success",
                    "message": f"Recorded {status} for '{email}' on {class_date} ({class_name})",
                    "raw_data": raw,
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
            "import_type": "attendance",
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
