from odoo import fields, models


class DojoBeltRank(models.Model):
    _name = "dojo.belt.rank"
    _description = "Dojang Belt Rank"
    _order = "sequence, name"

    name = fields.Char(required=True, string="Rank Name")
    sequence = fields.Integer(default=10, help="Lower = beginner, Higher = advanced")
    color = fields.Char(
        string="Belt Colour",
        help="CSS colour name or hex (e.g. 'white', '#FFD700')",
        default="#ffffff",
    )
    description = fields.Text()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )

    # ── Attendance-threshold eligibility ─────────────────────────────────
    attendance_threshold = fields.Integer(
        string="Attendance Threshold",
        default=0,
        help=(
            "Number of attended sessions since the member's last rank award required "
            "to automatically create a belt-test invitation.  Set to 0 to disable "
            "automatic invitations for this rank."
        ),
    )
    testing_fee_product_id = fields.Many2one(
        "product.product",
        string="Testing Fee Product",
        domain="[('type', 'in', ['service', 'consu'])]",
        help=(
            "If set, an invoice for this product will be posted automatically when a "
            "belt-test invitation is created for this rank."
        ),
    )

    # Reverse links
    member_rank_ids = fields.One2many(
        "dojo.member.rank", "rank_id", string="Awarded To"
    )

    # ── Dan Level ─────────────────────────────────────────────────────────
    is_dan = fields.Boolean(
        string="Is Dan Level",
        default=False,
        help="Check if this rank represents a Dan (black belt degree) level.",
    )
    dan_level = fields.Integer(
        string="Dan Level",
        default=0,
        help="Dan degree (1–10). Only relevant when 'Is Dan Level' is enabled.",
    )
