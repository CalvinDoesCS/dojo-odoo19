import logging
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoMember(models.Model):
    _name = "dojo.member"
    _description = "Dojang Member"
    _inherits = {"res.partner": "partner_id"}
    _inherit = ["mail.thread", "mail.activity.mixin"]

    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    date_of_birth = fields.Date()
    emergency_note = fields.Text()

    # ── Medical Information ───────────────────────────────────────────────
    blood_type = fields.Selection(
        [
            ("A+", "A+"), ("A-", "A-"),
            ("B+", "B+"), ("B-", "B-"),
            ("AB+", "AB+"), ("AB-", "AB-"),
            ("O+", "O+"), ("O-", "O-"),
        ],
        string="Blood Type",
    )
    allergies = fields.Text(string="Allergies")
    medical_notes = fields.Text(string="Medical Notes")

    user_ids = fields.One2many(
        "res.users", "partner_id", string="Linked Users",
        related="partner_id.user_ids",
    )
    has_portal_login = fields.Boolean(compute="_compute_has_portal_login", store=True)
    membership_state = fields.Selection(
        [
            ("lead", "Lead"),
            ("trial", "Trial"),
            ("active", "Active"),
            ("paused", "Paused"),
            ("cancelled", "Cancelled"),
        ],
        default="lead",
        required=True,
        tracking=True,
        string="Membership State",
    )

    def action_set_trial(self):
        self.membership_state = "trial"

    def action_set_active(self):
        self.membership_state = "active"

    def action_set_paused(self):
        self.membership_state = "paused"

    def action_set_cancelled(self):
        self.membership_state = "cancelled"
        # Cancel any active class enrollments so the member no longer holds spots
        if 'dojo.class.enrollment' in self.env:
            enrollments = self.env['dojo.class.enrollment'].sudo().search([
                ('member_id', 'in', self.ids),
                ('status', 'in', ['registered', 'waitlist']),
            ])
            enrollments.write({'status': 'cancelled'})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("partner_id"):
                partner_vals = {}
                for field_name in ("name", "email", "phone", "mobile", "company_id"):
                    if field_name in vals:
                        partner_vals[field_name] = vals.pop(field_name)
                if not partner_vals.get("name"):
                    partner_vals["name"] = "New Member"
                partner_vals["is_student"] = True
                partner = self.env["res.partner"].sudo().create(partner_vals)
                vals["partner_id"] = partner.id
            else:
                # Ensure existing partner is flagged as student, unless they are
                # a pure-guardian (parent-only) member who does not train.
                partner = self.env["res.partner"].browse(vals["partner_id"])
                if not partner.is_student and not partner.is_guardian:
                    partner.sudo().write({"is_student": True})
        return super().create(vals_list)

    @api.depends("partner_id.user_ids")
    def _compute_has_portal_login(self):
        for member in self:
            member.has_portal_login = any(
                user.share for user in member.partner_id.user_ids
            )

    def _get_household(self):
        """Return the household res.partner for this member, or empty recordset."""
        self.ensure_one()
        return self.partner_id.parent_id.filtered("is_household")

    def action_create_household(self):
        """Create a household for this solo member if they don't already have one."""
        self.ensure_one()
        household = self._get_household()
        if household:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('%s is already in household "%s".') % (self.name, household.name),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        household = self.env['res.partner'].sudo().create({
            'name': _("%s's Household") % self.name,
            'is_household': True,
            'is_company': True,
            'company_id': self.company_id.id,
            'primary_guardian_id': self.partner_id.id,
        })
        self.partner_id.parent_id = household
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('Household "%s" created and linked.') % household.name,
                'type': 'success',
                'sticky': False,
            },
        }

    def _grant_portal_access_credentials(self):
        """Grant portal access and return credentials dict for new users, or None
        if the user already existed and just needed a group added."""
        self.ensure_one()
        return self.partner_id._grant_portal_access_credentials()

    def unlink(self):
        """Delete associated user accounts and res.partner contacts when a
        member is removed.

        Deletion order matters:
        1. res.users   — has a RESTRICT FK on partner_id; must go first.
        2. dojo.member — super().unlink() removes the member row.
        3. res.partner — _inherits does NOT auto-delete the parent; we do it
                         explicitly after the member row is gone.

        Household handling:
        - If the member is the only person in a household, the household
          partner is archived as well.
        - If the household has other members and this member is the primary
          guardian, deletion is blocked; staff must assign a new guardian first.
        """
        households_to_archive = self.env['res.partner']
        for member in self:
            household = member.sudo().partner_id.parent_id.filtered('is_household')
            if not household:
                continue
            # Other members in same household (those not being deleted)
            other_members = self.sudo().search([
                ('partner_id.parent_id', '=', household.id),
                ('id', 'not in', self.ids),
            ])
            if other_members:
                if household.primary_guardian_id == member.partner_id:
                    raise UserError(_(
                        'Cannot delete %s: they are the primary guardian of '
                        '"%s" which still has other members. Please assign a '
                        'new primary guardian to the household before deleting '
                        'this member.',
                        member.name, household.name,
                    ))
            else:
                households_to_archive |= household

        partners = self.sudo().mapped("partner_id")

        # res.users — RESTRICT FK on partner_id; must go before the partner.
        users = partners.mapped("user_ids")
        if users:
            users.sudo().unlink()

        # payment.token — RESTRICT FK on partner_id; safe to delete.
        if 'payment.token' in self.env:
            tokens = self.env['payment.token'].sudo().search(
                [('partner_id', 'in', partners.ids)]
            )
            if tokens:
                tokens.unlink()

        res = super().unlink()

        # Archive the partner instead of deleting it: account_move, payment_transaction
        # and many other tables have RESTRICT FKs on res_partner — deleting would
        # orphan invoices and payment history.  Archiving hides the partner from
        # all normal views while keeping the audit trail intact.
        if partners:
            partners.sudo().write({'active': False})
        if households_to_archive:
            households_to_archive.sudo().write({'active': False})
        return res

    def action_grant_portal_access(self):
        """Create or update the member's user account and ensure it belongs to
        the dojo_base.group_dojo_parent_student group, which implies portal access
        and grants the correct dojo-specific ACLs and record-rules."""
        self.ensure_one()
        creds = self._grant_portal_access_credentials()
        if creds:
            message = _(
                "%(name)s now has portal access.\n"
                "Username: %(login)s\n"
                "Temp Password: %(pw)s",
                name=creds["name"],
                login=creds["login"],
                pw=creds["temp_password"],
            )
            sticky = True
        else:
            message = _("%s already has portal access.") % self.partner_id.name
            sticky = False
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": message,
                "title": _("Portal Access"),
                "type": "success",
                "sticky": sticky,
            },
        }
