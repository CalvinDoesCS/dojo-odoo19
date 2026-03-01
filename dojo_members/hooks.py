"""
post_init_hook for dojo_members.

After install (which creates the ir.sequence for dojo.member), align the
sequence's number_next so it starts above the highest already-assigned
member_number, preventing collisions with members numbered via SQL backfill.
"""
import re


def post_init_hook(env):
    """Advance the dojo.member sequence past any already-assigned numbers."""
    sequence = env["ir.sequence"].search([("code", "=", "dojo.member")], limit=1)
    if not sequence:
        return

    # Find the highest numeric suffix among existing member_numbers (e.g. "DJ-00007" → 7)
    members = env["dojo.member"].search([("member_number", "!=", False)])
    max_num = 0
    for m in members:
        match = re.search(r"(\d+)$", m.member_number or "")
        if match:
            max_num = max(max_num, int(match.group(1)))

    if max_num >= sequence.number_next:
        sequence.number_next = max_num + 1
