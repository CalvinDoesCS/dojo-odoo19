import base64
import io
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

CARD_TYPES = [
    ("book_trial", "Book Trial"),
    ("donate", "Donate"),
    ("merch", "Buy Merch"),
    ("tournament", "Register Tournament"),
    ("badge", "Member Badge (Check-in QR)"),
]

# Card types whose URL is computed automatically and don't need custom_url
_AUTO_URL_TYPES = {"book_trial"}
# Card types that have no static QR (generated per-member at runtime)
_PERSONAL_TYPES = {"badge"}


class DojoMarketingCard(models.Model):
    _name = "dojo.marketing.card"
    _description = "Dojang Marketing Card"
    _order = "sequence, id"

    name = fields.Char(required=True, string="Card Title")
    card_type = fields.Selection(CARD_TYPES, required=True, string="Type")
    subtitle = fields.Char(string="Subtitle")
    body = fields.Text(string="Body Text")
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    publish_kiosk = fields.Boolean(default=True, string="Show on Kiosk")
    publish_portal = fields.Boolean(default=True, string="Show on Portal")

    # Custom target URL — only relevant for donate / merch / tournament
    custom_url = fields.Char(
        string="Target URL",
        help="URL this card's QR code should point to. "
             "Not used for 'Book Trial' (auto) or 'Member Badge' (per-member).",
    )

    # Computed URL used to generate the QR
    target_url = fields.Char(
        compute="_compute_target_url",
        store=True,
        string="Resolved URL",
    )

    # Server-generated QR image (PNG, base64)
    qr_image = fields.Binary(
        compute="_compute_qr_image",
        store=True,
        string="QR Code",
        help="Auto-generated from Target URL. Not available for Member Badge cards.",
    )

    # ── Computed fields ───────────────────────────────────────────────────────

    @api.depends("card_type", "custom_url")
    def _compute_target_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url", default=""
        )
        for card in self:
            if card.card_type == "book_trial":
                card.target_url = f"{base_url}/dojo/book-trial"
            elif card.card_type in _PERSONAL_TYPES:
                card.target_url = False
            else:
                card.target_url = card.custom_url or False

    @api.depends("target_url")
    def _compute_qr_image(self):
        for card in self:
            if not card.target_url:
                card.qr_image = False
                continue
            card.qr_image = _generate_qr_b64(card.target_url)


# ── Module-level QR helper (no model state) ───────────────────────────────────

def _generate_qr_b64(data: str) -> str | bool:
    """Return a base64-encoded PNG QR code for *data*, or False on failure."""
    try:
        import qrcode  # noqa: PLC0415 — lazy import

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()
    except ImportError:
        _logger.warning(
            "dojo_marketing: 'qrcode' package not installed — QR generation skipped. "
            "Run: pip install qrcode[pil]"
        )
        return False
    except Exception:
        _logger.exception("dojo_marketing: QR generation failed for data=%r", data)
        return False
