from odoo import api, fields, models


class DojoMember(models.Model):
    _inherit = "dojo.member"

    member_number = fields.Char(
        string="Member Number",
        copy=False,
        readonly=True,
        index=True,
        help="Auto-generated unique member identifier (e.g. DJ-00001). Used for barcode/kiosk check-in.",
    )

    emergency_contact_ids = fields.One2many(
        "dojo.emergency.contact", "member_id", string="Emergency Contacts"
    )

    _dojo_member_number_unique = models.Constraint(
        "unique(member_number)",
        "Member Number must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if not record.member_number:
                record.member_number = self.env["ir.sequence"].next_by_code("dojo.member") or "/"
        return records
