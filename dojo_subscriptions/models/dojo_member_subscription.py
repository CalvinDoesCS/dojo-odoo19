import logging
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoMemberSubscription(models.Model):
    _name = "dojo.member.subscription"
    _description = "Dojo Member Subscription"

    member_id = fields.Many2one("dojo.member", required=True, index=True, ondelete="cascade")
    household_id = fields.Many2one(
        "dojo.household", related="member_id.household_id", store=True, readonly=True
    )
    plan_id = fields.Many2one("dojo.subscription.plan", required=True, index=True)
    plan_type = fields.Selection(
        related="plan_id.plan_type", store=True, readonly=True, string="Plan Type"
    )
    program_id = fields.Many2one(
        "dojo.program",
        related="plan_id.program_id",
        store=True,
        readonly=True,
        string="Program",
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    start_date = fields.Date(required=True, default=fields.Date.context_today)
    end_date = fields.Date()
    next_billing_date = fields.Date()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("paused", "Paused"),
            ("cancelled", "Cancelled"),
            ("expired", "Expired"),
        ],
        default="draft",
        required=True,
    )
    last_invoice_id = fields.Many2one("account.move", string="Last Invoice")
    invoice_ids = fields.One2many("account.move", "subscription_id", string="Invoices")
    invoice_count = fields.Integer(compute="_compute_invoice_count", store=True)
    billing_reference = fields.Char(help="External billing system reference.")
    note = fields.Text()

    # ── Dunning fields ────────────────────────────────────────────────────
    billing_failure_count = fields.Integer(
        default=0,
        string='Billing Failures',
        help='Consecutive billing failures. Resets to 0 on next successful payment.',
    )
    last_billing_failure_date = fields.Date(
        string='Last Billing Failure',
        help='Date of the most recent billing failure.',
    )
    grace_period_end = fields.Date(
        compute='_compute_grace_period_end',
        store=True,
        string='Grace Period End',
        help='After 3 billing failures, the date by which payment must be '
             'received before the subscription is permanently expired.',
    )

    # ── Computed ──────────────────────────────────────────────────────────
    @api.depends("invoice_ids")
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids)

    @api.depends('billing_failure_count', 'last_billing_failure_date')
    def _compute_grace_period_end(self):
        for rec in self:
            if rec.billing_failure_count >= 3 and rec.last_billing_failure_date:
                rec.grace_period_end = rec.last_billing_failure_date + relativedelta(days=30)
            else:
                rec.grace_period_end = False

    # ── Helpers ───────────────────────────────────────────────────────────
    def _billing_partner(self):
        """Return the res.partner to invoice for this subscription."""
        self.ensure_one()
        household = self.household_id
        if household and household.primary_guardian_id and household.primary_guardian_id.partner_id:
            return household.primary_guardian_id.partner_id
        member = self.member_id
        if member.partner_id:
            return member.partner_id
        return self.env["res.partner"].browse()

    def _next_date_from(self, from_date):
        """Return the billing date one period after from_date."""
        period = self.plan_id.billing_period
        if period == "weekly":
            return from_date + relativedelta(weeks=1)
        elif period == "yearly":
            return from_date + relativedelta(years=1)
        return from_date + relativedelta(months=1)

    # ── Invoice generation ────────────────────────────────────────────────
    def action_generate_invoice(self):
        """Create and post an Odoo invoice for this subscription billing cycle."""
        self.ensure_one()
        plan = self.plan_id
        billing_partner = self._billing_partner()
        if not billing_partner:
            raise UserError(
                _("No billing partner found for subscription of %s.", self.member_id.name)
            )

        today = fields.Date.today()
        period_label = {"weekly": "Weekly", "monthly": "Monthly", "yearly": "Annual"}.get(
            plan.billing_period, plan.billing_period.capitalize()
        )
        # Determine the billing period date range for the invoice description
        period_start = self.next_billing_date or today
        period_end = self._next_date_from(period_start) - relativedelta(days=1)
        date_range = "{} – {}".format(
            period_start.strftime("%-d %b %Y"),
            period_end.strftime("%-d %b %Y"),
        )
        # Resolve the service product for the invoice line
        product = self.env.ref(
            'dojo_subscriptions.product_membership_subscription',
            raise_if_not_found=False,
        )

        invoice_line_ids = []

        # Initial / setup fee — only on the very first invoice
        is_first_invoice = not bool(self.invoice_ids)
        if is_first_invoice and plan.initial_fee and plan.initial_fee > 0:
            fee_vals = {
                'name': '{} – Enrollment Fee'.format(plan.name),
                'quantity': 1.0,
                'price_unit': plan.initial_fee,
            }
            if product:
                fee_vals['product_id'] = product.id
            invoice_line_ids.append((0, 0, fee_vals))

        recurring_vals = {
            'name': '{} – {} Membership ({})'.format(plan.name, period_label, date_range),
            'quantity': 1.0,
            'price_unit': plan.price,
        }
        if product:
            recurring_vals['product_id'] = product.id
        invoice_line_ids.append((0, 0, recurring_vals))

        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': billing_partner.id,
            'invoice_date': today,
            'invoice_date_due': period_start,   # due same day as billing date
            'subscription_id': self.id,
            'company_id': (self.company_id or self.env.company).id,
            'invoice_line_ids': invoice_line_ids,
        })
        invoice.action_post()
        self.last_invoice_id = invoice
        # Advance next billing date by one period
        self.next_billing_date = self._next_date_from(period_start)

        # Email the invoice PDF to the billing partner
        if plan.auto_send_invoice and billing_partner.email:
            try:
                template = self.env.ref(
                    'account.email_template_edi_invoice',
                    raise_if_not_found=False,
                )
                if template:
                    template.sudo().send_mail(
                        invoice.id,
                        force_send=True,
                        raise_exception=False,
                    )
            except Exception:
                _logger.warning(
                    'Dojo billing: could not email invoice %s for subscription %s',
                    invoice.name, self.id, exc_info=True,
                )

        return invoice

    def action_view_invoices(self):
        """Smart button: open invoices linked to this subscription."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Invoices",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("subscription_id", "=", self.id)],
            "context": {
                "default_subscription_id": self.id,
                "default_move_type": "out_invoice",
            },
        }

    # ── Daily cron ────────────────────────────────────────────────────────
    @api.model
    def _cron_generate_invoices(self):
        """Generate invoices for all active subscriptions due today or earlier."""
        today = fields.Date.today()
        due = self.search([
            ("state", "=", "active"),
            ("next_billing_date", "!=", False),
            ("next_billing_date", "<=", today),
        ])
        for sub in due:
            # Idempotency guard: skip if an invoice was already posted today
            # for this subscription (handles cron crash-and-retry scenarios).
            already_today = self.env['account.move'].search_count([
                ('subscription_id', '=', sub.id),
                ('invoice_date', '=', today),
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel'),
            ])
            if already_today:
                continue
            try:
                sub.action_generate_invoice()
                # Reset transient failure count on successful billing
                if sub.billing_failure_count:
                    sub._reset_billing_failures()
            except Exception as exc:
                sub._handle_billing_failure(exc)

    # ── Dunning ───────────────────────────────────────────────────────────
    def _handle_billing_failure(self, exc):
        """Escalate dunning state after a billing failure.

        Thresholds (soft dunning):
          count == 1  →  send dunning email to billing partner
          count == 2  →  pause member  (membership_state = 'paused')
          count >= 3  →  expire subscription, cancel membership
        """
        self.ensure_one()
        self.billing_failure_count = (self.billing_failure_count or 0) + 1
        self.last_billing_failure_date = fields.Date.today()
        count = self.billing_failure_count
        _logger.error(
            'Dojo billing: failed to invoice subscription %s (failure #%d): %s',
            self.id, count, exc,
        )
        if count == 1:
            template = self.env.ref(
                'dojo_subscriptions.mail_template_dunning_notice',
                raise_if_not_found=False,
            )
            if template:
                billing_partner = self._billing_partner()
                if billing_partner and billing_partner.email:
                    try:
                        template.sudo().send_mail(
                            self.id,
                            force_send=True,
                            raise_exception=False,
                            email_values={
                                'email_to': billing_partner.email,
                                'partner_ids': [(4, billing_partner.id)],
                            },
                        )
                    except Exception:
                        _logger.warning(
                            'Dojo dunning: could not send dunning email for subscription %s',
                            self.id, exc_info=True,
                        )
        elif count == 2:
            self.member_id.sudo().write({'membership_state': 'paused'})
            _logger.warning(
                'Dojo dunning: subscription %s — member paused after 2 billing failures.',
                self.id,
            )
        elif count >= 3:
            self.state = 'expired'
            self.member_id.sudo().write({'membership_state': 'cancelled'})
            _logger.warning(
                'Dojo dunning: subscription %s expired after %d billing failures.',
                self.id, count,
            )

    def _reset_billing_failures(self):
        """Reset dunning counters and reactivate member/subscription on payment recovery."""
        self.ensure_one()
        reactivated = []
        if self.state == 'expired':
            self.state = 'active'
            reactivated.append('subscription')
        if self.member_id.membership_state in ('paused', 'cancelled'):
            self.member_id.sudo().write({'membership_state': 'active'})
            reactivated.append('member')
        self.billing_failure_count = 0
        self.last_billing_failure_date = False
        _logger.info(
            'Dojo dunning: subscription %s payment received — failures reset%s.',
            self.id,
            (', reactivated: ' + ', '.join(reactivated)) if reactivated else '',
        )

    @api.model
    def _cron_watch_unpaid_invoices(self):
        """Daily cron — two passes.

        Pass 1 (recovery): subscriptions with billing_failure_count > 0 whose
        last_invoice_id is now paid → reset dunning and reactivate.

        Pass 2 (escalation): active/paused subscriptions with a posted, overdue,
        unpaid last_invoice_id → apply _handle_billing_failure() once per day.
        This catches the invoice-mode path where the invoice was created
        successfully but the member never paid.
        """
        today = fields.Date.today()

        # Pass 1 — recovery
        recovering = self.search([
            ('state', 'in', ('active', 'paused', 'expired')),
            ('billing_failure_count', '>', 0),
            ('last_invoice_id.payment_state', '=', 'paid'),
        ])
        for sub in recovering:
            sub._reset_billing_failures()

        # Pass 2 — escalation (invoice mode: overdue unpaid invoices)
        overdue_subs = self.search([
            ('state', 'in', ('active', 'paused')),
            ('last_invoice_id', '!=', False),
            ('last_invoice_id.payment_state', 'in', ('not_paid', 'partial')),
            ('last_invoice_id.invoice_date_due', '<', today),
            ('last_invoice_id.state', '=', 'posted'),
        ])
        for sub in overdue_subs:
            # Escalate at most once per day
            if sub.last_billing_failure_date == today:
                continue
            sub._handle_billing_failure(
                'Invoice %s overdue (due %s, unpaid)'
                % (sub.last_invoice_id.name, sub.last_invoice_id.invoice_date_due)
            )
