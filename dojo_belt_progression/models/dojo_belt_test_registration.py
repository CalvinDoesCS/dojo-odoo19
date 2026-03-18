from odoo import fields, models


class DojoBeltTestRegistration(models.Model):
    _name = "dojo.belt.test.registration"
    _description = "Dojang Belt Test Registration"

    test_id = fields.Many2one(
        "dojo.belt.test", required=True, ondelete="cascade", index=True
    )
    member_id = fields.Many2one(
        "dojo.member", required=True, ondelete="cascade", index=True
    )
    target_rank_id = fields.Many2one("dojo.belt.rank", required=True, string="Testing For")
    program_id = fields.Many2one(
        "dojo.program",
        related="test_id.program_id",
        store=True,
        string="Program",
        index=True,
    )
    result = fields.Selection(
        [
            ("pending", "Pending"),
            ("pass", "Pass"),
            ("fail", "Fail"),
            ("withdrew", "Withdrew"),
        ],
        default="pending",
        required=True,
    )
    notes = fields.Text()
    company_id = fields.Many2one(
        "res.company", related="test_id.company_id", store=True, index=True
    )

    _dojo_belt_test_registration_unique = models.Constraint(
        "unique(test_id, member_id)",
        "A member can only register for a belt test once.",
    )

    def write(self, vals):
        res = super().write(vals)
        # When a registration reaches a terminal result, clear the pending flag
        # so the automation cron can re-evaluate eligibility on the next cycle.
        if "result" in vals and vals["result"] in ("pass", "fail", "withdrew"):
            self.filtered(
                lambda r: r.result in ("pass", "fail", "withdrew")
            ).mapped("member_id").filtered("test_invite_pending").write(
                {"test_invite_pending": False}
            )
        return res

    def action_award_rank(self):
        """Create a dojo.member.rank record for passing registrations."""
        for reg in self.filtered(lambda r: r.result == "pass"):
            self.env["dojo.member.rank"].create(
                {
                    "member_id": reg.member_id.id,
                    "rank_id": reg.target_rank_id.id,
                    "program_id": reg.test_id.program_id.id or False,
                    "date_awarded": reg.test_id.test_date,
                    "awarded_by": reg.test_id.instructor_profile_id.id or False,
                    "test_registration_id": reg.id,
                }
            )
