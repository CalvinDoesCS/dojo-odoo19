"""
dojo.credit.transaction — immutable(ish) double-entry credit ledger.

Every credit movement is recorded as a row here.  The subscription's
available balance is always derived from the live sum of this table — no
denormalised balance field to drift out of sync.

Transaction lifecycle
─────────────────────
  grant       +N  confirmed — credits issued at billing cycle top-up
  hold        -N  pending   — reservation created when a class is booked
              -N  confirmed — hold finalised: checked in OR no-show OR cancel ≤ 24 h
              -N  cancelled — hold released: cancelled > 24 h before session start
  expiry      -N  confirmed — unused credits swept at cycle renewal (no rollover)
  adjustment  ±N  confirmed — admin manual credit / debit

Balance formula
───────────────
  effective_balance = SUM(amount) WHERE status != 'cancelled'

This includes pending holds (negative), so a member cannot over-book.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

CANCEL_REFUND_HOURS = 24  # hours before session start to qualify for a refund


class DojoCreditTransaction(models.Model):
    _name = "dojo.credit.transaction"
    _description = "Dojo Credit Transaction"
    _order = "date desc, id desc"
    _rec_name = "reference"

    # ── Identity ──────────────────────────────────────────────────────────
    reference = fields.Char(
        string="Reference",
        readonly=True,
        copy=False,
        default="New",
        index=True,
    )
    date = fields.Datetime(
        string="Date",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )

    # ── Amount + type ─────────────────────────────────────────────────────
    transaction_type = fields.Selection(
        [
            ("grant", "Credit Grant"),
            ("hold", "Class Hold"),
            ("expiry", "Expiry"),
            ("adjustment", "Manual Adjustment"),
        ],
        string="Type",
        required=True,
        readonly=True,
    )
    amount = fields.Integer(
        string="Amount",
        required=True,
        readonly=True,
        help="Signed integer. Positive = credits in. Negative = credits out.",
    )
    status = fields.Selection(
        [
            ("pending", "Pending"),      # hold created; not yet finalised
            ("confirmed", "Confirmed"),  # grant / settled hold / expiry / adj
            ("cancelled", "Cancelled"),  # hold released (cancel > 24 h)
        ],
        string="Status",
        required=True,
        default="confirmed",
        readonly=True,
    )
    note = fields.Char(string="Note", readonly=True)

    # ── Links ─────────────────────────────────────────────────────────────
    subscription_id = fields.Many2one(
        "dojo.member.subscription",
        string="Subscription",
        required=True,
        index=True,
        ondelete="cascade",
        readonly=True,
    )
    member_id = fields.Many2one(
        "dojo.member",
        related="subscription_id.member_id",
        store=True,
        readonly=True,
        index=True,
    )
    enrollment_id = fields.Many2one(
        "dojo.class.enrollment",
        string="Enrollment",
        ondelete="set null",
        readonly=True,
        index=True,
        copy=False,
    )
    session_id = fields.Many2one(
        "dojo.class.session",
        related="enrollment_id.session_id",
        store=True,
        readonly=True,
    )

    # ── Unique constraint ─────────────────────────────────────────────────
    _dojo_credit_transaction_uniq_hold = models.Constraint(
        "UNIQUE(enrollment_id, transaction_type)",
        "A credit hold already exists for this enrollment.",
    )

    # ── ORM helpers ───────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env.ref(
            "dojo_credits.seq_dojo_credit_transaction",
            raise_if_not_found=False,
        )
        for vals in vals_list:
            if vals.get("reference", "New") == "New" and seq:
                vals["reference"] = seq.next_by_id()
        return super().create(vals_list)
