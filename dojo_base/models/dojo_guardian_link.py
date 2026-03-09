from odoo import fields, models


class DojoGuardianLink(models.Model):
    _name = "dojo.guardian.link"
    _description = "Dojo Guardian Link"

    household_id = fields.Many2one("dojo.household", required=True, index=True, ondelete="cascade")
    guardian_member_id = fields.Many2one(
        "dojo.member", required=True, ondelete="cascade", index=True
    )
    student_member_id = fields.Many2one(
        "dojo.member", required=True, ondelete="cascade", index=True
    )
    relation = fields.Selection(
        [
            ("mother", "Mother"),
            ("father", "Father"),
            ("guardian", "Guardian"),
            ("other", "Other"),
        ],
        default="guardian",
        required=True,
    )
    is_primary = fields.Boolean(default=False)

    _dojo_guardian_unique = models.Constraint(
        "unique(household_id, guardian_member_id, student_member_id)",
        "This guardian relationship already exists.",
    )
