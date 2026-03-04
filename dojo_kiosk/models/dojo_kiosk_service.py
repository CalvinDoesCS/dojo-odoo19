"""
Kiosk service methods -- all business logic for the kiosk SPA lives here.
Methods are designed to be called from the kiosk HTTP controller via sudo().
"""
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError

# Module-level rate limit state: {key: {"attempts": int, "locked_until": datetime|None}}
_PIN_ATTEMPTS: dict = {}
_MAX_PIN_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15


class DojoKioskService(models.AbstractModel):
    _name = "dojo.kiosk.service"
    _description = "Dojo Kiosk Service"

    # -------------------------------------------------------------------------
    # Token + bootstrap
    # -------------------------------------------------------------------------

    @api.model
    def validate_token(self, token):
        """Return the dojo.kiosk.config for a given token, or raise AccessError."""
        if not token:
            raise AccessError("Missing kiosk token.")
        config = self.env["dojo.kiosk.config"].search(
            [("kiosk_token", "=", token), ("active", "=", True)], limit=1
        )
        if not config:
            raise AccessError("Invalid or inactive kiosk token.")
        return config

    @api.model
    def get_config_bootstrap(self, token):
        """Return device config and today's sessions for the initial app load."""
        config = self.validate_token(token)
        sessions = self.get_todays_sessions()
        announcements = [
            {"id": a.id, "title": a.title or "", "body": a.body or ""}
            for a in config.announcement_ids.filtered("active")
        ]
        return {
            "config_id": config.id,
            "name": config.name,
            "theme_mode": config.theme_mode or "dark",
            "view_mode": config.view_mode or "search_only",
            "show_title": config.show_title,
            "announcements": announcements,
            "sessions": sessions,
        }

    @api.model
    def get_enrolled_sessions_today(self, member_id, date=None):
        """Return today's open sessions where the member has a registered enrollment."""
        if date:
            try:
                from datetime import datetime as _dt
                target = _dt.strptime(date, "%Y-%m-%d")
            except (ValueError, TypeError):
                target = fields.Datetime.now()
        else:
            target = fields.Datetime.now()

        today_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = target.replace(hour=23, minute=59, second=59, microsecond=999999)

        enrollments = self.env["dojo.class.enrollment"].search([
            ("member_id", "=", member_id),
            ("status", "=", "registered"),
            ("session_id.state", "=", "open"),
            ("session_id.start_datetime", ">=", fields.Datetime.to_string(today_start)),
            ("session_id.start_datetime", "<=", fields.Datetime.to_string(today_end)),
        ])

        # Deduplicate by session
        seen = set()
        result = []
        for enr in enrollments.sorted(key=lambda e: e.session_id.start_datetime):
            s = enr.session_id
            if s.id in seen:
                continue
            seen.add(s.id)
            result.append({
                "id": s.id,
                "name": s.name,
                "template_name": s.template_id.name if s.template_id else "",
                "program_name": s.template_id.program_id.name if (s.template_id and s.template_id.program_id) else "",
                "program_color": s.template_id.program_id.color if (s.template_id and s.template_id.program_id) else "",
                "start": fields.Datetime.to_string(s.start_datetime),
                "end": fields.Datetime.to_string(s.end_datetime),
                "instructor": s.instructor_profile_id.name if s.instructor_profile_id else "",
                "attendance_state": enr.attendance_state,
            })
        return result

    @api.model
    def bulk_roster_add(
        self, session_id, member_ids,
        override_capacity=False, override_settings=False, enroll_type="single",
        date_from=None, date_to=None,
        pref_mon=False, pref_tue=False, pref_wed=False, pref_thu=False,
        pref_fri=False, pref_sat=False, pref_sun=False,
    ):
        """Add multiple members to a session roster at once.

        enroll_type:
          'single'    — one-time session enrollment only.
          'multiday'  — session enrollment + multiday auto-enroll pref
                        (covers sessions within the specified date_from/date_to range).
          'permanent' — session enrollment + permanent auto-enroll pref
                        (enrolled into every future session for this template, never removed).

        override_settings:
          When True, the course-membership constraint is bypassed and (for multiday /
          permanent) the member is added to the template's course_member_ids so
          future cron enrollments also succeed.

        override_capacity:
          When True, ignore the per-session capacity limit.
        """
        from datetime import date as _date

        session = self.env["dojo.class.session"].browse(session_id)
        if not session.exists():
            return {"success": False, "error": "Session not found."}

        template = session.template_id

        # Context used when creating enrollments
        enroll_ctx = dict(self.env.context)
        if override_settings:
            enroll_ctx["skip_course_membership_check"] = True
        EnrollModel = self.env["dojo.class.enrollment"].with_context(**enroll_ctx)
        AutoEnroll = self.env["dojo.course.auto.enroll"]

        added = []
        skipped = []
        for member_id in (member_ids or []):
            member = self.env["dojo.member"].browse(member_id)
            if not member.exists():
                skipped.append(member_id)
                continue

            # ── 1. Add to course_member_ids if override_settings + recurring type ──
            if override_settings and enroll_type in ("multiday", "permanent") and template:
                if member not in template.course_member_ids:
                    template.course_member_ids = [(4, member.id)]

            # ── 2. Session enrollment ───────────────────────────────────────────
            existing = EnrollModel.search([
                ("session_id", "=", session_id),
                ("member_id", "=", member_id),
            ], limit=1)
            if existing:
                if existing.status != "registered":
                    existing.status = "registered"
                    added.append(member_id)
                else:
                    # Already registered — still apply auto-enroll pref below
                    added.append(member_id)
            else:
                if not override_capacity and session.capacity > 0 and session.seats_taken >= session.capacity:
                    skipped.append(member_id)
                    continue

                EnrollModel.create({
                    "session_id": session_id,
                    "member_id": member_id,
                    "status": "registered",
                    "attendance_state": "pending",
                })
                added.append(member_id)

            # ── 3. Auto-enroll preference (multiday / permanent) ───────────────────
            if enroll_type in ("multiday", "permanent") and template:
                pref_mode = "multiday" if enroll_type == "multiday" else "permanent"
                day_vals = {
                    "pref_mon": pref_mon, "pref_tue": pref_tue, "pref_wed": pref_wed,
                    "pref_thu": pref_thu, "pref_fri": pref_fri, "pref_sat": pref_sat,
                    "pref_sun": pref_sun,
                }
                pref = AutoEnroll.with_context(active_test=False).search([
                    ("member_id", "=", member_id),
                    ("template_id", "=", template.id),
                ], limit=1)
                if pref:
                    # Upgrade mode if changing from limited to permanent
                    write_vals = {"active": True, **day_vals}
                    if enroll_type == "permanent" and pref.mode != "permanent":
                        write_vals["mode"] = "permanent"
                        write_vals["date_from"] = False
                        write_vals["date_to"] = False
                    elif enroll_type == "multiday" and pref.mode != "multiday":
                        write_vals["mode"] = "multiday"
                        write_vals["date_from"] = date_from or fields.Date.today()
                        write_vals["date_to"] = date_to or fields.Date.today()
                    elif enroll_type == "multiday" and pref.mode == "multiday":
                        # Update the date range even if already multiday
                        if date_from:
                            write_vals["date_from"] = date_from
                        if date_to:
                            write_vals["date_to"] = date_to
                    pref.write(write_vals)
                else:
                    create_vals = {
                        "member_id": member_id,
                        "template_id": template.id,
                        "active": True,
                        "mode": pref_mode,
                        **day_vals,
                    }
                    if pref_mode == "multiday":
                        create_vals["date_from"] = date_from or fields.Date.today()
                        create_vals["date_to"] = date_to or fields.Date.today()
                    AutoEnroll.create(create_vals)

        return {"success": True, "added": added, "skipped": skipped}

    @api.model
    def get_announcements(self, token):
        config = self.validate_token(token)
        return [
            {"id": a.id, "title": a.title or "", "body": a.body or ""}
            for a in config.announcement_ids.filtered("active")
        ]

    # -------------------------------------------------------------------------
    # Session helpers
    # -------------------------------------------------------------------------

    @api.model
    def get_todays_sessions(self, date=None):
        """Return open sessions for a given date (defaults to today), ordered by start time."""
        if date:
            try:
                from datetime import datetime as _dt
                target = _dt.strptime(date, "%Y-%m-%d")
            except (ValueError, TypeError):
                target = fields.Datetime.now()
        else:
            target = fields.Datetime.now()

        today_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = target.replace(hour=23, minute=59, second=59, microsecond=999999)

        sessions = self.env["dojo.class.session"].search([
            ("state", "=", "open"),
            ("start_datetime", ">=", fields.Datetime.to_string(today_start)),
            ("start_datetime", "<=", fields.Datetime.to_string(today_end)),
            ("company_id", "in", [self.env.company.id, False]),
        ], order="start_datetime asc")

        result = []
        for s in sessions:
            result.append({
                "id": s.id,
                "name": s.name,
                "template_name": s.template_id.name if s.template_id else "",
                "start": fields.Datetime.to_string(s.start_datetime),
                "end": fields.Datetime.to_string(s.end_datetime),
                "seats_taken": s.seats_taken,
                "capacity": s.capacity,
                "instructor": s.instructor_profile_id.name if s.instructor_profile_id else "",
            })
        return result

    # -------------------------------------------------------------------------
    # Roster helpers
    # -------------------------------------------------------------------------

    @api.model
    def get_session_roster(self, session_id):
        """Return the enrolled roster for a session with attendance state."""
        session = self.env["dojo.class.session"].browse(session_id)
        if not session.exists():
            return []

        enrollments = session.enrollment_ids.filtered(
            lambda e: e.status == "registered"
        )

        # Build log map so we can correctly surface "late" (enrollment only tracks
        # present/absent/excused, but the attendance log stores the full status)
        logs = self.env["dojo.attendance.log"].search([
            ("session_id", "=", session_id),
            ("member_id", "in", enrollments.mapped("member_id").ids),
        ])
        log_by_member = {l.member_id.id: l.status for l in logs}

        result = []
        for enr in enrollments:
            member = enr.member_id
            # Prefer the log status (supports "late"); fall back to enrollment state
            att_state = log_by_member.get(member.id) or enr.attendance_state
            result.append(self._member_roster_entry(member, enr, att_state))
        return result

    def _member_roster_entry(self, member, enrollment=None, attendance_state=None):
        """Compact dict for a roster tile."""
        if attendance_state is None:
            attendance_state = enrollment.attendance_state if enrollment else "pending"
        return {
            "member_id": member.id,
            "name": member.name,
            "member_number": member.member_number or "",
            "image_url": "/web/image/dojo.member/%d/image_128" % member.id,
            "belt_rank": member.current_rank_id.name if member.current_rank_id else "",
            "belt_color": member.current_rank_id.color if member.current_rank_id else "",
            "attendance_state": attendance_state,
            "membership_state": member.membership_state if hasattr(member, "membership_state") else "",
            "issues": self._compute_issue_flags(member),
        }

    # -------------------------------------------------------------------------
    # Member lookup
    # -------------------------------------------------------------------------

    @api.model
    def lookup_member_by_barcode(self, barcode):
        """Find a member by member_number (barcode scan)."""
        member = self.env["dojo.member"].search(
            [("member_number", "=", barcode), ("active", "=", True)], limit=1
        )
        if not member:
            return None
        return self._member_profile_dict(member)

    @api.model
    def search_members(self, query, limit=20):
        """Search members by name, email, or phone for the kiosk search bar."""
        if not query or len(query.strip()) < 2:
            return []
        domain = [
            ("active", "=", True),
            "|", "|",
            ("name", "ilike", query.strip()),
            ("email", "ilike", query.strip()),
            ("phone", "ilike", query.strip()),
        ]
        members = self.env["dojo.member"].search(domain, limit=limit, order="name asc")
        return [self._member_profile_dict(m) for m in members]

    # -------------------------------------------------------------------------
    # Member profile + issue flags
    # -------------------------------------------------------------------------

    @api.model
    def get_member_profile(self, member_id, session_id=None):
        """Full member profile for the profile card modal."""
        member = self.env["dojo.member"].browse(member_id)
        if not member.exists():
            return None
        return self._member_profile_dict(member, session_id=session_id)

    def _member_profile_dict(self, member, session_id=None):
        issues = self._compute_issue_flags(member)

        # Current enrollment in the requested session
        attendance_state = "pending"
        enrolled = False
        if session_id:
            enr = self.env["dojo.class.enrollment"].search([
                ("session_id", "=", session_id),
                ("member_id", "=", member.id),
                ("status", "=", "registered"),
            ], limit=1)
            enrolled = bool(enr)
            # Use attendance log status so "late" is preserved
            log = self.env["dojo.attendance.log"].search([
                ("session_id", "=", session_id),
                ("member_id", "=", member.id),
            ], limit=1)
            attendance_state = log.status if log else (enr.attendance_state if enr else "pending")

        # Total attendance count
        total_attendance = self.env["dojo.attendance.log"].search_count([
            ("member_id", "=", member.id),
            ("status", "in", ["present", "late"]),
        ])

        allowed = member.sessions_allowed_per_week  # 0 = unlimited
        used = member.sessions_used_this_week

        # Upcoming enrolled sessions (appointments)
        now = fields.Datetime.now()
        upcoming_enrs = self.env["dojo.class.enrollment"].search([
            ("member_id", "=", member.id),
            ("status", "=", "registered"),
        ])
        # Filter future sessions and sort in Python (related field ops not supported in ORM order/search)
        future_enrs = [
            e for e in upcoming_enrs
            if e.session_id and e.session_id.start_datetime and e.session_id.start_datetime >= now
        ]
        future_enrs.sort(key=lambda e: e.session_id.start_datetime)
        appointments = []
        for enr in future_enrs[:7]:
            s = enr.session_id
            appointments.append({
                "session_id": s.id,
                "name": s.template_id.name if s.template_id else "",
                "start": fields.Datetime.to_string(s.start_datetime) if s.start_datetime else "",
                "end": fields.Datetime.to_string(s.end_datetime) if s.end_datetime else "",
            })

        # Active plan name
        plan_name = ""
        sub = member.active_subscription_id
        if sub and sub.plan_id:
            plan_name = sub.plan_id.name or ""

        # Household + emergency contacts
        hh = member.household_id
        household = None
        if hh:
            contacts = []
            for ec in member.emergency_contact_ids:
                contacts.append({
                    "name": ec.name or "",
                    "relationship": ec.relationship or "",
                    "phone": ec.phone or "",
                    "email": ec.email or "",
                    "is_primary": bool(ec.is_primary),
                })
            household = {
                "id": hh.id,
                "name": hh.name or "",
                "members": [
                    {"id": m.id, "name": m.name or "", "role": m.role or ""}
                    for m in hh.member_ids
                ],
                "emergency_contacts": contacts,
            }

        # Belt progression: classes since last rank + per-program stats
        att_since_rank = getattr(member, "attendance_since_last_rank", 0) or 0
        programs = []
        if hasattr(member, "rank_history_ids"):
            prog_ranks = {}
            for rank_rec in member.rank_history_ids:
                prog = rank_rec.program_id
                prog_key = prog.id if prog else 0
                if prog_key not in prog_ranks or rank_rec.date_awarded > prog_ranks[prog_key]["date"]:
                    prog_ranks[prog_key] = {
                        "program_name": prog.name if prog else "General",
                        "rank_name": rank_rec.rank_id.name if rank_rec.rank_id else "",
                        "rank_color": rank_rec.rank_id.color if rank_rec.rank_id else "",
                        "date": rank_rec.date_awarded,
                    }
            # Count attendance logs per program
            all_logs = self.env["dojo.attendance.log"].search([
                ("member_id", "=", member.id),
                ("status", "in", ["present", "late"]),
            ])
            prog_attendance = {}
            for log in all_logs:
                tmpl = log.session_id.template_id if log.session_id else None
                if tmpl and tmpl.program_id:
                    pid = tmpl.program_id.id
                    prog_attendance[pid] = prog_attendance.get(pid, 0) + 1
            for prog_key, info in prog_ranks.items():
                programs.append({
                    "program_name": info["program_name"],
                    "rank_name": info["rank_name"],
                    "rank_color": info["rank_color"],
                    "attendance_count": prog_attendance.get(prog_key, 0),
                })
            programs.sort(key=lambda p: p["program_name"])

        return {
            "member_id": member.id,
            "name": member.name,
            "email": member.email or "",
            "phone": member.phone or "",
            "role": member.role or "",
            "member_number": member.member_number or "",
            "image_url": "/web/image/dojo.member/%d/image_128" % member.id,
            "date_of_birth": fields.Date.to_string(member.date_of_birth) if member.date_of_birth else "",
            "membership_state": member.membership_state,
            "belt_rank": member.current_rank_id.name if member.current_rank_id else "",
            "belt_color": member.current_rank_id.color if member.current_rank_id else "",
            "total_attendance": total_attendance,
            "sessions_used_this_week": used,
            "sessions_allowed_per_week": allowed,
            "issues": issues,
            "enrolled_in_session": enrolled,
            "attendance_state": attendance_state,
            "appointments": appointments,
            "plan_name": plan_name,
            "household": household,
            "attendance_since_last_rank": att_since_rank,
            "programs": programs,
        }

    def _compute_issue_flags(self, member):
        flags = []
        if member.membership_state == "cancelled":
            flags.append({"code": "membership_cancelled", "label": "Membership Cancelled"})
        elif member.membership_state == "paused":
            flags.append({"code": "membership_on_hold", "label": "Membership On Hold"})
        elif member.membership_state == "lead":
            flags.append({"code": "membership_lead", "label": "Not Yet Active"})

        sub = member.active_subscription_id
        if not sub:
            flags.append({"code": "no_subscription", "label": "No Active Subscription"})
        elif sub.state in ("expired", "cancelled"):
            flags.append({"code": "membership_expired", "label": "Membership Expired"})

        allowed = member.sessions_allowed_per_week
        used = member.sessions_used_this_week
        if allowed > 0 and used >= allowed:
            flags.append({"code": "credits_exhausted", "label": "Ran Out of Credits"})

        return flags

    # -------------------------------------------------------------------------
    # Check-in
    # -------------------------------------------------------------------------

    @api.model
    def checkin_member(self, member_id, session_id):
        """
        Atomic check-in:
        1. Validate eligibility.
        2. Find or create enrollment (registered).
        3. Create attendance log (present / late).
        4. Sync enrollment.attendance_state.
        Returns dict with success flag, message, and updated profile.
        """
        member = self.env["dojo.member"].browse(member_id)
        session = self.env["dojo.class.session"].browse(session_id)

        if not member.exists() or not session.exists():
            return {"success": False, "error": "Member or session not found."}

        # --- Eligibility ---
        if member.membership_state in ("cancelled", "paused", "lead"):
            return {
                "success": False,
                "error": "Membership is not active. Please see the front desk.",
            }

        if not member.active_subscription_id:
            return {
                "success": False,
                "error": "No active subscription found. Please see the front desk.",
            }

        if session.state != "open":
            return {"success": False, "error": "This session is not currently open."}

        allowed = member.sessions_allowed_per_week
        used = member.sessions_used_this_week
        if allowed > 0 and used >= allowed:
            return {
                "success": False,
                "error": "Weekly session limit reached. Please see the front desk.",
            }

        # --- Course roster check ---
        template = session.template_id
        if template.course_member_ids and member not in template.course_member_ids:
            return {
                "success": False,
                "error": "You are not enrolled in this course. Please see the front desk.",
            }

        # --- Capacity check ---
        if session.capacity > 0 and session.seats_taken >= session.capacity:
            return {"success": False, "error": "This session is full."}

        # --- Find or create enrollment ---
        existing_log = self.env["dojo.attendance.log"].search([
            ("session_id", "=", session_id),
            ("member_id", "=", member_id),
        ], limit=1)
        if existing_log:
            return {
                "success": False,
                "error": "Already checked in to this session.",
            }

        enrollment = self.env["dojo.class.enrollment"].search([
            ("session_id", "=", session_id),
            ("member_id", "=", member_id),
            ("status", "=", "registered"),
        ], limit=1)

        if not enrollment:
            enrollment = self.env["dojo.class.enrollment"].create({
                "session_id": session_id,
                "member_id": member_id,
                "status": "registered",
                "attendance_state": "pending",
            })

        # --- Determine present / late ---
        now = fields.Datetime.now()
        status = "late" if now > session.start_datetime else "present"

        log = self.env["dojo.attendance.log"].create({
            "session_id": session_id,
            "member_id": member_id,
            "enrollment_id": enrollment.id,
            "status": status,
            "checkin_datetime": now,
        })

        # Sync enrollment
        enrollment.attendance_state = "present"

        return {
            "success": True,
            "status": status,
            "log_id": log.id,
            "member": self._member_profile_dict(member, session_id=session_id),
            "session_name": session.name,
        }

    # -------------------------------------------------------------------------
    # Instructor — attendance
    # -------------------------------------------------------------------------

    @api.model
    def mark_attendance(self, session_id, member_id, attendance_status):
        """
        Instructor-side: mark a member present / late / absent / excused.
        Creates or updates the attendance log and enrollment state.
        """
        valid = ("present", "late", "absent", "excused")
        if attendance_status not in valid:
            return {"success": False, "error": "Invalid status."}

        session = self.env["dojo.class.session"].browse(session_id)
        member = self.env["dojo.member"].browse(member_id)
        if not session.exists() or not member.exists():
            return {"success": False, "error": "Session or member not found."}

        log = self.env["dojo.attendance.log"].search([
            ("session_id", "=", session_id),
            ("member_id", "=", member_id),
        ], limit=1)

        if log:
            log.status = attendance_status
        else:
            log = self.env["dojo.attendance.log"].create({
                "session_id": session_id,
                "member_id": member_id,
                "status": attendance_status,
                "checkin_datetime": fields.Datetime.now(),
            })

        # Sync enrollment
        enrollment = self.env["dojo.class.enrollment"].search([
            ("session_id", "=", session_id),
            ("member_id", "=", member_id),
            ("status", "=", "registered"),
        ], limit=1)
        if enrollment:
            enrollment.attendance_state = (
                "present" if attendance_status in ("present", "late") else attendance_status
            )

        return {"success": True, "log_id": log.id}

    # -------------------------------------------------------------------------
    # Instructor — roster management
    # -------------------------------------------------------------------------

    @api.model
    def roster_add(self, session_id, member_id):
        """Add a member to the session roster (creates enrollment)."""
        session = self.env["dojo.class.session"].browse(session_id)
        member = self.env["dojo.member"].browse(member_id)
        if not session.exists() or not member.exists():
            return {"success": False, "error": "Session or member not found."}

        existing = self.env["dojo.class.enrollment"].search([
            ("session_id", "=", session_id),
            ("member_id", "=", member_id),
        ], limit=1)
        if existing:
            if existing.status != "registered":
                existing.status = "registered"
            return {"success": True, "enrollment_id": existing.id}

        if session.capacity > 0 and session.seats_taken >= session.capacity:
            return {"success": False, "error": "Session is at full capacity."}

        enr = self.env["dojo.class.enrollment"].create({
            "session_id": session_id,
            "member_id": member_id,
            "status": "registered",
            "attendance_state": "pending",
        })
        return {"success": True, "enrollment_id": enr.id}

    @api.model
    def roster_remove(self, session_id, member_id):
        """Remove a member from the session roster."""
        enrollment = self.env["dojo.class.enrollment"].search([
            ("session_id", "=", session_id),
            ("member_id", "=", member_id),
        ], limit=1)
        if enrollment:
            enrollment.status = "cancelled"
        return {"success": True}

    # -------------------------------------------------------------------------
    # Instructor — session close
    # -------------------------------------------------------------------------

    @api.model
    def close_session(self, session_id):
        """Mark a session as done."""
        session = self.env["dojo.class.session"].browse(session_id)
        if not session.exists():
            return {"success": False, "error": "Session not found."}
        session.state = "done"
        return {"success": True}

    @api.model
    def delete_session(self, session_id):
        """Cancel a session and all its registrations."""
        session = self.env["dojo.class.session"].browse(session_id)
        if not session.exists():
            return {"success": False, "error": "Session not found."}
        session.enrollment_ids.filtered(
            lambda e: e.status == "registered"
        ).write({"status": "cancelled"})
        session.state = "cancelled"
        return {"success": True}

    @api.model
    def update_session(self, session_id, capacity=None):
        """Update editable fields on an open session."""
        session = self.env["dojo.class.session"].browse(session_id)
        if not session.exists():
            return {"success": False, "error": "Session not found."}
        if capacity is not None:
            try:
                session.capacity = max(0, int(capacity))
            except (TypeError, ValueError):
                return {"success": False, "error": "Invalid capacity value."}
        return {"success": True}

    # -------------------------------------------------------------------------
    # PIN verification
    # -------------------------------------------------------------------------

    @api.model
    def verify_pin(self, pin, token=None, config_id=None):
        """
        Verify the 6-digit instructor PIN with rate limiting.
        Locks out after _MAX_PIN_ATTEMPTS failures for _LOCKOUT_MINUTES minutes.
        token takes priority over legacy config_id.
        """
        if token:
            try:
                config_record = self.validate_token(token)
                cfg_id = config_record.id
            except AccessError:
                return {"success": False, "error": "invalid_token"}
        elif config_id:
            cfg_id = int(config_id)
        else:
            cfg_id = None

        key = cfg_id or "global"
        state = _PIN_ATTEMPTS.setdefault(key, {"attempts": 0, "locked_until": None})
        now = datetime.utcnow()
        if state["locked_until"] and now < state["locked_until"]:
            remaining = int((state["locked_until"] - now).total_seconds() / 60) + 1
            return {"success": False, "error": "locked", "retry_in_minutes": remaining}

        domain = [("active", "=", True), ("pin_code", "=", pin)]
        if cfg_id:
            domain.append(("id", "=", cfg_id))
        else:
            domain.append(("company_id", "in", [self.env.company.id, False]))
        found = self.env["dojo.kiosk.config"].search(domain, limit=1)

        if found:
            _PIN_ATTEMPTS[key] = {"attempts": 0, "locked_until": None}
            return {"success": True}
        else:
            state["attempts"] += 1
            if state["attempts"] >= _MAX_PIN_ATTEMPTS:
                state["locked_until"] = now + timedelta(minutes=_LOCKOUT_MINUTES)
                state["attempts"] = 0
                return {"success": False, "error": "locked", "retry_in_minutes": _LOCKOUT_MINUTES}
            remaining_tries = _MAX_PIN_ATTEMPTS - state["attempts"]
            return {"success": False, "error": "wrong_pin", "remaining_tries": remaining_tries}

    # -------------------------------------------------------------------------
    # Check-out
    # -------------------------------------------------------------------------

    @api.model
    def checkout_member(self, member_id, session_id):
        """Record departure time on the attendance log."""
        log = self.env["dojo.attendance.log"].search([
            ("session_id", "=", session_id),
            ("member_id", "=", member_id),
        ], limit=1)
        if not log:
            return {"success": False, "error": "No attendance record found."}
        if log.status not in ("present", "late"):
            return {"success": False, "error": "Member is not marked present or late."}
        log.checkout_datetime = fields.Datetime.now()
        return {
            "success": True,
            "checkout_datetime": fields.Datetime.to_string(log.checkout_datetime),
        }
