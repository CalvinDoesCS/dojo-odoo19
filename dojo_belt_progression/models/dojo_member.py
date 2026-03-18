from odoo import api, fields, models


class DojoMember(models.Model):
    _inherit = "dojo.member"

    rank_history_ids = fields.One2many(
        "dojo.member.rank", "member_id", string="Belt History"
    )
    current_rank_id = fields.Many2one(
        "dojo.belt.rank",
        compute="_compute_current_rank",
        store=True,
        string="Current Belt",
    )

    # ── Attendance tracking ───────────────────────────────────────────────
    attendance_log_ids = fields.One2many(
        "dojo.attendance.log",
        "member_id",
        string="Attendance Logs",
    )
    attendance_since_last_rank = fields.Integer(
        string="Attendances Since Last Rank",
        compute="_compute_attendance_since_last_rank",
        store=True,
        help="Count of present/late sessions attended since the member's last rank was awarded.",
    )
    test_invite_pending = fields.Boolean(
        string="Belt Test Invite Pending",
        default=False,
        copy=False,
        help=(
            "Set automatically when the threshold is reached and a test event is created.  "
            "Reset when the test registration reaches a terminal result (pass/fail/withdrew) "
            "so the automation can re-evaluate on the next cycle."
        ),
    )

    current_stripe_count = fields.Integer(
        string="Current Stripes",
        compute="_compute_current_stripe_count",
        store=True,
        help="Number of stripes on the member's current belt rank.",
    )

    @api.depends("rank_history_ids.date_awarded", "rank_history_ids.rank_id")
    def _compute_current_rank(self):
        for member in self:
            latest = member.rank_history_ids.sorted("date_awarded", reverse=True)[:1]
            member.current_rank_id = latest.rank_id if latest else False

    @api.depends("rank_history_ids.date_awarded", "rank_history_ids.stripe_count")
    def _compute_current_stripe_count(self):
        for member in self:
            latest = member.rank_history_ids.sorted("date_awarded", reverse=True)[:1]
            member.current_stripe_count = latest.stripe_count if latest else 0

    @api.depends(
        "attendance_log_ids.status",
        "attendance_log_ids.checkin_datetime",
        "rank_history_ids.date_awarded",
    )
    def _compute_attendance_since_last_rank(self):
        for member in self:
            last_rank = member.rank_history_ids.sorted("date_awarded", reverse=True)[:1]
            threshold_date = last_rank.date_awarded if last_rank else False
            logs = member.attendance_log_ids.filtered(
                lambda l: l.status in ("present", "late")
                and (
                    not threshold_date
                    or (l.checkin_datetime and l.checkin_datetime.date() >= threshold_date)
                )
            )
            member.attendance_since_last_rank = len(logs)

    def action_reset_test_invite(self):
        """Manually clear the belt-test invite pending flag (admin use)."""
        self.test_invite_pending = False
