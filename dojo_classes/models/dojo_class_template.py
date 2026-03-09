from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DojoClassTemplate(models.Model):
    _name = "dojo.class.template"
    _description = "Dojo Class Template"

    name = fields.Char(required=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    program_id = fields.Many2one(
        "dojo.program",
        string="Program",
        index=True,
        ondelete="restrict",
        help="The curriculum / program this class template belongs to.",
    )
    level = fields.Selection(
        [
            ("beginner", "Beginner"),
            ("intermediate", "Intermediate"),
            ("advanced", "Advanced"),
            ("all", "All Levels"),
        ],
        default="all",
        required=True,
    )
    duration_minutes = fields.Integer(default=60)
    max_capacity = fields.Integer(default=20)
    instructor_profile_ids = fields.Many2many(
        "dojo.instructor.profile", string="Instructors"
    )
    description = fields.Text()
    # Course-level member roster (enrolled in ALL sessions generated from this template)
    course_member_ids = fields.Many2many(
        "dojo.member",
        "dojo_class_template_member_rel",
        "template_id",
        "member_id",
        string="Course Members",
    )
    # Recurrence settings
    recurrence_active = fields.Boolean(string="Enable Recurrence", default=False)
    rec_mon = fields.Boolean(string="Mon")
    rec_tue = fields.Boolean(string="Tue")
    rec_wed = fields.Boolean(string="Wed")
    rec_thu = fields.Boolean(string="Thu")
    rec_fri = fields.Boolean(string="Fri")
    rec_sat = fields.Boolean(string="Sat")
    rec_sun = fields.Boolean(string="Sun")
    recurrence_time = fields.Float(
        string="Class Time",
        help="Time of day in 24 h decimal (e.g. 18.5 = 18:30)",
    )
    recurrence_start_date = fields.Date(string="Recurrence Start")
    recurrence_end_date = fields.Date(string="Recurrence End")
    recurrence_instructor_id = fields.Many2one(
        "dojo.instructor.profile", string="Recurring Instructor"
    )

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #
    @api.model
    def _weekday_flags(self):
        """Return list of (isoweekday 1=Mon, field_name) pairs."""
        return [
            (0, "rec_mon"),
            (1, "rec_tue"),
            (2, "rec_wed"),
            (3, "rec_thu"),
            (4, "rec_fri"),
            (5, "rec_sat"),
            (6, "rec_sun"),
        ]

    def _generate_sessions_for_template(self, horizon_days=60):
        """Create sessions for all active recurrence days within the horizon.
        Skips dates that already have a generated session for this template.
        """
        self.ensure_one()
        if not self.recurrence_active:
            return
        today = fields.Date.today()
        start = max(self.recurrence_start_date or today, today)
        end_limit = today + timedelta(days=horizon_days)
        end = min(self.recurrence_end_date or end_limit, end_limit)
        if start > end:
            return

        active_weekdays = {
            iso_day
            for iso_day, fname in self._weekday_flags()
            if getattr(self, fname)
        }
        if not active_weekdays:
            return

        # Pre-fetch already-generated datetimes to avoid duplicates
        existing = self.env["dojo.class.session"].search(
            [
                ("template_id", "=", self.id),
                ("generated_from_recurrence", "=", True),
                ("start_datetime", ">=", datetime.combine(start, datetime.min.time())),
                ("start_datetime", "<=", datetime.combine(end, datetime.max.time())),
            ]
        )
        existing_dates = {s.start_datetime.date() for s in existing}

        hour, frac = divmod(self.recurrence_time, 1)
        hour = int(hour)
        minute = min(59, int(round(frac * 60)))
        duration = timedelta(minutes=self.duration_minutes or 60)

        current = start
        Session = self.env["dojo.class.session"]
        Enrollment = self.env["dojo.class.enrollment"]

        # Bulk-fetch all auto-enroll preferences for this template keyed by member_id.
        # We fetch with active_test=False so opted-out (active=False) records are included.
        pref_by_member = {
            pref.member_id.id: pref
            for pref in self.env["dojo.course.auto.enroll"].with_context(
                active_test=False
            ).search([("template_id", "=", self.id)])
        }

        while current <= end:
            if current.weekday() in active_weekdays and current not in existing_dates:
                start_dt = datetime(current.year, current.month, current.day, hour, minute)
                end_dt = start_dt + duration
                # Resolve instructor: prefer the dedicated recurrence_instructor_id,
                # then fall back to the first entry in instructor_profile_ids.
                # Use active_test=False so an archived instructor is still readable.
                instructor_id = (
                    self.with_context(active_test=False).recurrence_instructor_id.id
                    or (self.instructor_profile_ids[0].id if self.instructor_profile_ids else False)
                )
                session = Session.create(
                    {
                        "template_id": self.id,
                        "company_id": self.company_id.id,
                        "instructor_profile_id": instructor_id,
                        "start_datetime": start_dt,
                        "end_datetime": end_dt,
                        "capacity": self.max_capacity,
                        "state": "open",
                        "generated_from_recurrence": True,
                        "recurrence_template_id": self.id,
                    }
                )
                # Auto-enroll course members, respecting each member's preference.
                # No preference record  → enroll on all days (backward-compatible default).
                # active=False          → skip (explicit opt-out).
                # active=True           → defer to should_enroll_on_date().
                for member in self.course_member_ids:
                    pref = pref_by_member.get(member.id)
                    if pref is None:
                        # No preference: enroll (default)
                        enroll = True
                    else:
                        enroll = pref.should_enroll_on_date(current)
                    if enroll:
                        Enrollment.with_context(
                            skip_subscription_check=True,
                            skip_course_membership_check=True,
                        ).create(
                            {
                                "session_id": session.id,
                                "member_id": member.id,
                                "status": "registered",
                            }
                        )
            current += timedelta(days=1)

    def action_generate_sessions(self):
        """Manual trigger from the form view button."""
        for tmpl in self:
            tmpl._generate_sessions_for_template(horizon_days=60)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sessions Generated",
                "message": "Recurring sessions have been created for the next 60 days.",
                "sticky": False,
            },
        }

    def write(self, vals):
        """When members are removed from course_member_ids, cancel their future registered
        enrollments for sessions generated from this template.
        When recurrence_instructor_id changes, update the instructor on all future
        generated sessions so the change takes immediate effect.
        """
        removed_per_template = {}
        if 'course_member_ids' in vals:
            for tmpl in self:
                removed_per_template[tmpl.id] = set(tmpl.course_member_ids.ids)

        res = super().write(vals)

        now = fields.Datetime.now()

        # ── Propagate instructor change to existing future sessions ──────────
        if 'recurrence_instructor_id' in vals:
            for tmpl in self:
                tmpl_nc = tmpl.with_context(active_test=False)
                new_instructor_id = tmpl_nc.recurrence_instructor_id.id or (
                    tmpl.instructor_profile_ids[0].id if tmpl.instructor_profile_ids else False
                )
                future_sessions = self.env['dojo.class.session'].search([
                    ('template_id', '=', tmpl.id),
                    ('generated_from_recurrence', '=', True),
                    ('start_datetime', '>=', now),
                    ('state', 'not in', ['done', 'cancelled']),
                ])
                if future_sessions:
                    future_sessions.write({'instructor_profile_id': new_instructor_id})

        if removed_per_template:
            for tmpl in self:
                if tmpl.id not in removed_per_template:
                    continue
                old_ids = removed_per_template[tmpl.id]
                new_ids = set(tmpl.course_member_ids.ids)
                removed_ids = list(old_ids - new_ids)
                if removed_ids:
                    enrollments = self.env['dojo.class.enrollment'].search([
                        ('session_id.template_id', '=', tmpl.id),
                        ('member_id', 'in', removed_ids),
                        ('status', '=', 'registered'),
                        ('session_id.start_datetime', '>=', now),
                    ])
                    if enrollments:
                        enrollments.write({'status': 'cancelled'})

                # ── Enroll newly added members in existing future sessions ──
                # Skip members being handled by auto-enroll preference logic
                # (they pass context key 'auto_enroll_skip_members' to avoid double-enrollment).
                skip_ids = self.env.context.get('auto_enroll_skip_members', set())
                added_ids = list((new_ids - old_ids) - skip_ids)
                if added_ids:
                    # Fetch auto-enroll preferences for these members on this template
                    pref_by_member = {
                        pref.member_id.id: pref
                        for pref in self.env['dojo.course.auto.enroll'].with_context(
                            active_test=False
                        ).search([
                            ('template_id', '=', tmpl.id),
                            ('member_id', 'in', added_ids),
                        ])
                    }
                    future_sessions = self.env['dojo.class.session'].search([
                        ('template_id', '=', tmpl.id),
                        ('start_datetime', '>=', now),
                        ('state', 'not in', ['done', 'cancelled']),
                    ])
                    Enrollment = self.env['dojo.class.enrollment']
                    # Pre-load all existing enrollments in one query to avoid
                    # O(sessions × members) individual search() calls below.
                    existing_pairs = set()
                    if future_sessions:
                        existing_data = Enrollment.search_read([
                            ('session_id', 'in', future_sessions.ids),
                            ('member_id', 'in', added_ids),
                        ], fields=['session_id', 'member_id'])
                        existing_pairs = {
                            (e['session_id'][0], e['member_id'][0])
                            for e in existing_data
                        }
                    for session in future_sessions:
                        session_date = session.start_datetime.date()
                        to_create = []
                        for member_id in added_ids:
                            if (session.id, member_id) in existing_pairs:
                                continue
                            pref = pref_by_member.get(member_id)
                            if pref is None:
                                enroll = True  # no preference = enroll all days
                            else:
                                enroll = pref.should_enroll_on_date(session_date)
                            if enroll:
                                to_create.append({
                                    'session_id': session.id,
                                    'member_id': member_id,
                                    'status': 'registered',
                                })
                        if to_create:
                            Enrollment.with_context(
                                skip_course_membership_check=True
                            ).create(to_create)
        return res

    @api.model
    def _cron_generate_recurring_sessions(self):
        """Daily cron — process all active recurring templates."""
        templates = self.search([("recurrence_active", "=", True)])
        for tmpl in templates:
            tmpl._generate_sessions_for_template(horizon_days=60)
