from odoo import api, fields, models


class DojoMemberRank(models.Model):
    _name = "dojo.member.rank"
    _description = "Dojang Member Rank History"
    _order = "date_awarded desc"

    member_id = fields.Many2one(
        "dojo.member", required=True, ondelete="cascade", index=True
    )
    rank_id = fields.Many2one(
        "dojo.belt.rank", required=True, ondelete="restrict", index=True
    )
    program_id = fields.Many2one(
        "dojo.program",
        string="Program",
        index=True,
        help="Program this rank was awarded under.",
    )
    date_awarded = fields.Date(required=True, default=fields.Date.today)
    awarded_by = fields.Many2one("dojo.instructor.profile", string="Awarded By")
    test_registration_id = fields.Many2one(
        "dojo.belt.test.registration",
        string="Test Registration",
        readonly=True,
    )
    notes = fields.Text()
    company_id = fields.Many2one(
        "res.company",
        related="member_id.company_id",
        store=True,
        index=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Reset milestone_todos_sent on the member when a new rank is awarded
        so that attendance milestones fire again after each promotion."""
        records = super().create(vals_list)
        member_ids = records.mapped("member_id").ids
        if member_ids:
            self.env["dojo.member"].browse(member_ids).write(
                {"milestone_todos_sent": ""}
            )
        return records
