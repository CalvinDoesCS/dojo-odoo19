import pytz
from datetime import date, datetime, timedelta
from odoo import api, fields, models


class DojoMemberDashboard(models.Model):
    """Extends dojo.member with a belt rank stub and enrollment One2many for the
    instructor dashboard.  When dojo_belt_progression is installed, the view
    XPath in that module replaces current_belt_stub with current_rank_id."""

    _inherit = 'dojo.member'

    # Reverse One2many from dojo.class.enrollment so we can filter members
    # by instructor in domain expressions like:
    # [('enrollment_ids.session_id.instructor_profile_id.user_id', '=', uid)]
    enrollment_ids = fields.One2many(
        'dojo.class.enrollment',
        'member_id',
        string='Class Enrollments',
    )

    # TODO: replace with Many2one('dojo.belt.rank') when dojo_belt_progression ships
    current_belt_stub = fields.Char(
        string='Belt Rank',
        compute='_compute_belt_stub',
        help='Placeholder — full belt progression is available once dojo_belt_progression is installed.',
    )

    def _compute_belt_stub(self):
        for rec in self:
            rec.current_belt_stub = '—'


class DojoInstructorProfile(models.Model):
    """Extends dojo.instructor.profile with live KPI computed fields for the
    instructor dashboard.  All fields are non-stored so they recompute on every
    read (acceptable for a dashboard context)."""

    _inherit = 'dojo.instructor.profile'

    # ── Relations for dashboard embedding ────────────────────────────────
    session_ids = fields.One2many(
        'dojo.class.session', 'instructor_profile_id', string='Sessions',
    )

    session_today_ids = fields.Many2many(
        'dojo.class.session',
        compute='_compute_session_today_ids',
        string="Today's Classes",
    )

    upcoming_session_ids = fields.Many2many(
        'dojo.class.session',
        'instructor_profile_upcoming_rel',
        compute='_compute_upcoming_session_ids',
        string='Upcoming Classes',
    )

    task_ids = fields.Many2many(
        'project.task',
        compute='_compute_task_ids',
        string='My Todos',
    )

    @api.depends('session_ids.start_datetime')
    def _compute_session_today_ids(self):
        _, today_start, today_end = self._today_utc_range()
        for profile in self:
            profile.session_today_ids = self.env['dojo.class.session'].search([
                ('instructor_profile_id', '=', profile.id),
                ('start_datetime', '>=', today_start),
                ('start_datetime', '<=', today_end),
            ])

    @api.depends('session_ids.start_datetime')
    def _compute_upcoming_session_ids(self):
        tz_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(tz_name)
        today = fields.Date.context_today(self)
        tomorrow = today + timedelta(days=1)
        two_weeks = today + timedelta(days=14)
        tomorrow_start = user_tz.localize(
            datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        two_weeks_end = user_tz.localize(
            datetime(two_weeks.year, two_weeks.month, two_weeks.day, 23, 59, 59)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        for profile in self:
            profile.upcoming_session_ids = self.env['dojo.class.session'].search([
                ('instructor_profile_id', '=', profile.id),
                ('start_datetime', '>=', tomorrow_start),
                ('start_datetime', '<=', two_weeks_end),
            ])

    @api.depends('user_id')
    def _compute_task_ids(self):
        for profile in self:
            if profile.user_id:
                profile.task_ids = self.env['project.task'].search([
                    ('user_ids', 'in', profile.user_id.ids),
                    ('stage_id.fold', '=', False),
                ])
            else:
                profile.task_ids = self.env['project.task']

    def _today_utc_range(self):
        """Return (today_date, today_start_utc, today_end_utc) where the date
        boundaries are expressed in UTC but aligned to midnight/23:59:59 in the
        *user's* local timezone.  This prevents off-by-one-day errors when the
        server (UTC) and the user (e.g. America/New_York) are on different calendar
        dates."""
        tz_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(tz_name)
        today = fields.Date.context_today(self)  # date in user's tz
        today_start = user_tz.localize(
            datetime(today.year, today.month, today.day, 0, 0, 0)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        today_end = user_tz.localize(
            datetime(today.year, today.month, today.day, 23, 59, 59)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        return today, today_start, today_end

    # ── Today's sessions ──────────────────────────────────────────────────
    sessions_today_count = fields.Integer(
        string='Sessions Today',
        compute='_compute_instructor_kpis',
    )

    # ── Active students across all open/done sessions ─────────────────────
    students_total_count = fields.Integer(
        string='Total Students',
        compute='_compute_instructor_kpis',
    )

    # ── Fill rate (last 30 days) ──────────────────────────────────────────
    avg_fill_rate = fields.Float(
        string='Avg Fill Rate (%)',
        compute='_compute_instructor_kpis',
        digits=(5, 1),
    )

    # ── Attendance rate (last 30 days) ────────────────────────────────────
    attendance_rate = fields.Float(
        string='Attendance Rate (%)',
        compute='_compute_instructor_kpis',
        digits=(5, 1),
    )

    @api.model
    def get_my_profile_data(self):
        """Returns KPI data for the currently logged-in instructor.
        Uses self.env.uid (always correct server-side) so no client-side
        UID lookup is needed."""
        profile = self.search([('user_id', '=', self.env.uid)], limit=1)
        if not profile:
            return False
        return {
            'id': profile.id,
            'name': profile.name,
            'user_id': profile.user_id.id,
            'sessions_today_count': profile.sessions_today_count,
            'students_total_count': profile.students_total_count,
            'avg_fill_rate': profile.avg_fill_rate,
            'attendance_rate': profile.attendance_rate,
        }

    @api.depends('user_id')
    def _compute_instructor_kpis(self):
        """Computes KPI values for each instructor profile using batched queries
        (5 queries total regardless of how many profiles are in ``self``)."""
        if not self:
            return
        Session = self.env['dojo.class.session']
        Enrollment = self.env['dojo.class.enrollment']
        AttendanceLog = self.env['dojo.attendance.log']

        profile_ids = self.ids
        _, today_start, today_end = self._today_utc_range()
        thirty_days_ago = today_start - timedelta(days=30)

        # ── Today’s session count per instructor (1 query) ─────────────────
        today_sessions = Session.search([
            ('instructor_profile_id', 'in', profile_ids),
            ('start_datetime', '>=', today_start),
            ('start_datetime', '<=', today_end),
        ])
        today_count_map = {}
        for s in today_sessions:
            pid = s.instructor_profile_id.id
            today_count_map[pid] = today_count_map.get(pid, 0) + 1

        # ── Total enrolled students (distinct) per instructor (2 queries) ──
        all_active_sessions = Session.search([
            ('instructor_profile_id', 'in', profile_ids),
            ('state', 'in', ['open', 'done']),
        ])
        # Pre-build session_id → instructor_profile_id map to avoid M2o chain in loop
        sess_to_instructor = {s.id: s.instructor_profile_id.id for s in all_active_sessions}
        students_map = {}  # pid → set of member ids
        if all_active_sessions:
            all_enrollments = Enrollment.search([
                ('session_id', 'in', all_active_sessions.ids),
                ('status', '=', 'registered'),
            ])
            for enr in all_enrollments:
                pid = sess_to_instructor.get(enr.session_id.id)
                if pid:
                    students_map.setdefault(pid, set()).add(enr.member_id.id)

        # ── Recent sessions per instructor for fill/attendance rate (1 query)
        recent_sessions = Session.search([
            ('instructor_profile_id', 'in', profile_ids),
            ('start_datetime', '>=', thirty_days_ago),
            ('state', 'in', ['open', 'done']),
        ])
        recent_sess_to_instructor = {s.id: s.instructor_profile_id.id for s in recent_sessions}
        capacity_map = {}  # pid → (total_capacity, total_taken)
        for s in recent_sessions:
            pid = s.instructor_profile_id.id
            cap, taken = capacity_map.get(pid, (0, 0))
            if s.capacity > 0:
                cap += s.capacity
            capacity_map[pid] = (cap, taken + s.seats_taken)

        # ── Attendance logs for all recent sessions (1 query) ─────────────
        log_map = {}  # pid → (total, present)
        if recent_sessions:
            logs = AttendanceLog.search([('session_id', 'in', recent_sessions.ids)])
            for log in logs:
                pid = recent_sess_to_instructor.get(log.session_id.id)
                if pid:
                    total, present = log_map.get(pid, (0, 0))
                    log_map[pid] = (total + 1, present + (1 if log.status == 'present' else 0))

        # ── Assign computed values ─────────────────────────────────────────
        for profile in self:
            pid = profile.id
            profile.sessions_today_count = today_count_map.get(pid, 0)
            profile.students_total_count = len(students_map.get(pid, set()))
            tot_cap, tot_taken = capacity_map.get(pid, (0, 0))
            profile.avg_fill_rate = (tot_taken / tot_cap * 100) if tot_cap else 0.0
            tot_logs, tot_present = log_map.get(pid, (0, 0))
            profile.attendance_rate = (tot_present / tot_logs * 100) if tot_logs else 0.0

    # ── Admin dashboard data ──────────────────────────────────────────────

    @api.model
    def get_admin_dashboard_data(self):
        """Returns comprehensive dashboard data for admins:
        - Global KPI summary
        - Per-instructor KPIs
        - Dropped/cancelled students (last 60 days)
        - Recent sessions with fill/attendance breakdown
        """
        Session = self.env['dojo.class.session']
        Enrollment = self.env['dojo.class.enrollment']
        AttendanceLog = self.env['dojo.attendance.log']

        _, today_start, today_end = self._today_utc_range()
        thirty_days_ago = today_start - timedelta(days=30)
        sixty_days_ago = today_start - timedelta(days=60)

        # ── Global KPIs ───────────────────────────────────────────────────
        all_profiles = self.search([])
        active_members = self.env['dojo.member'].search_count([
            ('role', 'in', ['student', 'both']),
            ('membership_state', 'in', ['trial', 'active']),
        ])
        sessions_today = Session.search_count([
            ('start_datetime', '>=', today_start),
            ('start_datetime', '<=', today_end),
        ])

        # Overall fill rate (last 30 days)
        recent_sessions = Session.search([
            ('start_datetime', '>=', thirty_days_ago),
            ('state', 'in', ['open', 'done']),
        ])
        total_capacity = sum(s.capacity for s in recent_sessions if s.capacity > 0)
        total_taken = sum(s.seats_taken for s in recent_sessions)
        overall_fill_rate = (total_taken / total_capacity * 100) if total_capacity else 0.0

        # Overall attendance rate (last 30 days)
        recent_logs = AttendanceLog.search([
            ('session_id', 'in', recent_sessions.ids),
        ]) if recent_sessions else self.env['dojo.attendance.log']
        present_count = len(recent_logs.filtered(lambda l: l.status == 'present'))
        overall_attendance_rate = (
            present_count / len(recent_logs) * 100
        ) if recent_logs else 0.0

        # Dropped students count (last 60 days)
        total_dropped_60d = Enrollment.search_count([
            ('status', '=', 'cancelled'),
            ('session_id.start_datetime', '>=', sixty_days_ago),
        ])

        summary = {
            'total_instructors': len(all_profiles),
            'total_active_students': active_members,
            'sessions_today': sessions_today,
            'overall_fill_rate': round(overall_fill_rate, 1),
            'overall_attendance_rate': round(overall_attendance_rate, 1),
            'total_dropped_60d': total_dropped_60d,
        }

        # ── Per-instructor KPIs ───────────────────────────────────────────        # Build students_count per instructor directly to avoid stale
        # cached values from the @api.depends('user_id') computed field.
        active_sessions_all = Session.search([
            ('state', 'in', ['open', 'done']),
        ])
        if active_sessions_all:
            enrollments_all = Enrollment.search([
                ('session_id', 'in', active_sessions_all.ids),
                ('status', '=', 'registered'),
            ])
        else:
            enrollments_all = self.env['dojo.class.enrollment']
        # Map profile_id -> set of distinct member ids
        students_map = {}
        for e in enrollments_all:
            pid = e.session_id.instructor_profile_id.id
            if pid:
                students_map.setdefault(pid, set()).add(e.member_id.id)
        # Compute sessions_today per instructor directly to avoid stale
        # cached values from the @api.depends('user_id') computed field.
        today_session_map = {}
        today_session_recs = Session.search([
            ('start_datetime', '>=', today_start),
            ('start_datetime', '<=', today_end),
        ])
        for s in today_session_recs:
            pid = s.instructor_profile_id.id
            if not pid:
                # Fallback: if the session's template has exactly one instructor, attribute to them
                tmpl_instructors = s.template_id.instructor_profile_ids
                if len(tmpl_instructors) == 1:
                    pid = tmpl_instructors.id
            if pid:
                today_session_map[pid] = today_session_map.get(pid, 0) + 1

        instructors = []
        for p in all_profiles:
            instructors.append({
                'id': p.id,
                'name': p.name,
                'sessions_today': today_session_map.get(p.id, 0),
                'students_count': len(students_map.get(p.id, set())),
                'fill_rate': round(p.avg_fill_rate, 1),
                'attendance_rate': round(p.attendance_rate, 1),
            })
        instructors.sort(key=lambda x: x['students_count'], reverse=True)

        # ── Dropped / cancelled students (last 60 days) ───────────────────
        dropped_enrollments = Enrollment.search([
            ('status', '=', 'cancelled'),
            ('session_id.start_datetime', '>=', sixty_days_ago),
        ], order='session_id desc', limit=50)

        dropped_students = []
        for e in dropped_enrollments:
            dropped_students.append({
                'member_id': e.member_id.id,
                'member_name': e.member_id.name or '—',
                'class_name': (
                    e.session_id.template_id.name if e.session_id.template_id else '—'
                ),
                'instructor_name': (
                    e.session_id.instructor_profile_id.name
                    if e.session_id.instructor_profile_id else '—'
                ),
                'session_date': (
                    fields.Datetime.to_string(e.session_id.start_datetime)[:10]
                    if e.session_id.start_datetime else '—'
                ),
                'membership_state': e.member_id.membership_state or '—',
            })

        # ── Recent sessions (last 30 days, done/open, up to 40) ──────────
        recent_session_recs = Session.search([
            ('start_datetime', '>=', thirty_days_ago),
            ('state', 'in', ['open', 'done']),
        ], order='start_datetime desc', limit=40)

        recent_sessions_data = []
        for s in recent_session_recs:
            sess_logs = AttendanceLog.search([('session_id', '=', s.id)])
            present = len(sess_logs.filtered(lambda l: l.status == 'present'))
            total_log = len(sess_logs)
            fill = round((s.seats_taken / s.capacity * 100), 1) if s.capacity else 0.0
            att = round((present / total_log * 100), 1) if total_log else None
            recent_sessions_data.append({
                'id': s.id,
                'class_name': s.template_id.name if s.template_id else '—',
                'instructor_name': (
                    s.instructor_profile_id.name if s.instructor_profile_id else '—'
                ),
                'date': (
                    fields.Datetime.to_string(s.start_datetime)[:10]
                    if s.start_datetime else '—'
                ),
                'capacity': s.capacity,
                'enrolled': s.seats_taken,
                'present': present,
                'absent': total_log - present,
                'fill_rate': fill,
                'attendance_rate': att,
                'state': s.state,
            })

        return {
            'summary': summary,
            'instructors': instructors,
            'dropped_students': dropped_students,
            'recent_sessions': recent_sessions_data,
        }
