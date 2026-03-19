"""Null out household_id FK values that reference the old dojo_household table.

The field now points to res.partner; old IDs are invalid.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("Clearing stale household_id values on dojo_member_subscription")
    cr.execute("""
        UPDATE dojo_member_subscription
           SET household_id = NULL
         WHERE household_id IS NOT NULL
           AND household_id NOT IN (SELECT id FROM res_partner)
    """)
