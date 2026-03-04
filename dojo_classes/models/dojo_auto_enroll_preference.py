from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DojoAutoEnrollPreference(models.Model):
    """Per-member, per-template auto-enroll schedule preference.

    Modes
    -----
    permanent  — enroll on the chosen days every week, indefinitely (never removed).
    multiday   — enroll on the chosen days only within the [date_from, date_to] range.
                 Expired preferences are ignored by the session-generation cron.

    active = False  — explicit opt-out: the system will NOT auto-enroll this
                      member into this template's sessions regardless of defaults.

    No record       — backward-compatible default: member is enrolled on every
                      day the template runs (existing behaviour).
    """

    _name = "dojo.course.auto.enroll"
    _description = "Member Auto-Enroll Preference"
    _rec_name = "display_name"

    # ── Core relations ─────────────────────────────────────────────────────
    member_id = fields.Many2one(
        "dojo.member",
        string="Member",
        required=True,
        index=True,
        ondelete="cascade",
    )
    template_id = fields.Many2one(
        "dojo.class.template",
        string="Class Template",
        required=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="template_id.company_id",
        store=True,
        index=True,
    )

    # ── Preferences ────────────────────────────────────────────────────────
    active = fields.Boolean(
        default=True,
        help="False = explicit opt-out: system skips auto-enroll for this member+template.",
    )
    mode = fields.Selection(
        [
            ("permanent", "Never Remove"),
            ("multiday", "Multiday Range"),
        ],
        default="permanent",
        required=True,
        string="Recurrence Mode",
    )
    date_from = fields.Date(
        string="From",
        help="Start of the date range for 'Multiday Range' mode.",
    )
    date_to = fields.Date(
        string="To",
        help="End of the date range (inclusive) for 'Multiday Range' mode.",
    )

    # ── Day-of-week flags (subset of the template's active days) ───────────
    pref_mon = fields.Boolean(string="Mon")
    pref_tue = fields.Boolean(string="Tue")
    pref_wed = fields.Boolean(string="Wed")
    pref_thu = fields.Boolean(string="Thu")
    pref_fri = fields.Boolean(string="Fri")
    pref_sat = fields.Boolean(string="Sat")
    pref_sun = fields.Boolean(string="Sun")

    # ── Computed helpers ───────────────────────────────────────────────────
    display_name = fields.Char(compute="_compute_display_name", store=False)

    @api.depends("member_id", "template_id", "mode")
    def _compute_display_name(self):
        for rec in self:
            member = rec.member_id.name or "?"
            tmpl = rec.template_id.name or "?"
            mode_label = dict(rec._fields["mode"].selection).get(rec.mode, "")
            rec.display_name = f"{member} — {tmpl} ({mode_label})"

    # ── Unique constraint ──────────────────────────────────────────────────
    _dojo_auto_enroll_unique = models.Constraint(
        "unique(member_id, template_id)",
        "A member can only have one auto-enroll preference per class template.",
    )

    # ── ORM hooks ─────────────────────────────────────────────────────────
    @api.constrains("mode", "date_from", "date_to")
    def _check_multiday_dates(self):
        for rec in self:
            if rec.mode == "multiday":
                if not rec.date_from or not rec.date_to:
                    raise ValidationError(
                        "'Multiday Range' mode requires both a From and To date."
                    )
                if rec.date_from > rec.date_to:
                    raise ValidationError(
                        "'From' date must be on or before the 'To' date."
                    )

    # ── Business helpers ───────────────────────────────────────────────────
    def should_enroll_on_date(self, target_date):
        """Return True if this preference allows auto-enrollment on *target_date*.

        Called by the session-generation cron for each member × date combination.
        Returns False  — skip
        Returns True   — enroll
        """
        self.ensure_one()

        # Opted out
        if not self.active:
            return False

        # Multiday: only applies within the [date_from, date_to] range
        if self.mode == "multiday":
            if not self.date_from or not self.date_to:
                return False
            if not (self.date_from <= target_date <= self.date_to):
                return False

        # Check day-of-week flags
        # isoweekday: 0=Mon … 6=Sun  (Python weekday())
        day_map = {
            0: self.pref_mon,
            1: self.pref_tue,
            2: self.pref_wed,
            3: self.pref_thu,
            4: self.pref_fri,
            5: self.pref_sat,
            6: self.pref_sun,
        }
        # If ALL flags are False we treat that as "all days" (safe default)
        any_set = any(day_map.values())
        if not any_set:
            return True
        return day_map[target_date.weekday()]

    def preferred_days_label(self):
        """Human-readable list of selected days for display."""
        self.ensure_one()
        labels = []
        for fname, label in [
            ("pref_mon", "Mon"), ("pref_tue", "Tue"), ("pref_wed", "Wed"),
            ("pref_thu", "Thu"), ("pref_fri", "Fri"), ("pref_sat", "Sat"),
            ("pref_sun", "Sun"),
        ]:
            if getattr(self, fname):
                labels.append(label)
        return ", ".join(labels) if labels else "All days"


# ── Extend dojo.class.template with auto_enroll_pref_ids ──────────────────────

class DojoClassTemplateAutoEnrollExt(models.Model):
    _inherit = "dojo.class.template"

    auto_enroll_pref_ids = fields.One2many(
        "dojo.course.auto.enroll",
        "template_id",
        string="Auto-Enroll Preferences",
    )


# ── Extend dojo.member with auto_enroll_pref_ids ──────────────────────────────

class DojoMemberAutoEnrollExt(models.Model):
    _inherit = "dojo.member"

    auto_enroll_pref_ids = fields.One2many(
        "dojo.course.auto.enroll",
        "member_id",
        string="Auto-Enroll Preferences",
    )
