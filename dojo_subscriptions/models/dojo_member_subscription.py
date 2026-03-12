import logging
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoMemberSubscription(models.Model):
    _name = "dojo.member.subscription"
    _description = "Dojo Member Subscription"
    _rec_name = "name"

    name = fields.Char(
        compute="_compute_name",
        store=True,
        string="Name",
    )

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
    household_invoice_ids = fields.Many2many(
        "account.move",
        "dojo_invoice_sub_rel",
        "subscription_id",
        "invoice_id",
        string="Household Invoices",
        help="Consolidated invoices that cover this subscription along with sibling subscriptions.",
    )
    invoice_count = fields.Integer(compute="_compute_invoice_count", store=False)
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
    @api.depends("member_id", "plan_id")
    def _compute_name(self):
        for rec in self:
            parts = []
            if rec.member_id:
                parts.append(rec.member_id.name)
            if rec.plan_id:
                parts.append(rec.plan_id.name)
            rec.name = " \u2014 ".join(parts) if parts else _("New Subscription")

    @api.depends("invoice_ids", "household_invoice_ids")
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids | rec.household_invoice_ids)

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
    def _build_invoice_lines(self, today=None):
        """Build invoice line command vals for one billing period and advance next_billing_date.

        Returns (invoice_line_ids_vals, period_start) where invoice_line_ids_vals is
        a list of (0, 0, {...}) tuples ready for account.move creation.
        Side-effect: advances self.next_billing_date by one billing period.
        """
        self.ensure_one()
        if today is None:
            today = fields.Date.today()
        plan = self.plan_id
        period_label = {"weekly": "Weekly", "monthly": "Monthly", "yearly": "Annual"}.get(
            plan.billing_period, plan.billing_period.capitalize()
        )
        period_start = self.next_billing_date or today
        period_end = self._next_date_from(period_start) - relativedelta(days=1)
        date_range = "{} – {}".format(
            period_start.strftime("%-d %b %Y"),
            period_end.strftime("%-d %b %Y"),
        )
        product = self.env.ref(
            'dojo_subscriptions.product_membership_subscription',
            raise_if_not_found=False,
        )
        line_vals = []
        # Enrollment fee on the very first invoice for this subscription
        is_first_invoice = not bool(self.invoice_ids) and not bool(self.household_invoice_ids)
        if is_first_invoice and plan.initial_fee and plan.initial_fee > 0:
            fee_vals = {
                'name': '{} – Enrollment Fee'.format(plan.name),
                'quantity': 1.0,
                'price_unit': plan.initial_fee,
            }
            if product:
                fee_vals['product_id'] = product.id
            line_vals.append((0, 0, fee_vals))
        recurring_vals = {
            'name': '{} – {} Membership ({})'.format(plan.name, period_label, date_range),
            'quantity': 1.0,
            'price_unit': plan.price,
        }
        if product:
            recurring_vals['product_id'] = product.id
        line_vals.append((0, 0, recurring_vals))
        # Advance the billing date now so multi-sub grouped loops see unique dates
        self.next_billing_date = self._next_date_from(period_start)
        return line_vals, period_start

    def action_generate_invoice(self):
        """Create and post an Odoo invoice for this subscription billing cycle.

        Used for manual/admin invoice generation and for single-occupant
        households in the daily cron.  Multi-sub household cron uses
        _generate_household_invoice() instead.
        """
        self.ensure_one()
        billing_partner = self._billing_partner()
        if not billing_partner:
            raise UserError(
                _("No billing partner found for subscription of %s.", self.member_id.name)
            )
        today = fields.Date.today()
        invoice_line_ids, period_start = self._build_invoice_lines(today)
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': billing_partner.id,
            'invoice_date': today,
            'invoice_date_due': period_start,
            'subscription_id': self.id,
            'company_id': (self.company_id or self.env.company).id,
            'invoice_line_ids': invoice_line_ids,
        })
        invoice.action_post()
        self.last_invoice_id = invoice
        plan = self.plan_id
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

    def _generate_household_invoice(self, subs, today):
        """Create ONE consolidated invoice for all subscriptions in a household billing group.

        Called by _cron_generate_invoices() when 2+ subs share the same billing
        partner and company.  Lines from every sub are combined on a single
        account.move and linked to each sub via dojo_invoice_sub_rel (Many2many).

        Returns the posted account.move record.
        """
        if not subs:
            return None
        first_sub = subs[0]
        billing_partner = first_sub._billing_partner()
        if not billing_partner:
            raise UserError(_(
                "No billing partner found for household billing group (first sub: %s).",
                first_sub.member_id.name,
            ))
        company = first_sub.company_id or self.env.company
        all_line_vals = []
        period_starts = []
        for sub in subs:
            lines, period_start = sub._build_invoice_lines(today)
            all_line_vals.extend(lines)
            period_starts.append(period_start)
        invoice = self.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': billing_partner.id,
            'invoice_date': today,
            'invoice_date_due': min(period_starts),
            'company_id': company.id,
            'invoice_line_ids': all_line_vals,
            'dojo_subscription_ids': [(6, 0, subs.ids)],
        })
        invoice.action_post()
        for sub in subs:
            sub.last_invoice_id = invoice
        auto_send = any(s.plan_id.auto_send_invoice for s in subs)
        if auto_send and billing_partner.email:
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
                    'Dojo billing: could not email consolidated invoice %s',
                    invoice.name, exc_info=True,
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
            "domain": [
                "|",
                ("subscription_id", "=", self.id),
                ("dojo_subscription_ids", "in", [self.id]),
            ],
            "context": {
                "default_subscription_id": self.id,
                "default_move_type": "out_invoice",
            },
        }

    # ── Daily cron ────────────────────────────────────────────────────────
    @api.model
    def _cron_generate_invoices(self):
        """Generate consolidated household invoices for all active subscriptions due today.

        Subscriptions sharing a billing partner+company are grouped and billed
        on a single invoice.  Single-sub households fall through to
        action_generate_invoice() for backward compatibility.
        """
        from collections import defaultdict
        today = fields.Date.today()
        due = self.search([
            ("state", "=", "active"),
            ("next_billing_date", "!=", False),
            ("next_billing_date", "<=", today),
        ])
        # Idempotency: drop subs already invoiced today (handles cron restart).
        filtered = self.env['dojo.member.subscription']
        for sub in due:
            already_m2o = self.env['account.move'].search_count([
                ('subscription_id', '=', sub.id),
                ('invoice_date', '=', today),
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel'),
            ])
            already_m2m = self.env['account.move'].search_count([
                ('dojo_subscription_ids', 'in', [sub.id]),
                ('invoice_date', '=', today),
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel'),
            ])
            if not already_m2o and not already_m2m:
                filtered |= sub
        # Group by (billing_partner_id, company_id) to consolidate households.
        groups = defaultdict(lambda: self.env['dojo.member.subscription'])
        for sub in filtered:
            partner = sub._billing_partner()
            if not partner:
                _logger.warning(
                    'Dojo billing: no billing partner for subscription %s — skipped.', sub.id
                )
                continue
            key = (partner.id, (sub.company_id or self.env.company).id)
            groups[key] |= sub
        for _key, group_subs in groups.items():
            if len(group_subs) == 1:
                # Single sub — use per-subscription invoice (M2o path).
                sub = group_subs
                try:
                    sub.action_generate_invoice()
                    if sub.billing_failure_count:
                        sub._reset_billing_failures()
                except Exception as exc:
                    sub._handle_billing_failure(exc)
            else:
                # Multiple subs share a billing partner — consolidated invoice.
                try:
                    self._generate_household_invoice(group_subs, today)
                    for sub in group_subs:
                        if sub.billing_failure_count:
                            sub._reset_billing_failures()
                except Exception as exc:
                    _logger.error(
                        'Dojo billing: failed to generate consolidated invoice for group: %s',
                        exc, exc_info=True,
                    )
                    for sub in group_subs:
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
