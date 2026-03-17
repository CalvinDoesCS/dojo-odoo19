import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DojoOnboardingWizard(models.TransientModel):
    """Extends the onboarding wizard with an inline, blocking waiver-signing step.

    This replaces the previous Odoo Enterprise ``sign`` workflow with a
    Community-compatible approach:

    1.  A ``waiver`` step is injected between ``subscription`` and
        ``portal_access`` in the wizard step order.
    2.  The member (or admin on their behalf) draws a signature on a canvas
        widget (``widget="signature"``) and ticks a legal-authority checkbox.
    3.  On ``action_confirm()`` the signature is written to the newly created
        ``dojo.member``, a QWeb PDF is rendered with the full waiver text plus
        the embedded signature image, and the PDF is attached to the member.
    4.  Portal access is granted immediately — no daily cron required.
    """

    _inherit = "dojo.onboarding.wizard"

    # ── Extra step ────────────────────────────────────────────────────────────
    step = fields.Selection(
        selection_add=[("waiver", "6. Waiver")],
        ondelete={"waiver": "set default"},
    )

    # ── Waiver-specific wizard fields ─────────────────────────────────────────
    waiver_signature = fields.Image(
        string="Signature",
        attachment=True,
        max_width=800,
        max_height=400,
        help="Draw your signature using the mouse or a touchscreen stylus.",
    )
    waiver_signed_by = fields.Char(
        string="Signing As",
        help=(
            "Full name of the person signing.  Auto-filled from the member's name; "
            "edit if a legal guardian is signing on behalf of the member."
        ),
    )
    waiver_legal_authority = fields.Boolean(
        string=(
            "I confirm I have the legal authority to sign this waiver "
            "(on my own behalf, or as the legal guardian/representative of the "
            "above member)"
        ),
        default=False,
    )
    waiver_preview_html = fields.Html(
        string="Waiver",
        compute="_compute_waiver_preview_html",
        sanitize=False,
    )

    # ── Step order ────────────────────────────────────────────────────────────
    # Defined as a @property so that, when dojo_onboarding_stripe is also
    # installed (detected via its sentinel field), the 'payment' step is
    # automatically inserted between 'waiver' and 'portal_access'.
    # This matters because dojo_sign is loaded *after* dojo_onboarding_stripe
    # (both depend on dojo_onboarding; alphabetically s > o_s), so a static
    # class attribute here would clobber the one set by dojo_onboarding_stripe.
    @property
    def _STEP_ORDER(self):
        order = [
            "member_info",
            "household",
            "guardian_setup",
            "enrollment",
            "auto_enroll",
            "subscription",
            "waiver",
        ]
        # Include the Stripe payment-capture step when dojo_onboarding_stripe
        # is installed (it adds stripe_payment_method_id to the wizard fields).
        if "stripe_payment_method_id" in self._fields:
            order.append("payment")
        order.append("portal_access")
        return order

    # ── Compute ───────────────────────────────────────────────────────────────
    def _compute_waiver_preview_html(self):
        config = self.env["dojo.waiver.config"].sudo().get_singleton()
        html = config.content_html or ""
        for rec in self:
            rec.waiver_preview_html = html

    # ── Skip logic ────────────────────────────────────────────────────────────
    def _should_skip_step(self, step_name):
        if step_name == "waiver":
            return False  # waiver is always required; never skip
        return super()._should_skip_step(step_name)

    # ── Navigation overrides ──────────────────────────────────────────────────
    def action_next(self):
        """Validate the waiver step before advancing; auto-fill signed_by on entry."""
        self.ensure_one()
        # Validate waiver content before letting the user leave that step
        if self.step == "waiver":
            if not self.waiver_legal_authority:
                raise UserError(
                    _(
                        "Please tick the legal authority checkbox to confirm you are "
                        "authorised to sign this waiver before continuing."
                    )
                )
            if not self.waiver_signature:
                raise UserError(
                    _(
                        "A drawn signature is required. "
                        "Please sign in the signature box before continuing."
                    )
                )

        result = super().action_next()

        # Auto-fill signed_by when the wizard lands on the waiver step
        if self.step == "waiver" and not self.waiver_signed_by:
            self.waiver_signed_by = self.name

        return result

    # ── Confirm override ──────────────────────────────────────────────────────
    def action_confirm(self):
        """Create the member (via super), then write the signed waiver PDF."""
        self.ensure_one()

        # Ensure signed_by is set even if the user skipped back and re-confirmed
        if not self.waiver_signed_by and self.name:
            self.waiver_signed_by = self.name

        result = super().action_confirm()

        # Apply waiver data to the newly created member
        member = self.created_member_id
        if member and self.waiver_signature:
            self._apply_waiver_to_member(member)

        return result

    # ── Waiver application helper ─────────────────────────────────────────────
    def _apply_waiver_to_member(self, member):
        """Write signature fields to *member* and generate/attach the signed PDF.

        Called after ``super().action_confirm()`` has created the member record.
        PDF generation failure is non-fatal: the signature data is already saved
        on the member, so staff can regenerate the PDF manually if needed.
        """
        now = fields.Datetime.now()
        signed_by = self.waiver_signed_by or member.name

        member.sudo().write(
            {
                "waiver_signature": self.waiver_signature,
                "waiver_signed_by": signed_by,
                "waiver_signed_on": now,
            }
        )

        # Generate the signed PDF and store it as an attachment
        try:
            pdf_content, _mime = (
                self.env["ir.actions.report"]
                .sudo()
                ._render_qweb_pdf(
                    "dojo_sign.action_report_member_waiver", member.ids
                )
            )
            attachment = (
                self.env["ir.attachment"]
                .sudo()
                .create(
                    {
                        "name": f"Waiver \u2013 {member.name}.pdf",
                        "type": "binary",
                        "datas": base64.b64encode(pdf_content),
                        "res_model": "dojo.member",
                        "res_id": member.id,
                        "mimetype": "application/pdf",
                    }
                )
            )
            member.sudo().waiver_attachment_id = attachment.id
        except Exception:
            # Non-fatal: signature image is already saved on the member record.
            # Staff can print the waiver PDF manually from the member form.
            pass

