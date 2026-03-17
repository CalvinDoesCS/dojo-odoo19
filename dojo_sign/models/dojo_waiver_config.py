from odoo import api, fields, models

_DEFAULT_WAIVER_NAME = "Member Liability Waiver & Release of Claims"

_DEFAULT_WAIVER_HTML = """
<h2 style="text-align:center;">PARTICIPANT LIABILITY WAIVER AND RELEASE OF CLAIMS</h2>

<p>
In consideration of being permitted to participate in classes, training, and all activities
offered by this dojo (the <strong>"Facility"</strong>), the undersigned (the
<strong>"Participant"</strong>) hereby agrees to the following:
</p>

<h4>1. Assumption of Risk</h4>
<p>
The Participant acknowledges that martial arts training involves inherent risks, including
but not limited to physical injury, sprains, fractures, and other bodily harm.  The
Participant voluntarily assumes all such risks, whether foreseen or unforeseen, known or
unknown.
</p>

<h4>2. Release of Liability</h4>
<p>
The Participant, on behalf of themselves and their heirs, assigns, and legal
representatives, hereby releases and forever discharges the Facility, its owners,
instructors, employees, and agents from any and all claims, demands, damages, actions,
or causes of action arising from or related to participation in activities at the
Facility.
</p>

<h4>3. Medical Authorization</h4>
<p>
The Participant authorizes the Facility's staff to seek emergency medical treatment if
the Participant is incapacitated and unable to act on their own behalf.  The Participant
accepts full financial responsibility for any medical treatment rendered.
</p>

<h4>4. Photo / Media Release</h4>
<p>
The Participant consents to the use of photographs, videos, or other media taken during
Facility activities for promotional purposes, without compensation.
</p>

<h4>5. Rules &amp; Conduct</h4>
<p>
The Participant agrees to adhere to all Facility rules, instructor instructions, and
codes of conduct.  The Facility reserves the right to suspend or terminate membership
for violations.
</p>

<h4>6. Governing Law</h4>
<p>
This agreement shall be governed by applicable law.  If any provision is found
unenforceable, the remaining provisions shall remain in full force and effect.
</p>

<p>
By signing below the Participant acknowledges they have read, understood, and voluntarily
agreed to the terms above and confirm they have the legal authority to execute this waiver.
</p>
"""


class DojoWaiverConfig(models.Model):
    """Singleton model holding the global waiver text shown during onboarding.

    Admins edit the waiver content at Dojo ▸ Configuration ▸ Waiver Text.
    The same text is used for all subscription plans and rendered into the
    signed PDF that is attached to each new member's record.
    """

    _name = "dojo.waiver.config"
    _description = "Dojo Waiver Configuration"

    name = fields.Char(
        string="Waiver Title",
        required=True,
        default=_DEFAULT_WAIVER_NAME,
    )
    content_html = fields.Html(
        string="Waiver Content",
        sanitize=False,
        help=(
            "Full legal waiver text displayed to members during onboarding. "
            "Use the rich-text editor to format headings, lists, and bold text. "
            "This content will be rendered verbatim into the signed PDF."
        ),
    )

    @api.model
    def get_singleton(self):
        """Return the single waiver config record, creating it with defaults if absent."""
        config = self.search([], limit=1, order="id asc")
        if not config:
            config = self.create(
                {
                    "name": _DEFAULT_WAIVER_NAME,
                    "content_html": _DEFAULT_WAIVER_HTML,
                }
            )
        return config
