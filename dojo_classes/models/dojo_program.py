from odoo import api, fields, models


class DojoProgram(models.Model):
    _name = "dojo.program"
    _description = "Dojang Program / Curriculum"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(help="Short code, e.g. BJJ, MT, KIDS")
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    active = fields.Boolean(default=True)
    description = fields.Html()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    style_id = fields.Many2one(
        "dojo.martial.art.style",
        string="Martial Art Style",
        ondelete="set null",
    )

    # ── Related records ───────────────────────────────────────────────────
    template_ids = fields.One2many(
        "dojo.class.template", "program_id", string="Class Templates"
    )
    template_count = fields.Integer(
        compute="_compute_template_count", store=True
    )

    # ── Computed ───────────────────────────────────────────────────────────
    @api.depends("template_ids")
    def _compute_template_count(self):
        for rec in self:
            rec.template_count = len(rec.template_ids)

    # ── Actions ────────────────────────────────────────────────────────────
    def action_view_templates(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Class Templates",
            "res_model": "dojo.class.template",
            "view_mode": "list,form",
            "domain": [("program_id", "=", self.id)],
            "context": {"default_program_id": self.id},
        }
