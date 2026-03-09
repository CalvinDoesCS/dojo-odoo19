"""Extensions to dojo.member for per-member weekly session counters and enrolled courses."""
from datetime import date, timedelta

from odoo import api, fields, models


class DojoMemberWeeklyCounter(models.Model):
    _inherit = "dojo.member"

    # Reverse side of the dojo_class_template_member_rel M2M — courses this member
    # is explicitly enrolled in (course roster).
    enrolled_template_ids = fields.Many2many(
        "dojo.class.template",
        "dojo_class_template_member_rel",
        "member_id",    # this member's FK column in the rel table
        "template_id",  # the template FK column
        string="Enrolled Courses",
        readonly=True,
    )

    # How many sessions the member's active plan allows per week (0 = unlimited).
    sessions_allowed_per_week = fields.Integer(
        string="Sessions Allowed / Week",
        compute="_compute_sessions_allowed_per_week",
        help="Taken from the active subscription plan's 'Max Sessions Per Week' setting. "
             "0 means unlimited.",
    )

    # How many sessions the member has as 'registered' enrollments in the current ISO week.
    sessions_used_this_week = fields.Integer(
        string="Sessions Used This Week",
        compute="_compute_sessions_used_this_week",
    )

    @api.depends("active_subscription_id", "active_subscription_id.plan_id",
                 "active_subscription_id.plan_id.max_sessions_per_week",
                 "active_subscription_id.plan_type",
                 "active_subscription_id.program_id")
    def _compute_sessions_allowed_per_week(self):
        for member in self:
            sub = member.active_subscription_id
            if sub and sub.plan_id and sub.plan_id.max_sessions_per_week:
                member.sessions_allowed_per_week = sub.plan_id.max_sessions_per_week
            else:
                member.sessions_allowed_per_week = 0

    # No @api.depends — recomputed fresh every time the field is read (no triggers
    # needed; enrollment records in dojo.class.enrollment are counted via search).
    @api.depends()
    def _compute_sessions_used_this_week(self):
        if not self.ids:
            return
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        week_start_str = "%s 00:00:00" % week_start
        week_end_str = "%s 23:59:59" % week_end
        groups = self.env['dojo.class.enrollment'].read_group(
            [
                ('member_id', 'in', self.ids),
                ('status', '=', 'registered'),
                ('session_id.start_datetime', '>=', week_start_str),
                ('session_id.start_datetime', '<=', week_end_str),
            ],
            fields=['member_id'],
            groupby=['member_id'],
        )
        counts = {g['member_id'][0]: g['member_id_count'] for g in groups}
        for member in self:
            member.sessions_used_this_week = counts.get(member.id, 0)
