"""
Subscriptions import wizard.

Expected CSV columns (case-insensitive after strip):
  member_email*     — matches existing dojo.member by email (required)
  plan_name*        — dojo.subscription.plan name; auto-created if not found
  billing_period    — monthly | weekly | yearly  (default: monthly)
  price             — recurring amount (float, default 0.0)
  initial_fee       — one-time fee (float, default 0.0)
  start_date*       — YYYY-MM-DD or MM/DD/YYYY (required)
  state             — draft | active | paused | cancelled | expired (default: active)
  end_date          — YYYY-MM-DD or MM/DD/YYYY
  next_billing_date — YYYY-MM-DD or MM/DD/YYYY
  program_name      — links plan to dojo.program (auto-creates program if missing)
  billing_reference — SparkMembership subscription ID
  duration          — fixed plan length in months (0 = ongoing, default 0); only
                      applied when a new plan is auto-created

Dedup: skips if a subscription already exists for (member, plan_name, start_date).
Also creates dojo.program.enrollment when state='active'.
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

REQUIRED_COLS = {"member_email", "plan_name", "start_date"}

TEMPLATE_ROWS = [
    [
        "member_email", "plan_name", "billing_period", "price", "initial_fee",
        "start_date", "state", "end_date", "next_billing_date",
        "program_name", "billing_reference", "duration",
    ],
    [
        "john.doe@example.com", "BJJ Adult Monthly", "monthly", "120.00", "50.00",
        "2024-01-01", "active", "", "2026-04-01",
        "Brazilian Jiu-Jitsu", "SPARK-SUB-001", "0",
    ],
    [
        "sam.doe@example.com", "BJJ Kids Monthly", "monthly", "80.00", "0.00",
        "2024-01-01", "active", "", "2026-04-01",
        "Brazilian Jiu-Jitsu", "SPARK-SUB-002", "0",
    ],
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


def _parse_float(val, default=0.0):
    try:
        return float((val or "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return default


class DojoMigrationImportSubscriptions(models.TransientModel):
    _name = "dojo.migration.import.subscriptions"
    _description = "Import Subscriptions from CSV"

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
            "name": "spark_subscriptions_template.csv",
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
        Plan = self.env["dojo.subscription.plan"]
        Program = self.env["dojo.program"]
        Subscription = self.env["dojo.member.subscription"]
        Enrollment = self.env["dojo.program.enrollment"]
        company = self.env.company

        valid_billing = ("monthly", "weekly", "yearly")
        valid_states = ("draft", "active", "paused", "cancelled", "expired")

        for idx, row in enumerate(rows, start=2):
            raw = json.dumps(row)
            try:
                email = (row.get("member_email") or "").strip().lower()
                plan_name = (row.get("plan_name") or "").strip()
                start_date = _parse_date(row.get("start_date"))

                if not email:
                    raise ValueError("member_email is required.")
                if not plan_name:
                    raise ValueError("plan_name is required.")
                if not start_date:
                    raise ValueError("start_date is required or has an invalid format.")

                member = Member.search([("email", "=", email)], limit=1)
                if not member:
                    raise ValueError(f"No member found with email '{email}'. Import members first.")

                # Resolve or create plan
                plan = Plan.search([("name", "=ilike", plan_name)], limit=1)
                if not plan:
                    billing_period = (row.get("billing_period") or "monthly").strip().lower()
                    if billing_period not in valid_billing:
                        billing_period = "monthly"

                    program_name = (row.get("program_name") or "").strip()
                    program = None
                    if program_name:
                        program = Program.search([("name", "=ilike", program_name)], limit=1)
                        if not program:
                            program = Program.create({"name": program_name})

                    # Parse duration (0 = ongoing, i.e. no fixed end date)
                    try:
                        duration = int((row.get("duration") or "0").strip())
                        if duration < 0:
                            duration = 0
                    except (ValueError, TypeError):
                        duration = 0

                    plan_vals = {
                        "name": plan_name,
                        "billing_period": billing_period,
                        "price": _parse_float(row.get("price")),
                        "initial_fee": _parse_float(row.get("initial_fee")),
                        "company_id": company.id,
                        "currency_id": company.currency_id.id,
                        "plan_type": "program",
                        "duration": duration,
                    }
                    if program:
                        plan_vals["program_id"] = program.id
                    plan = Plan.create(plan_vals)

                # Dedup check
                existing = Subscription.search([
                    ("member_id", "=", member.id),
                    ("plan_id", "=", plan.id),
                    ("start_date", "=", start_date),
                ], limit=1)
                if existing:
                    log_lines.append((0, 0, {
                        "row_number": idx, "status": "skip",
                        "message": (
                            f"Subscription for '{email}' plan='{plan_name}' "
                            f"start={start_date} already exists (id={existing.id})"
                        ),
                        "raw_data": raw,
                    }))
                    skip += 1
                    continue

                sub_state = (row.get("state") or "active").strip().lower()
                if sub_state not in valid_states:
                    sub_state = "active"

                sub_vals = {
                    "member_id": member.id,
                    "plan_id": plan.id,
                    "start_date": start_date,
                    "state": sub_state,
                    "company_id": company.id,
                }
                end_date = _parse_date(row.get("end_date"))
                if end_date:
                    sub_vals["end_date"] = end_date

                nbd = _parse_date(row.get("next_billing_date"))
                if nbd:
                    sub_vals["next_billing_date"] = nbd

                billing_ref = (row.get("billing_reference") or "").strip()
                if billing_ref:
                    sub_vals["billing_reference"] = billing_ref

                subscription = Subscription.create(sub_vals)

                # Create program enrollment for active subscriptions
                if sub_state == "active" and plan.program_id:
                    existing_enroll = Enrollment.search([
                        ("member_id", "=", member.id),
                        ("program_id", "=", plan.program_id.id),
                        ("is_active", "=", True),
                    ], limit=1)
                    if not existing_enroll:
                        Enrollment.create({
                            "member_id": member.id,
                            "program_id": plan.program_id.id,
                            "subscription_id": subscription.id,
                            "is_active": True,
                            "enrolled_date": start_date,
                            "company_id": company.id,
                        })

                log_lines.append((0, 0, {
                    "row_number": idx, "status": "success",
                    "message": f"Created subscription for '{email}': {plan_name} from {start_date}",
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
            "import_type": "subscriptions",
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
