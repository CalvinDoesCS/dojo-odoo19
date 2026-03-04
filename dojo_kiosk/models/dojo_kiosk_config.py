import re
import secrets

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DojoKioskConfig(models.Model):
    _name = "dojo.kiosk.config"
    _description = "Dojo Kiosk Configuration"
    _order = "name"

    name = fields.Char(string="Kiosk Name", required=True)
    pin_code = fields.Char(
        string="Instructor PIN",
        required=True,
        help="Exactly 6 digits used to unlock Instructor Mode on this kiosk.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)

    # ── Token-based device auth ────────────────────────────────────────
    kiosk_token = fields.Char(
        string="Kiosk Token",
        readonly=True,
        copy=False,
        index=True,
        help="Unguessable URL token. Share the Kiosk URL with the tablet operator.",
    )
    kiosk_url = fields.Char(
        string="Kiosk URL",
        compute="_compute_kiosk_url",
        help="Open this URL on the kiosk tablet.",
    )

    # ── Theming & announcements ────────────────────────────────────────
    theme_mode = fields.Selection(
        [("dark", "Dark"), ("light", "Light")],
        string="Theme",
        default="dark",
    )
    announcement_ids = fields.One2many(
        "dojo.kiosk.announcement",
        "config_id",
        string="Idle Screen Announcements",
    )

    # ── Lifecycle ─────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("kiosk_token"):
                vals["kiosk_token"] = secrets.token_urlsafe(32)
        return super().create(vals_list)

    def action_regenerate_token(self):
        """Regenerate the kiosk token (invalidates any open tablet sessions)."""
        for cfg in self:
            cfg.kiosk_token = secrets.token_urlsafe(32)

    def action_open_kiosk_url(self):
        """Open this kiosk's URL in a new browser tab."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self.kiosk_url,
            "target": "new",
        }

    def _compute_kiosk_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        for cfg in self:
            if cfg.kiosk_token:
                cfg.kiosk_url = f"{base}/kiosk/{cfg.kiosk_token}"
            else:
                cfg.kiosk_url = ""

    @api.constrains("pin_code")
    def _check_pin_code(self):
        for kiosk in self:
            if not re.fullmatch(r"\d{6}", kiosk.pin_code or ""):
                raise ValidationError(
                    "Instructor PIN must be exactly 6 digits (numbers only)."
                )
