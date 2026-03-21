import logging

from datetime import datetime, timedelta
from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AiAssistantServiceCrm(models.AbstractModel):
    """Extend the AI assistant service with CRM pipeline intents."""

    _inherit = "ai.assistant.service"

    # ------------------------------------------------------------------
    # Read intent handlers
    # ------------------------------------------------------------------

    def _handle_lead_lookup(self, intent_type, intent_data, resolved_data):
        """Look up CRM leads by name, email, or phone."""
        params = intent_data.get("parameters", {})
        domain = []
        name = params.get("lead_name")
        email = params.get("email")
        phone = params.get("phone")

        if name:
            domain.append("|")
            domain.append(("contact_name", "ilike", name))
            domain.append(("partner_name", "ilike", name))
        if email:
            domain.append(("email_from", "ilike", email))
        if phone:
            domain.append("|")
            domain.append(("phone", "ilike", phone))
            domain.append(("mobile", "ilike", phone))

        if not domain:
            return {"success": False, "message": "Please provide a name, email, or phone to search."}

        leads = self.env["crm.lead"].search(domain, limit=10)
        if not leads:
            return {"success": True, "message": "No leads found matching the search criteria.", "data": []}

        data = []
        for lead in leads:
            data.append({
                "id": lead.id,
                "name": lead.name,
                "contact_name": lead.contact_name,
                "email": lead.email_from,
                "phone": lead.phone or (lead.partner_id.mobile if lead.partner_id else None),
                "stage": lead.stage_id.name,
                "score": lead.dojo_lead_score,
                "trial_attended": lead.trial_attended,
                "is_converted": lead.is_converted,
            })

        return {
            "success": True,
            "message": f"Found {len(data)} lead(s).",
            "data": data,
        }

    def _handle_pipeline_summary(self, intent_type, intent_data, resolved_data):
        """Summarise the CRM pipeline by stage."""
        stages = self.env["crm.stage"].search([], order="sequence")
        summary = []
        total = 0
        for stage in stages:
            count = self.env["crm.lead"].search_count([
                ("stage_id", "=", stage.id),
                ("active", "=", True),
            ])
            summary.append({"stage": stage.name, "count": count})
            total += count

        return {
            "success": True,
            "message": f"Pipeline has {total} active lead(s) across {len(stages)} stages.",
            "data": summary,
        }

    def _handle_trial_schedule(self, intent_type, intent_data, resolved_data):
        """List upcoming trial bookings."""
        params = intent_data.get("parameters", {})
        date_str = params.get("date")

        domain = [
            ("trial_session_id", "!=", False),
            ("trial_attended", "=", False),
            ("trial_session_id.start_datetime", ">", fields.Datetime.now()),
        ]

        if date_str:
            try:
                target = datetime.strptime(date_str, "%Y-%m-%d")
                domain.append(("trial_session_id.start_datetime", ">=", target))
                domain.append(("trial_session_id.start_datetime", "<", target + timedelta(days=1)))
            except ValueError:
                pass

        leads = self.env["crm.lead"].search(domain, limit=20, order="trial_session_id")
        data = []
        for lead in leads:
            data.append({
                "lead": lead.contact_name or lead.partner_name or lead.name,
                "session": lead.trial_session_id.name,
                "datetime": str(lead.trial_session_id.start_datetime),
                "phone": lead.phone or (lead.partner_id.mobile if lead.partner_id else "") or "",
            })

        return {
            "success": True,
            "message": f"{len(data)} upcoming trial(s).",
            "data": data,
        }

    # ------------------------------------------------------------------
    # Write intent handlers
    # ------------------------------------------------------------------

    def _handle_lead_qualify(self, intent_type, intent_data, resolved_data, action_log=None):
        """Move lead to Qualified stage and generate booking link."""
        lead = self._resolve_crm_lead(intent_data)
        if not lead:
            return {"success": False, "message": "Could not find the specified lead."}

        qualified_stage = self.env["crm.stage"].search([("name", "=", "Qualified")], limit=1)
        if not qualified_stage:
            return {"success": False, "message": "Qualified stage not found."}

        if not lead.trial_booking_token:
            lead._generate_trial_tokens()

        old_stage = lead.stage_id.name
        lead.write({"stage_id": qualified_stage.id})

        if action_log:
            action_log.write({
                "undo_data": f'{{"stage_id": {lead.stage_id.id}, "old_stage_name": "{old_stage}"}}',
            })

        return {
            "success": True,
            "message": f"Lead '{lead.contact_name or lead.name}' moved to Qualified. Booking link generated.",
            "data": {"id": lead.id, "booking_url": lead.trial_booking_url},
        }

    def _handle_lead_mark_attended(self, intent_type, intent_data, resolved_data, action_log=None):
        """Mark a lead's trial as attended."""
        lead = self._resolve_crm_lead(intent_data)
        if not lead:
            return {"success": False, "message": "Could not find the specified lead."}

        attended_stage = self.env["crm.stage"].search([("name", "=", "Trial Attended")], limit=1)
        if not attended_stage:
            return {"success": False, "message": "Trial Attended stage not found."}

        old_stage = lead.stage_id.name
        lead.write({
            "stage_id": attended_stage.id,
            "trial_attended": True,
        })

        if action_log:
            action_log.write({
                "undo_data": f'{{"stage_id": {lead.stage_id.id}, "old_stage_name": "{old_stage}"}}',
            })

        return {
            "success": True,
            "message": f"'{lead.contact_name or lead.name}' marked as Trial Attended.",
        }

    def _handle_lead_convert(self, intent_type, intent_data, resolved_data, action_log=None):
        """Convert a CRM lead to a dojo member."""
        lead = self._resolve_crm_lead(intent_data)
        if not lead:
            return {"success": False, "message": "Could not find the specified lead."}

        if lead.is_converted:
            return {
                "success": False,
                "message": f"Lead '{lead.contact_name or lead.name}' is already converted.",
            }

        try:
            lead.action_convert_to_member()
            return {
                "success": True,
                "message": f"Lead '{lead.contact_name or lead.name}' converted to member.",
                "data": {"member_id": lead.dojo_member_id.id if lead.dojo_member_id else None},
            }
        except Exception as exc:
            _logger.error("AI CRM: convert lead %s failed: %s", lead.id, exc)
            return {"success": False, "message": f"Conversion failed: {exc}"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_crm_lead(self, intent_data):
        """Resolve a CRM lead from intent parameters (by ID or name)."""
        params = intent_data.get("parameters", {})
        lead_id = params.get("lead_id")
        lead_name = params.get("lead_name")

        if lead_id:
            lead = self.env["crm.lead"].browse(int(lead_id)).exists()
            if lead:
                return lead

        if lead_name:
            lead = self.env["crm.lead"].search(
                ["|", ("contact_name", "ilike", lead_name), ("partner_name", "ilike", lead_name)],
                limit=1,
            )
            if lead:
                return lead

        return None
