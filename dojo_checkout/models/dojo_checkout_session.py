import logging
import uuid

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DAY_FIELD_MAP = {
    "mon": "pref_mon",
    "tue": "pref_tue",
    "wed": "pref_wed",
    "thu": "pref_thu",
    "fri": "pref_fri",
    "sat": "pref_sat",
    "sun": "pref_sun",
}


class DojoCheckoutSession(models.Model):
    """Server-side checkout session, keyed by a UUID token.

    Stores the buyer's details across the multi-step checkout flow and
    performs atomic member/subscription creation on completion.
    """

    _name = "dojo.checkout.session"
    _description = "Checkout Session"
    _rec_name = "member_name"
    _order = "create_date desc"

    # ── Identity ──────────────────────────────────────────────────────────
    token = fields.Char(required=True, index=True, copy=False, readonly=True)
    state = fields.Selection(
        [
            ("draft", "In Progress"),
            ("pending_payment", "Pending Payment"),
            ("completed", "Completed"),
            ("abandoned", "Abandoned"),
        ],
        default="draft",
        required=True,
    )

    # ── Plan ───────────────────────────────────────────────────────────────
    plan_id = fields.Many2one("dojo.subscription.plan", required=True, ondelete="cascade")

    # ── Enrollment type ───────────────────────────────────────────────────
    enrollment_type = fields.Selection(
        [("adult", "Adult Student"), ("family", "Parent / Guardian")],
        default="adult",
        required=True,
    )
    parent_also_trains = fields.Boolean(
        string="Parent Also Trains",
        default=False,
        help="When true, parent member gets role='both' instead of 'parent'",
    )

    # ── Primary registrant (adult, or parent in a family enrolment) ───────
    member_name = fields.Char(string="Full Name", required=True)
    member_email = fields.Char(string="Email", required=True)
    member_phone = fields.Char(string="Phone")
    date_of_birth = fields.Date(string="Date of Birth")

    # ── Child info (family enrolment only) ────────────────────────────────
    child_name = fields.Char(string="Child Full Name")
    child_dob = fields.Date(string="Child Date of Birth")
    child_email = fields.Char(string="Child Email")
    child_phone = fields.Char(string="Child Phone")
    child_portal_access = fields.Boolean(
        string="Create Portal Login for Child",
        default=True,
    )

    # ── Preferences ───────────────────────────────────────────────────────
    preferred_days = fields.Char(
        help="Comma-separated day codes: mon,tue,wed,thu,fri,sat,sun"
    )
    selected_upsell_ids = fields.Many2many(
        "dojo.checkout.upsell",
        "dojo_checkout_session_upsell_rel",
        "session_id",
        "upsell_id",
        string="Selected Upsells",
    )
    payment_mode = fields.Selection(
        [("invoice", "Invoice Me"), ("online", "Online Payment")],
        default="invoice",
    )

    # ── Results ───────────────────────────────────────────────────────────
    resulting_member_id = fields.Many2one("dojo.member", readonly=True, string="Parent / Primary Member")
    resulting_child_member_id = fields.Many2one("dojo.member", readonly=True, string="Child Member")
    resulting_subscription_id = fields.Many2one("dojo.member.subscription", readonly=True)

    # ── Computed ──────────────────────────────────────────────────────────
    @api.depends("plan_id", "selected_upsell_ids")
    def _compute_total(self):
        for rec in self:
            plan = rec.plan_id
            upsell_total = sum(u.price for u in rec.selected_upsell_ids)
            rec.checkout_total = (plan.price or 0) + (plan.initial_fee or 0) + upsell_total

    checkout_total = fields.Monetary(
        compute="_compute_total",
        currency_field="currency_id",
        string="Total Due Today",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="plan_id.currency_id",
    )

    # ── Fulfillment ───────────────────────────────────────────────────────
    def action_complete_checkout(self):
        """Atomically create member(s), subscription, auto-enroll prefs, and first invoice.

        Two paths:
          * adult   — one member (student), invoice to them, portal for them.
          * family  — parent member + child member, household + guardian link,
                      subscription/auto-enroll on child, invoice to parent,
                      portal for parent (+ optionally child).
        """
        self.ensure_one()
        env = self.env
        plan = self.plan_id
        today = fields.Date.today()
        billing_delta = {
            "weekly": relativedelta(weeks=1),
            "monthly": relativedelta(months=1),
            "yearly": relativedelta(years=1),
        }.get(plan.billing_period, relativedelta(months=1))
        next_billing = today + billing_delta

        # ── Shared helpers ──────────────────────────────────────────────
        def _find_or_create_partner(name, email, phone=None):
            p = env["res.partner"].sudo().search(
                [("email", "=ilike", email)], limit=1
            ) if email else env["res.partner"]
            if not p:
                p = env["res.partner"].sudo().create({
                    "name": name,
                    "email": email or False,
                    "phone": phone or False,
                })
            else:
                wv = {}
                if not p.phone and phone:
                    wv["phone"] = phone
                if wv:
                    p.sudo().write(wv)
            return p

        def _find_or_create_member(partner, dob=None):
            m = env["dojo.member"].sudo().search(
                [("partner_id", "=", partner.id)], limit=1
            )
            if m:
                return m
            return env["dojo.member"].sudo().create({
                "partner_id": partner.id,
                "date_of_birth": dob or False,
                "membership_state": "lead",
            })

        def _create_subscription(member_id):
            return env["dojo.member.subscription"].sudo().with_context(
                skip_subscription_check=True
            ).create({
                "member_id": member_id,
                "plan_id": plan.id,
                "start_date": today,
                "next_billing_date": next_billing,
                "state": "active",
            })

        def _auto_enroll(member):
            if not self.preferred_days or not plan.program_id:
                return
            days = [d.strip() for d in self.preferred_days.split(",") if d.strip()]
            pref_vals = {v: False for v in DAY_FIELD_MAP.values()}
            for d in days:
                if d in DAY_FIELD_MAP:
                    pref_vals[DAY_FIELD_MAP[d]] = True
            templates = env["dojo.class.template"].sudo().search([
                ("program_id", "=", plan.program_id.id),
                ("active", "=", True),
            ])
            for tmpl in templates:
                env["dojo.course.auto.enroll"].sudo().with_context(
                    skip_subscription_check=True
                ).create({
                    "member_id": member.id,
                    "template_id": tmpl.id,
                    "mode": "permanent",
                    "active": True,
                    **pref_vals,
                })

        def _build_invoice(billing_partner, subscription):
            product = env.ref(
                "dojo_subscriptions.product_membership_subscription",
                raise_if_not_found=False,
            )
            period_label = {
                "weekly": "Weekly", "monthly": "Monthly", "yearly": "Annual"
            }.get(plan.billing_period, "Monthly")
            invoice_lines = []

            sub_line = {
                "name": f"{plan.name} – {period_label} Membership",
                "quantity": 1.0,
                "price_unit": plan.price or 0.0,
            }
            if product:
                sub_line["product_id"] = product.id
            invoice_lines.append((0, 0, sub_line))

            if plan.initial_fee and plan.initial_fee > 0:
                fee_line = {
                    "name": f"{plan.name} – Enrollment Fee",
                    "quantity": 1.0,
                    "price_unit": plan.initial_fee,
                }
                if product:
                    fee_line["product_id"] = product.id
                invoice_lines.append((0, 0, fee_line))

            internal_user = env["res.users"].sudo().search(
                [("share", "=", False), ("active", "=", True)], limit=1
            )
            activity_type = env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
            member_model_id = env["ir.model"].sudo()._get_id("dojo.member")

            for upsell in self.selected_upsell_ids:
                uline = {
                    "name": upsell.name,
                    "quantity": 1.0,
                    "price_unit": upsell.price or 0.0,
                }
                if upsell.product_id:
                    uline["product_id"] = upsell.product_id.id
                invoice_lines.append((0, 0, uline))
                if internal_user and activity_type and member_model_id:
                    try:
                        # Resolve the dojo.member record so res_id matches res_model_id
                        upsell_member = subscription.member_id
                        env["mail.activity"].sudo().create({
                            "res_model_id": member_model_id,
                            "res_id": upsell_member.id,
                            "activity_type_id": activity_type.id,
                            "summary": f"Checkout upsell: {upsell.name}",
                            "note": (
                                f"<b>{upsell.name}</b> (${upsell.price:.2f}) selected at "
                                f"online checkout. Please process and fulfil."
                            ),
                            "user_id": internal_user.id,
                        })
                    except Exception:
                        _logger.warning("Checkout: upsell activity failed", exc_info=True)

            inv = env["account.move"].sudo().create({
                "move_type": "out_invoice",
                "partner_id": billing_partner.id,
                "invoice_date": today,
                "invoice_date_due": next_billing,
                "subscription_id": subscription.id,
                "company_id": env.company.id,
                "invoice_line_ids": invoice_lines,
            })
            inv.action_post()
            subscription.sudo().write({"last_invoice_id": inv.id})
            if billing_partner.email:
                try:
                    tmpl = env.ref("account.email_template_edi_invoice", raise_if_not_found=False)
                    if tmpl:
                        tmpl.sudo().send_mail(inv.id, force_send=True, raise_exception=False)
                except Exception:
                    _logger.warning("Checkout: invoice email failed", exc_info=True)
            return inv

        def _grant_portal(member):
            try:
                member.sudo().action_grant_portal_access()
            except Exception:
                _logger.warning(
                    "Checkout: portal access failed for member %s", member.id, exc_info=True
                )

        # ════════════════════════════════════════════════════════════════
        #  ADULT PATH — single member (student enrolling themselves)
        # ════════════════════════════════════════════════════════════════
        if self.enrollment_type == "adult":
            partner = _find_or_create_partner(
                self.member_name, self.member_email, self.member_phone
            )
            member = _find_or_create_member(partner, self.date_of_birth)
            # Create a solo household for consistency
            household = env["res.partner"].sudo().create({
                "name": f"{self.member_name}'s Household",
                "is_household": True,
                "is_company": True,
                "primary_guardian_id": partner.id,
                "company_id": env.company.id,
            })
            partner.sudo().write({"parent_id": household.id, "is_student": True})
            subscription = _create_subscription(member.id)
            member.sudo().action_set_active()
            _auto_enroll(member)
            _build_invoice(member.partner_id, subscription)
            _grant_portal(member)
            self.sudo().write({
                "resulting_member_id": member.id,
                "resulting_subscription_id": subscription.id,
                "state": "completed",
            })
            return member

        # ════════════════════════════════════════════════════════════════
        #  FAMILY PATH — parent + child, household, subscription on child
        # ════════════════════════════════════════════════════════════════

        # 1. Parent partner (guardian, optionally also trains)
        parent_partner = _find_or_create_partner(
            self.member_name, self.member_email, self.member_phone
        )
        parent_partner.sudo().write({"is_guardian": True})
        if self.parent_also_trains:
            parent_partner.sudo().write({"is_student": True})
        # Always create a dojo.member for the parent so they can access
        # the portal to manage their students.
        parent_member = _find_or_create_member(parent_partner, self.date_of_birth)

        # 2. Child partner + member
        child_display_name = self.child_name or f"{self.member_name}'s Child"
        child_partner = _find_or_create_partner(
            child_display_name, self.child_email or None, self.child_phone or None
        )
        child_partner.sudo().write({"is_student": True})
        child_member = _find_or_create_member(child_partner, self.child_dob)

        # 3. Household — reuse existing if both already share one, else create
        household = parent_partner.parent_id if parent_partner.parent_id.is_household else (
            child_partner.parent_id if child_partner.parent_id.is_household else
            env["res.partner"].browse()
        )
        if not household:
            last_name = (self.member_name or "").split()[-1] if self.member_name else "Family"
            household = env["res.partner"].sudo().create({
                "name": f"{last_name} Household",
                "is_household": True,
                "is_company": True,
                "company_id": env.company.id,
            })
        if not parent_partner.parent_id:
            parent_partner.sudo().write({"parent_id": household.id})
        if not child_partner.parent_id:
            child_partner.sudo().write({"parent_id": household.id})
        if not household.primary_guardian_id:
            household.sudo().write({"primary_guardian_id": parent_partner.id})

        # (Guardian relationship implicit via shared parent_id — no link needed)

        # 5. Subscription, activation, and auto-enroll — all on the CHILD
        subscription = _create_subscription(child_member.id)
        child_member.sudo().action_set_active()
        _auto_enroll(child_member)

        # 6. Invoice addressed to PARENT
        _build_invoice(parent_partner, subscription)

        # 7. Portal access: parent always; child only if opted-in and has email
        try:
            parent_partner.sudo()._grant_portal_access_credentials()
        except Exception:
            _logger.warning(
                "Checkout: portal access failed for partner %s", parent_partner.id, exc_info=True
            )
        if self.child_portal_access and self.child_email:
            _grant_portal(child_member)

        # 8. Finalize
        self.sudo().write({
            "resulting_member_id": parent_member.id if parent_member else False,
            "resulting_child_member_id": child_member.id,
            "resulting_subscription_id": subscription.id,
            "state": "completed",
        })
        return parent_member or child_member

    # ── Cleanup cron ──────────────────────────────────────────────────────
    @api.model
    def _cron_gc_abandoned_sessions(self):
        """Mark sessions 7+ days old still in draft as abandoned."""
        cutoff = fields.Datetime.now() - relativedelta(days=7)
        old = self.search([("state", "=", "draft"), ("create_date", "<", cutoff)])
        old.write({"state": "abandoned"})
