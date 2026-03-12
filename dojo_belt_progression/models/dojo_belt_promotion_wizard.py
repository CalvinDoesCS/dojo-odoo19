from odoo import api, fields, models


class DojoBeltPromotionWizardLine(models.TransientModel):
    _name = "dojo.belt.promotion.wizard.line"
    _description = "Belt Promotion Wizard Line"
    _order = "member_id"

    wizard_id = fields.Many2one(
        "dojo.belt.promotion.wizard",
        required=True,
        ondelete="cascade",
    )
    member_id = fields.Many2one("dojo.member", string="Member", required=True)
    current_rank_id = fields.Many2one(
        "dojo.belt.rank",
        string="Current Rank",
        readonly=True,
    )
    target_rank_id = fields.Many2one(
        "dojo.belt.rank",
        string="Promote To",
        required=True,
    )
    do_promote = fields.Boolean(string="Promote", default=True)


class DojoBeltPromotionWizard(models.TransientModel):
    _name = "dojo.belt.promotion.wizard"
    _description = "Belt Promotion Wizard"

    test_id = fields.Many2one(
        "dojo.belt.test",
        string="Belt Test",
        readonly=True,
    )
    program_id = fields.Many2one(
        "dojo.program",
        string="Program",
        readonly=True,
    )
    line_ids = fields.One2many(
        "dojo.belt.promotion.wizard.line",
        "wizard_id",
        string="Candidates",
    )

    @api.model
    def create_from_test(self, test_id):
        """Instantiate a wizard pre-populated from a belt test's passing registrations."""
        test = self.env["dojo.belt.test"].browse(test_id)
        passing = test.registration_ids.filtered(lambda r: r.result == "pass")
        lines = []
        for reg in passing:
            current_rank = reg.member_id.current_rank_id if hasattr(reg.member_id, "current_rank_id") else False
            lines.append((0, 0, {
                "member_id": reg.member_id.id,
                "current_rank_id": current_rank.id if current_rank else False,
                "target_rank_id": reg.target_rank_id.id,
                "do_promote": True,
            }))
        wizard = self.create({
            "test_id": test_id,
            "program_id": test.program_id.id,
            "line_ids": lines,
        })
        return wizard

    def action_promote(self):
        """Create dojo.member.rank records for all checked lines."""
        self.ensure_one()
        MemberRank = self.env["dojo.member.rank"]
        instructor = self.test_id.instructor_profile_id if self.test_id else False
        promoted = 0
        for line in self.line_ids.filtered(lambda l: l.do_promote):
            MemberRank.create({
                "member_id": line.member_id.id,
                "rank_id": line.target_rank_id.id,
                "program_id": self.program_id.id,
                "date_awarded": fields.Date.today(),
                "awarded_by": instructor.id if instructor else False,
            })
            promoted += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Promotions Applied",
                "message": f"{promoted} member(s) promoted successfully.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
