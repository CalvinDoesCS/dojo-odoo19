import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DojoConvertLeadWizard(models.TransientModel):
    """
    Convert a crm.lead into a dojo.member.
    Pre-fills member fields from the lead's partner data; creates the member +
    household (if needed) and optionally creates a subscription.
    Moves the lead to the Converted stage and archives it.
    """

    _name = "dojo.convert.lead.wizard"
    _description = "Convert CRM Lead to Dojang Member"

    # ------------------------------------------------------------------
    # Source
    # ------------------------------------------------------------------

    lead_id = fields.Many2one(
        "crm.lead",
        string="Lead",
        required=True,
        readonly=True,
        ondelete="cascade",
    )

    # ------------------------------------------------------------------
    # Member fields (pre-filled from lead partner)
    # ------------------------------------------------------------------

    first_name = fields.Char(string="First Name", required=True)
    last_name = fields.Char(string="Last Name")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")
    mobile = fields.Char(string="Mobile")
    date_of_birth = fields.Date(string="Date of Birth")
    role = fields.Selection(
        [("student", "Student"), ("parent", "Parent / Guardian"), ("both", "Both")],
        string="Role",
        default="student",
        required=True,
    )

    # ------------------------------------------------------------------
    # Guardian / Household
    # ------------------------------------------------------------------

    create_household = fields.Boolean(
        string="Create New Household",
        default=True,
    )
    household_id = fields.Many2one(
        "dojo.household",
        string="Existing Household",
    )
    guardian_name = fields.Char(
        string="Guardian / Parent Name",
        help="Required when creating a new household for a student member.",
    )
    guardian_email = fields.Char(string="Guardian Email")
    guardian_mobile = fields.Char(string="Guardian Mobile / Phone")

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    create_subscription = fields.Boolean(
        string="Create Subscription",
        default=True,
    )
    plan_id = fields.Many2one(
        "dojo.subscription.plan",
        string="Subscription Plan",
        domain="[('active', '=', True)]",
    )
    subscription_start_date = fields.Date(
        string="Start Date",
        default=fields.Date.today,
    )

    # ------------------------------------------------------------------
    # Defaults from lead
    # ------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lead_id = self.env.context.get("default_lead_id") or self.env.context.get("active_id")
        if lead_id:
            lead = self.env["crm.lead"].browse(lead_id)
            partner = lead.partner_id
            if partner:
                name_parts = (partner.name or "").split(" ", 1)
                res["first_name"] = name_parts[0]
                res["last_name"] = name_parts[1] if len(name_parts) > 1 else ""
                res["email"] = partner.email or lead.email_from or ""
                res["phone"] = partner.phone or lead.phone or ""
                res["mobile"] = partner.mobile or lead.mobile or ""
            else:
                name_parts = (lead.contact_name or lead.partner_name or "").split(" ", 1)
                res["first_name"] = name_parts[0]
                res["last_name"] = name_parts[1] if len(name_parts) > 1 else ""
                res["email"] = lead.email_from or ""
                res["phone"] = lead.phone or ""
                res["mobile"] = lead.mobile or ""
            res["lead_id"] = lead.id
        return res

    # ------------------------------------------------------------------
    # Convert action
    # ------------------------------------------------------------------

    def action_convert(self):
        self.ensure_one()
        lead = self.lead_id

        if lead.dojo_member_id:
            raise UserError(_("This lead has already been converted to a member."))

        # ---- Build member name ----
        full_name = " ".join(filter(None, [self.first_name, self.last_name]))

        # ---- Resolve or create res.partner ----
        partner = lead.partner_id
        if not partner:
            partner = self.env["res.partner"].create(
                {
                    "name": full_name,
                    "email": self.email,
                    "phone": self.phone,
                    "mobile": self.mobile,
                    "company_type": "person",
                }
            )
        else:
            partner.write(
                {
                    "name": full_name,
                    "email": self.email or partner.email,
                    "phone": self.phone or partner.phone,
                    "mobile": self.mobile or partner.mobile,
                }
            )

        # ---- Resolve / create household ----
        household = None
        if self.create_household:
            if not self.guardian_name and self.role == "student":
                raise UserError(
                    _("Please provide a guardian name when creating a household for a student.")
                )
            # Create guardian partner
            if self.guardian_name:
                guardian_partner = self.env["res.partner"].create(
                    {
                        "name": self.guardian_name,
                        "email": self.guardian_email,
                        "mobile": self.guardian_mobile,
                        "company_type": "person",
                    }
                )
                guardian_member = self.env["dojo.member"].create(
                    {
                        "partner_id": guardian_partner.id,
                        "role": "parent",
                        "membership_state": "active",
                    }
                )
                household = self.env["dojo.household"].create(
                    {
                        "name": f"{self.last_name or full_name} Household",
                        "primary_guardian_id": guardian_member.id,
                    }
                )
            else:
                household = self.env["dojo.household"].create(
                    {"name": f"{self.last_name or full_name} Household"}
                )
        elif self.household_id:
            household = self.household_id

        # ---- Create dojo.member ----
        member_vals = {
            "partner_id": partner.id,
            "role": self.role,
            "date_of_birth": self.date_of_birth,
            "membership_state": "active",
        }
        if household:
            member_vals["household_id"] = household.id

        member = self.env["dojo.member"].create(member_vals)

        # Link guardian if created
        if household and household.primary_guardian_id and self.role == "student":
            self.env["dojo.guardian.link"].create(
                {
                    "household_id": household.id,
                    "guardian_member_id": household.primary_guardian_id.id,
                    "student_member_id": member.id,
                    "relation": "guardian",
                    "is_primary": True,
                }
            )
            # Update household member list
            household.primary_guardian_id.household_id = household.id

        # ---- Create subscription ----
        if self.create_subscription and self.plan_id:
            plan = self.plan_id
            start = self.subscription_start_date or fields.Date.today()
            self.env["dojo.member.subscription"].create(
                {
                    "member_id": member.id,
                    "plan_id": plan.id,
                    "start_date": start,
                    "next_billing_date": start,  # first invoice covers start → start+period
                    "state": "active",
                }
            )

        # ---- Link back to lead ----
        lead.dojo_member_id = member.id
        lead.trial_attended = True

        # ---- Move lead to Converted stage ----
        converted_stage = self.env["crm.stage"].search(
            [("name", "=", "Converted")], limit=1
        )
        if converted_stage:
            lead.stage_id = converted_stage.id

        lead.active = False  # archive

        _logger.info(
            "dojo_crm: lead %d converted to member %d (%s)",
            lead.id,
            member.id,
            member.display_name,
        )

        # Open the new member record
        return {
            "type": "ir.actions.act_window",
            "name": _("New Member"),
            "res_model": "dojo.member",
            "res_id": member.id,
            "view_mode": "form",
        }
