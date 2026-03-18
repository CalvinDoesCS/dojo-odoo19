"""
Instructor todo automation for the Dojo Instructor Dashboard.

Creates ``project.task`` records assigned to the relevant instructor(s) for
six natural trigger points in the member/class lifecycle:

  1. New trial / onboarding member     → membership_state → 'trial'
  2. Member paused or cancelled        → membership_state → 'paused'/'cancelled'
  3. Attendance milestone reached      → 10 / 25 / 50 / 100 / 200 classes
  4. Attendance not marked after class → session state → 'done', attendance_complete=False
  5. Student inactivity (30 days)      → daily cron
  6. Belt test eligibility             → hooked in dojo_belt_progression

All tasks land in the "Instructor Alerts" project (seeded by
``instructor_todos_data.xml``) with the "To Do" stage so they immediately
appear in the instructor dashboard "My Todos" panel.
"""

import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models


class ProjectTaskDojo(models.Model):
    """Adds a session back-reference to project.task so attendance todos
    can be auto-closed when attendance is completed."""

    _inherit = "project.task"

    dojo_session_id = fields.Many2one(
        "dojo.class.session",
        string="Dojang Session",
        ondelete="set null",
        copy=False,
        index=True,
    )

_logger = logging.getLogger(__name__)

_MILESTONES = [10, 25, 50, 100, 200]


class DojoMemberTodos(models.Model):
    """Extends dojo.member with todo helpers and dedup tracking fields."""

    _inherit = "dojo.member"

    # ── Dedup tracking ────────────────────────────────────────────────────
    milestone_todos_sent = fields.Char(
        string="Milestone Todos Sent",
        default="",
        copy=False,
        help=(
            "Comma-separated attendance milestones for which a todo has already "
            "been created (e.g. '10,25').  Reset to empty when a new rank is "
            "awarded so milestones fire again after each promotion."
        ),
    )
    lapsed_todo_sent = fields.Boolean(
        string="Inactivity Todo Sent",
        default=False,
        copy=False,
        help=(
            "Set when the 30-day inactivity todo is created. "
            "Cleared automatically when the member checks in again."
        ),
    )

    # ── Helpers ───────────────────────────────────────────────────────────

    @api.model
    def _get_instructor_alert_project(self):
        """Return the seeded 'Instructor Alerts' project, or False."""
        return self.env.ref(
            "dojo_instructor_dashboard.project_instructor_alerts",
            raise_if_not_found=False,
        )

    @api.model
    def _get_instructor_alert_stage(self):
        """Return the open 'To Do' stage in the Instructor Alerts project."""
        return self.env.ref(
            "dojo_instructor_dashboard.stage_instructor_todo",
            raise_if_not_found=False,
        )

    def _get_instructor_users_for_member(self):
        """Return a ``res.users`` recordset to assign a todo for *self*.

        Walks the member's past enrollments (most-recent first) to find the
        instructor on that session.  Falls back to every active instructor
        profile in the member's company.
        """
        self.ensure_one()
        # Most-recent enrollment with an assigned instructor
        enrollments = self.enrollment_ids.sorted(
            lambda e: e.session_id.start_datetime or fields.Datetime.now(),
            reverse=True,
        )
        for enroll in enrollments:
            sess = enroll.session_id
            if sess and sess.instructor_profile_id and sess.instructor_profile_id.user_id:
                return sess.instructor_profile_id.user_id

        # Fallback: all instructors in this company
        profiles = self.env["dojo.instructor.profile"].search(
            [
                ("company_id", "in", [self.company_id.id, False]),
                ("user_id", "!=", False),
            ]
        )
        return profiles.mapped("user_id")

    @api.model
    def _create_instructor_todo(self, users, name, deadline=None, description=False, priority="0", session=None):
        """Create one ``project.task`` per user in the Instructor Alerts project.

        Silently skips if the seed data (project/stage) hasn't been loaded yet
        or if *users* is empty.

        Pass ``session`` (a ``dojo.class.session`` record) to link the todo so
        it can be auto-closed when attendance is completed.
        """
        project = self._get_instructor_alert_project()
        stage = self._get_instructor_alert_stage()
        if not project or not stage:
            _logger.debug("Instructor Alerts project/stage not found — skipping todo: %s", name)
            return
        if not users:
            return

        user_ids = users.ids if hasattr(users, "ids") else list(users)
        for uid in user_ids:
            vals = {
                "name": name,
                "project_id": project.id,
                "stage_id": stage.id,
                "user_ids": [(4, uid)],
                "date_deadline": deadline,
                "description": description or "",
                "priority": priority,
            }
            if session:
                vals["dojo_session_id"] = session.id
            self.env["project.task"].sudo().create(vals)

    def _check_and_create_milestone_todos(self):
        """Check whether *self* has crossed a new attendance milestone and
        create a todo if so.  Called after a new attendance log is saved."""
        self.ensure_one()
        # Count present/late logs since last rank award (mirrors the stored compute)
        last_rank = self.rank_history_ids.sorted("date_awarded", reverse=True)[:1]
        threshold_date = last_rank.date_awarded if last_rank else False
        logs = self.attendance_log_ids.filtered(
            lambda l: l.status in ("present", "late")
            and (
                not threshold_date
                or (l.checkin_datetime and l.checkin_datetime.date() >= threshold_date)
            )
        )
        count = len(logs)

        sent = set(
            int(x)
            for x in (self.milestone_todos_sent or "").split(",")
            if x.strip().isdigit()
        )
        newly_hit = [m for m in _MILESTONES if count >= m and m not in sent]
        if not newly_hit:
            return

        users = self._get_instructor_users_for_member()
        for milestone in newly_hit:
            self._create_instructor_todo(
                users,
                "🎯 Milestone: %s has attended %d classes — recognize them!" % (self.name, milestone),
            )
        sent.update(newly_hit)
        # Write directly to avoid triggering this method recursively
        self.env.cr.execute(
            "UPDATE dojo_member SET milestone_todos_sent = %s WHERE id = %s",
            (",".join(str(m) for m in sorted(sent)), self.id),
        )

    # ── dojo.member.write() — membership_state transitions ────────────────

    def write(self, vals):
        old_states = (
            {m.id: m.membership_state for m in self}
            if "membership_state" in vals
            else {}
        )
        result = super().write(vals)

        if "membership_state" in vals:
            new_state = vals["membership_state"]
            for member in self:
                if old_states.get(member.id) == new_state:
                    continue  # no actual change
                users = member._get_instructor_users_for_member()
                if new_state == "trial":
                    member._create_instructor_todo(
                        users,
                        "👋 New trial member: %s — schedule intro session" % member.name,
                        deadline=fields.Date.today() + timedelta(days=3),
                    )
                elif new_state == "paused":
                    member._create_instructor_todo(
                        users,
                        "⏸ Follow up: %s has paused — reach out" % member.name,
                        deadline=fields.Date.today() + timedelta(days=2),
                    )
                elif new_state == "cancelled":
                    member._create_instructor_todo(
                        users,
                        "🚫 Follow up: %s has cancelled — reach out" % member.name,
                        deadline=fields.Date.today() + timedelta(days=2),
                    )
        return result

    # ── Student inactivity cron ───────────────────────────────────────────

    @api.model
    def _cron_check_student_inactivity(self):
        """Daily cron: create a todo for active students with no attendance
        in the past 30 days.  Deduped via ``lapsed_todo_sent``."""
        cutoff = fields.Datetime.now() - timedelta(days=30)
        candidates = self.search(
            [
                ("membership_state", "=", "active"),
                ("lapsed_todo_sent", "=", False),
                ("role", "in", ["student", "both"]),
            ]
        )
        for member in candidates:
            present_logs = member.attendance_log_ids.filtered(
                lambda l: l.status in ("present", "late") and l.checkin_datetime
            )
            if not present_logs:
                # Never attended — skip (new members are covered by trial todo)
                continue
            last_checkin = max(present_logs.mapped("checkin_datetime"))
            if last_checkin < cutoff:
                users = member._get_instructor_users_for_member()
                member._create_instructor_todo(
                    users,
                    "💤 Inactive student: %s — no attendance in 30+ days" % member.name,
                    deadline=fields.Date.today() + timedelta(days=1),
                )
                member.lapsed_todo_sent = True


