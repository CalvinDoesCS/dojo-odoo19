"""
Members, Households & Emergency Contacts import wizard.

Expected CSV columns (case-insensitive after strip):
  first_name*        — OR use full_name instead
  last_name*         — OR use full_name instead
  full_name          — alternative to first_name + last_name
  email              — primary dedup key
  phone
  mobile
  date_of_birth      — YYYY-MM-DD or MM/DD/YYYY
  role               — student | parent | both  (default: student)
  family_account     — shared value groups members into one dojo.household
  membership_state   — lead | trial | active | paused | cancelled
  member_number      — SparkMembership external ID (stored as billing_reference)
  emergency_contact_name
  emergency_contact_phone
  emergency_contact_relationship
  emergency_contact_email

Dedup key: email (primary); fallback: full_name + date_of_birth → skip if found.
Households are grouped in-memory by family_account before any DB writes.
"""
import base64
import csv
import io
import json
import logging
import re
from datetime import date, datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUIRED_ONE_OF = [{"first_name", "last_name"}, {"full_name"}]

TEMPLATE_ROWS = [
    [
        "first_name", "last_name", "email", "phone", "mobile",
        "date_of_birth", "role", "family_account", "membership_state",
        "member_number",
        "emergency_contact_name", "emergency_contact_phone",
        "emergency_contact_relationship", "emergency_contact_email",
    ],
    [
        "John", "Doe", "john.doe@example.com", "+1-555-0100", "",
        "1990-05-15", "parent", "Doe Family", "active",
        "SPARK-001",
        "Jane Doe", "+1-555-0101", "spouse", "jane.doe@example.com",
    ],
    [
        "Sam", "Doe", "sam.doe@example.com", "", "",
        "2012-08-22", "student", "Doe Family", "active",
        "SPARK-002",
        "", "", "", "",
    ],
]


def _parse_date(val):
    """Accept YYYY-MM-DD or MM/DD/YYYY; return date or None."""
    if not val:
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    return None


