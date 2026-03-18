from odoo import api, models
from odoo.fields import Date


class DojoMemberProfile(models.Model):
    """Adds a single RPC method that returns all data needed by the
    Member Profile OWL component."""

    _inherit = "dojo.member"

    @api.model
    def get_member_profile_data(self, member_id):
        """Return a rich dict of member data for the OWL profile component.

        Called via ``orm.call("dojo.member", "get_member_profile_data", [id])``.
        Uses sudo() so instructors can always see a student's full profile
        regardless of record-level rules on related models.
        """
        member = self.sudo().browse(member_id)
        if not member.exists():
            return {}

        env = self.sudo().env

        # ── Subscription ──────────────────────────────────────────────────
        plan_name = ""
        subscription_data = None
        sub = getattr(member, "active_subscription_id", None)
        if sub and sub.id:
            if sub.plan_id:
                plan_name = sub.plan_id.name or ""
            credit_balance = getattr(sub, "credit_balance", 0) or 0
            credit_pending = getattr(sub, "credit_pending", 0) or 0
            plan = sub.plan_id
            subscription_data = {
                "id": sub.id,
                "plan_name": plan_name,
                "state": sub.state or "",
                "start_date": str(sub.start_date) if sub.start_date else "",
                "next_billing_date": str(sub.next_billing_date) if sub.next_billing_date else "",
                "billing_period": (plan.billing_period if plan else "") or "",
                "price": plan.price if plan else 0,
                "billing_failure_count": sub.billing_failure_count or 0,
                "grace_period_end": str(sub.grace_period_end) if getattr(sub, "grace_period_end", None) else "",
                "credit_balance": credit_balance,
                "credit_pending": credit_pending,
                "credits_per_period": getattr(plan, "credits_per_period", 0) if plan else 0,
            }

        # ── Basics ────────────────────────────────────────────────────────
        member_number = getattr(member, "member_number", None) or ""
        blood_type = getattr(member, "blood_type", None) or ""
        allergies = getattr(member, "allergies", None) or ""
        medical_notes = getattr(member, "medical_notes", None) or ""

        data = {
            "id": member.id,
            "name": member.name or "",
            "email": member.email or "",
            "phone": member.phone or "",
            "date_of_birth": str(member.date_of_birth) if member.date_of_birth else "",
            "role": member.role or "",
            "membership_state": member.membership_state or "",
            "emergency_note": member.emergency_note or "",
            "plan_name": plan_name,
            "member_number": member_number,
            "blood_type": blood_type,
            "allergies": allergies,
            "medical_notes": medical_notes,
            "subscription": subscription_data,
        }

        # ── Belt progression ───────────────────────────────────────────────
        current_rank = None
        rank_history = []
        attendance_since_last_rank = 0
        test_invite_pending = False
        if hasattr(member, "current_rank_id") and member.current_rank_id:
            r = member.current_rank_id
            current_rank = {
                "name": r.name or "",
                "color": r.color or "#9aa0a6",
                "sequence": r.sequence or 0,
                "max_stripes": getattr(r, "max_stripes", 0) or 0,
            }
        if hasattr(member, "rank_history_ids"):
            for rh in member.rank_history_ids.sorted("date_awarded", reverse=True)[:5]:
                rank_history.append({
                    "rank_name": rh.rank_id.name if rh.rank_id else "—",
                    "date_awarded": str(rh.date_awarded) if rh.date_awarded else "",
                    "awarded_by": rh.awarded_by.name if getattr(rh, "awarded_by", None) else "—",
                    "program": rh.program_id.name if getattr(rh, "program_id", None) and rh.program_id else "—",
                    "stripe_count": getattr(rh, "stripe_count", 0) or 0,
                })
        if hasattr(member, "attendance_since_last_rank"):
            attendance_since_last_rank = member.attendance_since_last_rank or 0
        if hasattr(member, "test_invite_pending"):
            test_invite_pending = bool(member.test_invite_pending)

        # Try to get attendance threshold from belt rank
        rank_threshold = 0
        if current_rank and hasattr(member, "current_rank_id") and member.current_rank_id:
            rank_threshold = getattr(member.current_rank_id, "attendance_threshold", 0) or 0

        data["current_rank"] = current_rank
        data["rank_history"] = rank_history
        data["attendance_since_last_rank"] = attendance_since_last_rank
        data["rank_threshold"] = rank_threshold
        data["test_invite_pending"] = test_invite_pending
        data["current_stripes"] = getattr(member, "current_stripe_count", 0) or 0

        # ── Total attendance count ─────────────────────────────────────────
        total_attendance = 0
        if hasattr(member, "attendance_log_ids"):
            total_attendance = len(member.attendance_log_ids.filtered(
                lambda l: l.status in ("present", "late")
            ))
        data["total_attendance_count"] = total_attendance

        # ── Recent attendance (last 10) ────────────────────────────────────
        recent_attendance = []
        if hasattr(member, "attendance_log_ids"):
            logs = member.attendance_log_ids.sorted(
                key=lambda l: l.checkin_datetime or "", reverse=True
            )[:10]
            for log in logs:
                session = log.session_id
                recent_attendance.append({
                    "id": log.id,
                    "session_name": (
                        session.template_id.name if session and session.template_id else "—"
                    ),
                    "date": str(log.checkin_datetime) if log.checkin_datetime else (
                        str(session.start_datetime) if session and session.start_datetime else ""
                    ),
                    "status": log.status or "",
                    "instructor": (
                        session.instructor_profile_id.name
                        if session and session.instructor_profile_id
                        else "—"
                    ),
                })
        data["recent_attendance"] = recent_attendance

        # ── Credit transactions (last 10) ──────────────────────────────────
        credit_transactions = []
        if sub and sub.id and hasattr(sub, "transaction_ids"):
            txns = sub.transaction_ids.sorted("date", reverse=True)[:10]
            for tx in txns:
                credit_transactions.append({
                    "id": tx.id,
                    "reference": tx.reference or "",
                    "date": str(tx.date) if tx.date else "",
                    "transaction_type": tx.transaction_type or "",
                    "amount": tx.amount or 0,
                    "status": tx.status or "",
                    "note": tx.note or "",
                })
        data["credit_transactions"] = credit_transactions

        # ── Household ─────────────────────────────────────────────────────
        hh = member.household_id
        if hh:
            data["household"] = {
                "id": hh.id,
                "name": hh.name or "",
                "primary_guardian": (
                    hh.primary_guardian_id.name if hh.primary_guardian_id else ""
                ),
                "members": [
                    {"id": m.id, "name": m.name or "", "role": m.role or ""}
                    for m in hh.member_ids
                ],
            }
        else:
            data["household"] = None

        # ── Days as member ─────────────────────────────────────────────────
        days_as_member = 0
        if subscription_data and subscription_data.get("start_date"):
            try:
                from datetime import date as dt_date
                start = dt_date.fromisoformat(subscription_data["start_date"])
                days_as_member = (Date.today() - start).days
            except Exception:
                pass
        data["days_as_member"] = days_as_member

        # ── Course template rosters ────────────────────────────────────────
        level_labels = dict(
            self.env["dojo.class.template"]._fields["level"].selection
        )
        templates = env["dojo.class.template"].search(
            [("course_member_ids", "in", [member_id])]
        )
        data["course_templates"] = [
            {
                "id": t.id,
                "name": t.name or "",
                "level": level_labels.get(t.level, t.level or ""),
                "instructors": (
                    ", ".join(t.instructor_profile_ids.mapped("name")) or "—"
                ),
            }
            for t in templates
        ]

        # ── Upcoming session enrollments ───────────────────────────────────
        today = Date.today()
        future_sessions = env["dojo.class.session"].search(
            [("start_datetime", ">=", str(today) + " 00:00:00")],
            order="start_datetime asc",
            limit=200,
        )
        enrollments = env["dojo.class.enrollment"].search(
            [
                ("member_id", "=", member_id),
                ("session_id", "in", future_sessions.ids),
                ("status", "!=", "cancelled"),
            ],
            limit=50,
        )
        enrollments = enrollments.sorted(
            key=lambda e: e.session_id.start_datetime or ""
        )
        data["upcoming_enrollments"] = [
            {
                "id": e.id,
                "template_name": (
                    e.session_id.template_id.name
                    if e.session_id.template_id
                    else "—"
                ),
                "start_datetime": (
                    str(e.session_id.start_datetime)
                    if e.session_id.start_datetime
                    else ""
                ),
                "instructor": (
                    e.session_id.instructor_profile_id.name
                    if e.session_id.instructor_profile_id
                    else "—"
                ),
                "status": e.status or "",
                "attendance_state": e.attendance_state or "",
            }
            for e in enrollments
        ]

        return data
