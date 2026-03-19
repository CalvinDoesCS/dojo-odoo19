from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DojoSubscriptionPlan(models.Model):
    _name = "dojo.subscription.plan"
    _description = "Dojang Subscription Plan"

    name = fields.Char(required=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, required=True
    )
    price = fields.Monetary(currency_field="currency_id", required=True, string='Recurring Price')
    initial_fee = fields.Monetary(
        currency_field="currency_id",
        default=0.0,
        string='Initial / Setup Fee',
        help='One-time fee charged when the subscription starts. Leave at 0 if none.',
    )
    billing_period = fields.Selection(
        [
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
            ("yearly", "Yearly"),
        ],
        default="monthly",
        required=True,
    )
    duration = fields.Integer(
        string='Duration (Months)',
        default=0,
        help='Fixed membership length in months. 0 = ongoing (no fixed end date).',
    )
    description = fields.Text()
    auto_send_invoice = fields.Boolean(
        'Email Invoice Automatically',
        default=True,
        help='When enabled, Odoo emails the invoice PDF to the billing partner '
             'each time an invoice is generated (cron or manually).',
    )

    # ── Plan type ─────────────────────────────────────────────────────────
    plan_type = fields.Selection(
        [
            ("program", "Program-Based"),
            ("course", "Course-Based"),
        ],
        default="program",
        required=True,
        string="Plan Type",
        help=(
            "Program-Based: member may attend any class that belongs to the selected program "
            "(subject to weekly session cap).\n"
            "Course-Based: member may only attend the specific courses listed below "
            "(subject to weekly and period caps)."
        ),
    )

    # ── Program-based fields ──────────────────────────────────────────────
    program_id = fields.Many2one(
        "dojo.program",
        string="Program",
        ondelete="restrict",
        index=True,
        help="Required for Program-Based plans. Members with this plan may attend any class in this program.",
    )

    # ── Course-based / session constraints ────────────────────────────────
    allowed_template_ids = fields.Many2many(
        'dojo.class.template',
        'dojo_sub_plan_template_rel',
        'plan_id',
        'template_id',
        string='Allowed Courses',
        help=(
            'Course-Based plans only. Which courses members may enrol in. '
            'Leave empty to allow any class (session-cap rules still apply).'
        ),
    )
    max_sessions_per_week = fields.Integer(
        string='Max Sessions / Week',
        default=0,
        help='Maximum number of sessions a member can attend per calendar week under this plan. 0 = unlimited.',
    )

    # ── Onchange helpers ──────────────────────────────────────────────────
    @api.onchange("plan_type")
    def _onchange_plan_type(self):
        if self.plan_type == "program":
            self.allowed_template_ids = [(5, 0, 0)]
        elif self.plan_type == "course":
            self.program_id = False

    # ── Constraints ───────────────────────────────────────────────────────
    @api.constrains("plan_type", "program_id")
    def _check_program_required(self):
        for rec in self:
            if rec.plan_type == "program" and not rec.program_id:
                raise ValidationError(
                    "A Program must be selected for Program-Based plans."
                )