class DojoMigrationImportMembers(models.TransientModel):
    _name = "dojo.migration.import.members"
    _description = "Import Members & Households from CSV"

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
            "name": "spark_members_template.csv",
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
        html = self._rows_to_html(rows[:5])
        self.preview_html = html
        self.state = "preview"
        return self._reopen()

    # ── Import ────────────────────────────────────────────────────────────

    def action_import(self):
        self.ensure_one()
        rows, header = self._parse_csv()

        # Validate that name columns exist
        has_full = "full_name" in header
        has_split = "first_name" in header and "last_name" in header
        if not has_full and not has_split:
            raise UserError(
                "CSV must contain either 'full_name' or both 'first_name' and 'last_name'."
            )

        log_lines = []
        success = skip = error = 0

        Member = self.env["dojo.member"]
        Household = self.env["dojo.household"]
        GuardianLink = self.env["dojo.guardian.link"]
        Emergency = self.env["dojo.emergency.contact"]

        # ── Group rows by family_account for household creation ────────────
        # We process households in two passes:
        #   Pass 1: resolve/create all dojo.member records
        #   Pass 2: link members to households (to handle forward references)
        household_map = {}   # family_account_name → dojo.household record
        member_results = {}  # row_index → {"member": record, "row": row_dict}

        for idx, row in enumerate(rows, start=2):
            raw = json.dumps(row)
            try:
                full_name, first, last = self._extract_name(row)
                if not full_name:
                    raise ValueError("Name is required (full_name or first_name + last_name).")

                email = (row.get("email") or "").strip().lower() or None

                # Dedup check
                existing = None
                if email:
                    existing = Member.search([("email", "=", email)], limit=1)
                if not existing and full_name:
                    dob = _parse_date(row.get("date_of_birth"))
                    if dob:
                        existing = Member.search([
                            ("name", "=ilike", full_name),
                            ("date_of_birth", "=", dob),
                        ], limit=1)

                if existing:
                    log_lines.append((0, 0, {
                        "row_number": idx,
                        "status": "skip",
                        "message": f"Member '{full_name}' already exists (id={existing.id})",
                        "raw_data": raw,
                    }))
                    skip += 1
                    member_results[idx] = {"member": existing, "row": row, "skipped": True}
                    continue

                # Determine role
                role_raw = (row.get("role") or "student").strip().lower()
                role = role_raw if role_raw in ("student", "parent", "both") else "student"

                # Membership state
                ms_raw = (row.get("membership_state") or "").strip().lower()
                valid_states = ("lead", "trial", "active", "paused", "cancelled")
                membership_state = ms_raw if ms_raw in valid_states else "lead"

                partner_vals = {"name": full_name}
                if email:
                    partner_vals["email"] = email
                phone = (row.get("phone") or "").strip()
                mobile = (row.get("mobile") or "").strip()
                if phone:
                    partner_vals["phone"] = phone
                if mobile:
                    partner_vals["mobile"] = mobile

                member_vals = {
                    "role": role,
                    "membership_state": membership_state,
                }
                dob = _parse_date(row.get("date_of_birth"))
                if dob:
                    member_vals["date_of_birth"] = dob

                member = Member.create({**partner_vals, **member_vals})

                # Store billing_reference (member_number from Spark)
                member_num = (row.get("member_number") or "").strip()
                if member_num:
                    # billing_reference lives on dojo.member.subscription; we store it
                    # as an external ref note on the member for reference during sub import.
                    # We add it to the member's comment field for traceability.
                    member.comment = f"SparkMembership ID: {member_num}"

                # Emergency contact
                ec_name = (row.get("emergency_contact_name") or "").strip()
                if ec_name:
                    Emergency.create({
                        "member_id": member.id,
                        "name": ec_name,
                        "phone": (row.get("emergency_contact_phone") or "").strip(),
                        "relationship": (row.get("emergency_contact_relationship") or "").strip() or "Other",
                        "email": (row.get("emergency_contact_email") or "").strip() or False,
                        "is_primary": True,
                    })

                log_lines.append((0, 0, {
                    "row_number": idx,
                    "status": "success",
                    "message": f"Created member '{full_name}'",
                    "raw_data": raw,
                }))
                success += 1
                member_results[idx] = {"member": member, "row": row, "skipped": False}

            except Exception as exc:
                log_lines.append((0, 0, {
                    "row_number": idx,
                    "status": "error",
                    "message": str(exc),
                    "raw_data": json.dumps(row),
                }))
                error += 1

        # ── Pass 2: Household linking ──────────────────────────────────────
        # Group all successfully processed members by family_account
        family_groups = {}
        for idx, result in member_results.items():
            fa = (result["row"].get("family_account") or "").strip()
            if fa:
                family_groups.setdefault(fa, [])
                family_groups[fa].append(result)

        for fa_name, group in family_groups.items():
            try:
                household = Household.search([("name", "=ilike", fa_name)], limit=1)
                if not household:
                    household = Household.create({"name": fa_name})
                    household_map[fa_name] = household

                # Find primary guardian: first parent/both in group
                parents = [
                    g for g in group
                    if (g["row"].get("role") or "student").strip().lower() in ("parent", "both")
                ]
                students = [
                    g for g in group
                    if (g["row"].get("role") or "student").strip().lower() in ("student", "both")
                ]

                primary_guardian = parents[0]["member"] if parents else None
                if primary_guardian and not household.primary_guardian_id:
                    household.primary_guardian_id = primary_guardian

                # Assign all members to household
                for g in group:
                    if not g["member"].household_id:
                        g["member"].household_id = household

                # Create guardian links: each parent ↔ each student
                for parent_g in parents:
                    for student_g in students:
                        existing_link = GuardianLink.search([
                            ("guardian_member_id", "=", parent_g["member"].id),
                            ("student_member_id", "=", student_g["member"].id),
                        ], limit=1)
                        if not existing_link:
                            role_raw = (parent_g["row"].get("role") or "parent").strip().lower()
                            GuardianLink.create({
                                "household_id": household.id,
                                "guardian_member_id": parent_g["member"].id,
                                "student_member_id": student_g["member"].id,
                                "relation": "guardian",
                            })
            except Exception as exc:
                _logger.warning(
                    "Household linking failed for family_account='%s': %s", fa_name, exc
                )

        state = "done" if error == 0 else ("partial" if success + skip > 0 else "failed")
        log = self.env["dojo.migration.log"].create({
            "import_type": "members",
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

    def _extract_name(self, row):
        full = (row.get("full_name") or "").strip()
        first = (row.get("first_name") or "").strip()
        last = (row.get("last_name") or "").strip()
        if not full:
            full = f"{first} {last}".strip()
        return full or None, first, last

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
