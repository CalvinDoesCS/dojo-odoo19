"""
Extends dojo.class.session with an import-placeholder flag so that
sessions auto-created during attendance migration can be identified
and cleaned up post-migration if needed.
"""
from odoo import fields, models


class DojoClassSessionMigrationExt(models.Model):
    _inherit = "dojo.class.session"

    is_import_placeholder = fields.Boolean(
        string="Import Placeholder",
        default=False,
        index=True,
        help=(
            "Set to True for sessions auto-created during SparkMembership "
            "attendance migration. These are not real scheduled sessions and "
            "can be reviewed and cleaned up after migration."
        ),
    )
