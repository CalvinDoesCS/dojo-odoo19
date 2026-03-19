import logging
import uuid

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DojoCheckout(http.Controller):
    """Public-facing checkout flow and portal upgrade routes."""

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_session(self, token):
        if not token:
            return None
        session = request.env["dojo.checkout.session"].sudo().search(
            [("token", "=", token)], limit=1
        )
        return session if session.exists() else None

    def _get_portal_member(self):
        user = request.env.user
        if user._is_public():
            return None
        member = request.env["dojo.member"].sudo().search(
            [("partner_id", "=", user.partner_id.id)], limit=1
        )
        return member if member.exists() else None

    def _plans_with_config(self):
        """Return all active plans grouped by program with their config."""
        plans = request.env["dojo.subscription.plan"].sudo().search(
            [("active", "=", True)], order="name"
        )
        configs = {
            c.plan_id.id: c
            for c in request.env["dojo.checkout.config"].sudo().search([])
        }
        programs = {}
        for plan in plans:
            prog = plan.program_id
            if prog.id not in programs:
                programs[prog.id] = {"program": prog, "plans": []}
            programs[prog.id]["plans"].append({
                "plan": plan,
                "config": configs.get(plan.id),
            })
        return list(programs.values())

    # ══════════════════════════════════════════════════════════════════════
    #  PUBLIC CHECKOUT FLOW
    # ══════════════════════════════════════════════════════════════════════

    @http.route("/checkout", auth="public", website=True)
    def checkout_gallery(self, **kw):
        """Step 0 — Plan gallery grouped by program."""
        groups = self._plans_with_config()
        return request.render("dojo_checkout.checkout_gallery", {
            "plan_groups": groups,
        })

    @http.route("/checkout/plan/<int:plan_id>", auth="public", website=True)
    def checkout_plan(self, plan_id, **kw):
        """Step 1 — Plan detail page with member info form + upsells."""
        plan = request.env["dojo.subscription.plan"].sudo().browse(plan_id)
        if not plan.exists() or not plan.active:
            return request.redirect("/checkout")
        config = request.env["dojo.checkout.config"].sudo().search(
            [("plan_id", "=", plan_id)], limit=1
        )
        # Gather upsells: from config if set, otherwise all upsells linked to this plan
        upsells = config.upsell_ids if config else request.env["dojo.checkout.upsell"].sudo().search(
            [("active", "=", True), ("plan_ids", "=", plan_id)]
        )
        return request.render("dojo_checkout.checkout_plan", {
            "plan": plan,
            "config": config,
            "upsells": upsells,
        })

    @http.route(
        "/checkout/plan/<int:plan_id>/start",
        auth="public", website=True, methods=["POST"], csrf=True
    )
    def checkout_start(self, plan_id, **post):
        """Step 1 POST — Validate member info, collect upsells, create session."""
        plan = request.env["dojo.subscription.plan"].sudo().browse(plan_id)
        if not plan.exists() or not plan.active:
            return request.redirect("/checkout")

        name = post.get("member_name", "").strip()
        email = post.get("member_email", "").strip().lower()
        if not name or not email:
            return request.redirect(f"/checkout/plan/{plan_id}?error=missing_fields")

        # Collect selected upsell IDs from checkboxes: name="upsell_<id>"
        upsell_ids = []
        for key, val in post.items():
            if key.startswith("upsell_") and val == "on":
                try:
                    upsell_ids.append(int(key.split("_", 1)[1]))
                except (ValueError, IndexError):
                    pass

        session = request.env["dojo.checkout.session"].sudo().create({
            "token": str(uuid.uuid4()),
            "plan_id": plan_id,
            "member_name": name,
            "member_email": email,
            "member_phone": post.get("member_phone", "").strip() or False,
            "date_of_birth": post.get("date_of_birth") or False,
            "enrollment_type": post.get("enrollment_type", "adult"),
            "parent_also_trains": post.get("parent_also_trains") == "on",
            "child_name": post.get("child_name", "").strip() or False,
            "child_dob": post.get("child_dob") or False,
            "child_email": post.get("child_email", "").strip().lower() or False,
            "child_phone": post.get("child_phone", "").strip() or False,
            "child_portal_access": post.get("child_portal_access") != "off",
            "selected_upsell_ids": [(6, 0, upsell_ids)] if upsell_ids else [],
        })
        return request.redirect(f"/checkout/schedule/{session.token}")

    @http.route(
        "/checkout/schedule/<string:token>",
        auth="public", website=True, methods=["GET", "POST"]
    )
    def checkout_schedule(self, token, **post):
        """Step 2 — Day/time preference picker."""
        session = self._get_session(token)
        if not session or session.state == "completed":
            return request.redirect("/checkout")

        if request.httprequest.method == "POST":
            # HTML multi-select sends preferred_days as list or single value
            days_raw = post.get("preferred_days", "")
            if isinstance(days_raw, list):
                days = ",".join(d.strip() for d in days_raw if d.strip())
            else:
                days = days_raw.strip()
            session.sudo().write({"preferred_days": days})
            return request.redirect(f"/checkout/summary/{token}")

        # GET — build schedule context
        templates = request.env["dojo.class.template"].sudo().browse()
        if session.plan_id.program_id:
            templates = request.env["dojo.class.template"].sudo().search([
                ("program_id", "=", session.plan_id.program_id.id),
                ("active", "=", True),
            ])

        all_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        day_labels = {
            "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
            "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
        }
        return request.render("dojo_checkout.checkout_schedule", {
            "session": session,
            "templates": templates,
            "all_days": all_days,
            "day_labels": day_labels,
        })

    @http.route("/checkout/summary/<string:token>", auth="public", website=True)
    def checkout_summary(self, token, **kw):
        """Step 3 — Order summary with Invoice/Pay buttons."""
        session = self._get_session(token)
        if not session or session.state == "completed":
            return request.redirect("/checkout")

        ICP = request.env["ir.config_parameter"].sudo()
        stripe_pk = ICP.get_param("stripe.publishable_key", "")
        return request.render("dojo_checkout.checkout_summary", {
            "session": session,
            "stripe_publishable_key": stripe_pk,
            # kept for backward-compat with invoice-button class toggle
            "has_payment_provider": bool(stripe_pk),
        })

    @http.route(
        "/checkout/invoice/<string:token>",
        auth="public", website=True, methods=["POST"], csrf=True
    )
    def checkout_invoice(self, token, **kw):
        """Step 4a — Invoice me: create member + subscription + send invoice."""
        session = self._get_session(token)
        if not session or session.state == "completed":
            return request.redirect("/checkout")

        session.sudo().write({"payment_mode": "invoice"})
        try:
            session.sudo().action_complete_checkout()
        except Exception as exc:
            _logger.error(
                "Checkout invoice error (token=%s): %s", token, exc, exc_info=True
            )
            return request.render("dojo_checkout.checkout_error", {
                "error": str(exc),
                "token": token,
            })
        return request.redirect(f"/checkout/complete/{token}")

    @http.route(
        "/checkout/pay/<string:token>",
        auth="public", website=True, methods=["POST"], csrf=True
    )
    def checkout_pay(self, token, **kw):
        """Step 4b — Pay now with Stripe: collects PM from Elements, charges immediately.

        Expects POST field ``payment_method_id`` (pm_…) produced by Stripe.js.
        If missing or Stripe is not configured, falls through to the invoice path.
        """
        session = self._get_session(token)
        if not session or session.state == "completed":
            return request.redirect("/checkout")

        payment_method_id = (kw.get("payment_method_id") or "").strip()

        session.sudo().write({"payment_mode": "online"})
        try:
            session.sudo().action_complete_checkout()
        except Exception as exc:
            _logger.error(
                "Checkout pay error (token=%s): %s", token, exc, exc_info=True
            )
            return request.render("dojo_checkout.checkout_error", {
                "error": str(exc),
                "token": token,
            })

        # Stripe charge — only when a PaymentMethod ID was submitted
        if payment_method_id.startswith("pm_"):
            household = session.sudo().resulting_member_id.partner_id.parent_id
            if household:
                try:
                    household.sudo().action_save_payment_method(payment_method_id)
                    invoice = session.sudo().resulting_subscription_id.last_invoice_id
                    if invoice:
                        pi = household.sudo().action_charge_invoice(invoice)
                        status = (
                            pi.get("status") if isinstance(pi, dict)
                            else getattr(pi, "status", "")
                        )
                        if status == "requires_action":
                            pi_id = (
                                pi.get("id") if isinstance(pi, dict)
                                else getattr(pi, "id", "")
                            )
                            return request.redirect(
                                f"/checkout/pay-confirm/{token}?pi={pi_id}"
                            )
                except Exception as exc:
                    _logger.error(
                        "Checkout Stripe charge error (token=%s): %s",
                        token, exc, exc_info=True,
                    )
                    # Membership already created — show error without destroying it
                    return request.render("dojo_checkout.checkout_error", {
                        "error": "Your membership was created but payment failed: " + str(exc),
                        "token": token,
                    })

        return request.redirect(f"/checkout/complete/{token}")

    @http.route(
        "/checkout/pay-confirm/<string:token>",
        auth="public", website=True, methods=["GET"],
    )
    def checkout_pay_confirm(self, token, pi=None, **kw):
        """Step 4c — Stripe 3DS return URL.

        Stripe redirects here after the customer completes 3D Secure with
        ?payment_intent=pi_xxx. The actual payment outcome is handled by the
        Stripe → NestJS → /bridge/v1/webhooks/event webhook pipeline.
        We simply redirect to the completion page.
        """
        if not self._get_session(token):
            return request.redirect("/checkout")
        return request.redirect(f"/checkout/complete/{token}")

    @http.route("/checkout/complete/<string:token>", auth="public", website=True)
    def checkout_complete(self, token, **kw):
        """Step 5 — Success page."""
        session = self._get_session(token)
        if not session:
            return request.redirect("/checkout")
        config = request.env["dojo.checkout.config"].sudo().search(
            [("plan_id", "=", session.plan_id.id)], limit=1
        )
        return request.render("dojo_checkout.checkout_complete", {
            "session": session,
            "config": config,
        })

    @http.route("/checkout/error", auth="public", website=True)
    def checkout_error_page(self, token=None, **kw):
        return request.render("dojo_checkout.checkout_error", {
            "error": "An unexpected error occurred. Please contact us for help.",
            "token": token,
        })

    # ══════════════════════════════════════════════════════════════════════
    #  PORTAL UPGRADE FLOW (trial/lead → active member)
    # ══════════════════════════════════════════════════════════════════════

    @http.route("/my/dojo/upgrade", auth="user", website=True, methods=["GET", "POST"])
    def portal_upgrade(self, **post):
        """One-click upgrade: trial/lead member picks a plan and becomes active."""
        member = self._get_portal_member()
        if not member or member.membership_state not in ("lead", "trial"):
            return request.redirect("/my/dojo")

        if request.httprequest.method == "POST":
            plan_id = int(post.get("plan_id", 0))
            plan = request.env["dojo.subscription.plan"].sudo().browse(plan_id)
            if not plan.exists() or not plan.active:
                return request.redirect("/my/dojo/upgrade?error=invalid_plan")

            today = fields.Date.today()
            billing_delta = {
                "weekly": relativedelta(weeks=1),
                "monthly": relativedelta(months=1),
                "yearly": relativedelta(years=1),
            }.get(plan.billing_period, relativedelta(months=1))

            subscription = request.env["dojo.member.subscription"].sudo().with_context(
                skip_subscription_check=True
            ).create({
                "member_id": member.id,
                "plan_id": plan.id,
                "start_date": today,
                "next_billing_date": today + billing_delta,
                "state": "active",
            })
            member.sudo().action_set_active()

            # Generate and email the first invoice
            invoice_failed = False
            try:
                subscription.sudo().action_generate_invoice()
            except Exception:
                _logger.warning(
                    "Portal upgrade: could not generate invoice for member %s",
                    member.id, exc_info=True
                )
                invoice_failed = True

            redirect_url = "/my/dojo?tab=billing&upgraded=1"
            if invoice_failed:
                redirect_url += "&invoice_warning=1"
            return request.redirect(redirect_url)

        # GET — show plan picker
        plans = request.env["dojo.subscription.plan"].sudo().search(
            [("active", "=", True)], order="name"
        )
        configs = {
            c.plan_id.id: c
            for c in request.env["dojo.checkout.config"].sudo().search([])
        }
        return request.render("dojo_checkout.checkout_upgrade", {
            "member": member,
            "plans": plans,
            "configs": configs,
        })
