import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DojoOnboardingWizard(models.TransientModel):
    """Extends the onboarding wizard with an inline, blocking waiver-signing step.

    A ``waiver`` step is injected between ``subscription`` and
    ``student_portal`` in the student registration phase.  Each student must
    sign (or have a guardian sign on their behalf) before portal access is
    granted.
    """

    _inherit = "dojo.onboarding.wizard"

    # ── Extra step ────────────────────────────────────────────────────────────
    step = fields.Selection(
        selection_add=[("waiver", "Waiver")],
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
            "Full name of the person signing.  Auto-filled from the student's name; "
            "edit if a legal guardian is signing on behalf of the student."
        ),
    )
    waiver_legal_authority = fields.Boolean(
        string=(
            "I confirm I have the legal authority to sign this waiver "
            "(on my own behalf, or as the legal guardian/representative of the "
            "above student)"
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
    # automatically included in the guardian phase (after guardian_portal).
    # dojo_sign is loaded *after* dojo_onboarding_stripe (alphabetically
    # s > o_s), so this property takes precedence.
    @property
    def _STEP_ORDER(self):
        guardian_steps = list(self._GUARDIAN_STEPS)
        student_steps = list(self._STUDENT_STEPS)
        # Insert waiver after subscription
        idx = student_steps.index('subscription') + 1
        student_steps.insert(idx, 'waiver')
        # Include the Stripe payment step in the guardian phase when
        # dojo_onboarding_stripe is installed.
        if 'stripe_payment_method_id' in self._fields:
            guardian_steps.append('payment')
        return guardian_steps + student_steps

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
            self.waiver_signed_by = self.student_name

        return result

    # ── Student creation hook ─────────────────────────────────────────────────
    def _create_student_member(self):
        """Create the student via super, then apply the signed waiver."""
        member = super()._create_student_member()
        if member and self.waiver_signature:
            if not self.waiver_signed_by and self.student_name:
                self.waiver_signed_by = self.student_name
            self._apply_waiver_to_member(member)
        return member

    # ── Reset waiver fields between students ──────────────────────────────────
    def _reset_student_fields(self):
        super()._reset_student_fields()
        self.write({
            'waiver_signature': False,
            'waiver_signed_by': False,
            'waiver_legal_authority': False,
        })

    # ── Waiver application helper ─────────────────────────────────────────────
    def _apply_waiver_to_member(self, member):
        """Write signature fields to *member* and generate/attach the signed PDF.

        Called from ``_create_student_member()`` after the member record is
        created.  PDF generation failure is non-fatal: the signature data is
        already saved on the member, so staff can regenerate the PDF manually.
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