class DojoClassSessionTodos(models.Model):
    """Detects when a session is marked Done without completing attendance,
    and (via cron) when an instructor forgets to mark a session at all."""

    _inherit = "dojo.class.session"

    # Dedup: set True once the missed-attendance todo has been sent for this session
    attendance_todo_sent = fields.Boolean(
        string="Attendance Reminder Sent",
        default=False,
        copy=False,
        help="Set when an 'attendance not marked' todo has been created for this session.",
    )

    def _get_session_instructor_users(self):
        """Return res.users for this session's instructor, or all company instructors."""
        self.ensure_one()
        if self.instructor_profile_id and self.instructor_profile_id.user_id:
            return self.instructor_profile_id.user_id
        profiles = self.env["dojo.instructor.profile"].search(
            [
                ("company_id", "in", [self.company_id.id, False]),
                ("user_id", "!=", False),
            ]
        )
        return profiles.mapped("user_id")

    def _session_url(self):
        """Return a backend URL that opens this session's form view.

        Uses the Odoo 17+ path-based URL format so the correct session is
        always opened rather than the list-default (today's) session.
        """
        self.ensure_one()
        return "/odoo/action-dojo_classes.action_dojo_class_sessions/%d" % self.id

    def action_open_attendance_wizard(self):
        """Pre-create the attendance wizard with lines so web_save can only
        call write() (not create()), letting our write() override preserve
        the pre-populated lines when the browser's editable list resets."""
        self.ensure_one()
        Wizard = self.env['dojo.attendance.quick.wizard']
        existing_logs = {
            log.member_id.id: log
            for log in self.env['dojo.attendance.log'].search([
                ('session_id', '=', self.id),
            ])
        }
        lines = []
        for enr in self.enrollment_ids.filtered(lambda e: e.status == 'registered'):
            log = existing_logs.get(enr.member_id.id)
            lines.append((0, 0, {
                'member_id': enr.member_id.id,
                'enrollment_id': enr.id,
                'status': log.status if log else 'present',
                'note': log.note if log else False,
            }))
        wizard = Wizard.create({
            'session_id': self.id,
            'line_ids': lines,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Mark Attendance',
            'res_model': 'dojo.attendance.quick.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def write(self, vals):
        old_states = (
            {s.id: s.state for s in self}
            if "state" in vals
            else {}
        )
        result = super().write(vals)

        # If instructor manually toggled attendance_complete = True, suppress the cron reminder
        if vals.get("attendance_complete"):
            for session in self:
                if not session.attendance_todo_sent:
                    session.attendance_todo_sent = True

        if vals.get("state") == "done":
            for session in self:
                if old_states.get(session.id) == "done":
                    continue  # already done
                if session.attendance_complete:
                    continue  # nothing to remind
                if session.attendance_todo_sent:
                    continue  # cron already fired a reminder
                instructor_user = session._get_session_instructor_users()
                url = session._session_url()
                link = Markup('<br/><a href="%s">→ Open session to mark attendance</a>') % url if url else Markup("")
                self.env["dojo.member"]._create_instructor_todo(
                    instructor_user,
                    "📋 Mark attendance: %s" % (session.template_id.name or session.name),
                    deadline=fields.Date.today(),
                    description=Markup(
                        "<p>Session <em>{name}</em> was marked done but attendance has not been recorded. "
                        "Please mark each student as present or absent.{link}</p>"
                    ).format(name=session.name, link=link),
                    priority="1",
                    session=session,
                )
                session.attendance_todo_sent = True
        return result

    @api.model
    def _cron_check_missed_attendance(self):
        """Hourly cron: find sessions that ended without attendance being marked
        and create an urgent todo for the instructor.

        Targets sessions that are:
        - still ``open`` (instructor never marked done / took attendance)
        - end_datetime is in the past
        - have at least one registered enrollment still ``pending``
        - attendance_complete not manually set to True
        - haven't had a reminder sent yet (``attendance_todo_sent=False``)
        """
        now = fields.Datetime.now()
        Sessions = self.search([
            ("state", "=", "open"),
            ("end_datetime", "<", now),
            ("attendance_todo_sent", "=", False),
            ("attendance_complete", "=", False),
        ])
        for session in Sessions:
            pending = session.enrollment_ids.filtered(
                lambda e: e.status == "registered" and e.attendance_state == "pending"
            )
            if not pending:
                # No pending enrollments — nothing to remind about
                session.attendance_todo_sent = True
                continue
            instructor_user = session._get_session_instructor_users()
            url = session._session_url()
            link = Markup('<br/><a href="%s">→ Open session to mark attendance</a>') % url if url else Markup("")
            self.env["dojo.member"]._create_instructor_todo(
                instructor_user,
                "⚠️ Attendance not marked: %s" % (session.template_id.name or session.name),
                deadline=session.end_datetime.date(),
                description=Markup(
                    "<p>Session <em>{name}</em> ended without attendance being recorded. "
                    "Please mark each of the {n} enrolled student(s) as present or absent.{link}</p>"
                ).format(name=session.name, n=len(pending), link=link),
                priority="1",
                session=session,
            )
            session.attendance_todo_sent = True
            _logger.info(
                "Missed-attendance todo created for session %d ('%s') — %d pending enrollments",
                session.id, session.name, len(pending),
            )


    def _close_attendance_todos(self):
        """Move all open attendance todos linked to this session to the Done stage.

        Called after the attendance quick wizard confirms, so the instructor's
        'Mark attendance' / 'Attendance not marked' todos disappear automatically.
        """
        self.ensure_one()
        done_stage = self.env.ref(
            "dojo_instructor_dashboard.stage_instructor_done",
            raise_if_not_found=False,
        )
        if not done_stage:
            return
        todos = self.env["project.task"].sudo().search([
            ("dojo_session_id", "=", self.id),
            ("stage_id", "!=", done_stage.id),
        ])
        if todos:
            todos.write({"stage_id": done_stage.id})
            _logger.info(
                "Auto-closed %d attendance todo(s) for session %d ('%s')",
                len(todos), self.id, self.name,
            )


class DojoAttendanceLogTodos(models.Model):
    """Resets inactivity flag and checks milestones when a new log arrives."""

    _inherit = "dojo.attendance.log"

    @api.model_create_multi
    def create(self, vals_list):
        logs = super().create(vals_list)
        for log in logs:
            if log.status not in ("present", "late") or not log.member_id:
                continue
            member = log.member_id
            # Reset lapsed flag so the inactivity cron can fire again later
            if member.lapsed_todo_sent:
                member.lapsed_todo_sent = False
            # Check if a milestone was just crossed
            member._check_and_create_milestone_todos()
        return logs


