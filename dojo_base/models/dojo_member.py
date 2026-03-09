from odoo import api, fields, models, _
from odoo.exceptions import UserError


class DojoMember(models.Model):
    _name = "dojo.member"
    _description = "Dojo Member"
    _inherits = {"res.partner": "partner_id"}
    _inherit = ["mail.thread", "mail.activity.mixin"]

    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade")
    active = fields.Boolean(default=True)
    household_id = fields.Many2one("dojo.household", tracking=True, index=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    role = fields.Selection(
        [
            ("student", "Student"),
            ("parent", "Parent"),
            ("both", "Student & Parent"),
        ],
        default="student",
        required=True,
        tracking=True,
    )
    date_of_birth = fields.Date()
    emergency_note = fields.Text()
    guardian_for_link_ids = fields.One2many(
        "dojo.guardian.link", "guardian_member_id", string="Guardian Of"
    )
    dependent_link_ids = fields.One2many(
        "dojo.guardian.link", "student_member_id", string="Dependents"
    )
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
                partner = self.env["res.partner"].create(partner_vals)
                vals["partner_id"] = partner.id
        return super().create(vals_list)

    @api.depends("partner_id.user_ids")
    def _compute_has_portal_login(self):
        for member in self:
            member.has_portal_login = any(
                user.share for user in member.partner_id.user_ids
            )

    def action_create_household(self):
        """Create a household for this solo member if they don't already have one."""
        self.ensure_one()
        if self.household_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('%s is already in household "%s".') % (self.name, self.household_id.name),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        household = self.env['dojo.household'].create({
            'name': _("%s's Household") % self.name,
            'company_id': self.company_id.id,
        })
        self.household_id = household
        if self.role in ('parent', 'both'):
            household.primary_guardian_id = self
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('Household "%s" created and linked.') % household.name,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_grant_portal_access(self):
        """Create or update the member's user account and ensure it belongs to
        the dojo_base.group_dojo_parent_student group, which implies portal access
        and grants the correct dojo-specific ACLs and record-rules."""
        self.ensure_one()
        partner = self.partner_id
        if not partner.email:
            raise UserError(_(
                "The member must have an email address before portal access can be granted."
            ))
        group_parent = self.env.ref("dojo_base.group_dojo_parent_student")
        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", partner.id)], limit=1
        )
        if user:
            if group_parent not in user.groups_id:
                user.sudo().write({"groups_id": [(4, group_parent.id)]})
        else:
            user = self.env["res.users"].sudo().create({
                "partner_id": partner.id,
                "login": partner.email,
                "name": partner.name,
                "groups_id": [(4, group_parent.id)],
            })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("%s now has portal access.") % partner.name,
                "type": "success",
                "sticky": False,
            },
        }
