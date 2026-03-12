from datetime import timedelta

from odoo import api, fields, models, _


class DojoMember(models.Model):
    _inherit = "dojo.member"

    def _get_next_belt_rank(self):
        """Return the belt rank immediately above the member's current rank,
        or the lowest rank if the member has no rank yet.  Returns False if
        the member is already at the highest rank."""
        self.ensure_one()
        all_ranks = self.env["dojo.belt.rank"].search(
            [("active", "=", True), ("company_id", "in", [self.company_id.id, False])],
            order="sequence asc",
        )
        if not all_ranks:
            return False
        if not self.current_rank_id:
            return all_ranks[0]
        for i, rank in enumerate(all_ranks):
            if rank == self.current_rank_id:
                return all_ranks[i + 1] if i + 1 < len(all_ranks) else False
        return False

    def _create_belt_test_invite(self, next_rank):
        """Create a scheduled belt test + registration for *self* targeting *next_rank*.
        If *next_rank* has a testing_fee_product_id, also post an invoice."""
        self.ensure_one()
        test_date = fields.Date.today() + timedelta(days=7)

        test = self.env["dojo.belt.test"].create(
            {
                "name": _("Auto: %s — %s", self.name, next_rank.name),
                "test_date": test_date,
                "state": "scheduled",
                "company_id": self.company_id.id,
            }
        )
        self.env["dojo.belt.test.registration"].create(
            {
                "test_id": test.id,
                "member_id": self.id,
                "target_rank_id": next_rank.id,
                "result": "pending",
            }
        )

        # Optional testing-fee invoice
        if next_rank.testing_fee_product_id:
            product = next_rank.testing_fee_product_id
            move = self.env["account.move"].create(
                {
                    "move_type": "out_invoice",
                    "partner_id": self.partner_id.id,
                    "invoice_date": fields.Date.today(),
                    "company_id": self.company_id.id,
                    "invoice_line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": product.id,
                                "quantity": 1,
                                "name": product.name,
                                "price_unit": product.lst_price,
                            },
                        )
                    ],
                }
            )
            move.action_post()

        self.test_invite_pending = True

        # Create an instructor todo so the instructor knows to review/schedule the test
        self.env["dojo.member"]._create_instructor_todo(
            self._get_instructor_users_for_member(),
            "🥋 Belt test ready: %s → %s" % (self.name, next_rank.name),
            deadline=test_date,
            description=(
                "Auto-generated belt test on %s. Review, schedule, and confirm the student."
                % fields.Date.to_string(test_date)
            ),
        )
        return test

    @api.model
    def _cron_check_belt_eligibility(self):
        """Daily cron: for every active member without a pending test invite,
        check if their attendance since their last rank award has reached the
        threshold configured on the next belt rank.  When it does, auto-create
        a belt test event + registration (and optionally an invoice)."""
        members = self.search(
            [
                ("membership_state", "=", "active"),
                ("test_invite_pending", "=", False),
            ]
        )
        for member in members:
            next_rank = member._get_next_belt_rank()
            if not next_rank:
                continue
            threshold = next_rank.attendance_threshold
            if not threshold:
                continue
            if member.attendance_since_last_rank >= threshold:
                member._create_belt_test_invite(next_rank)
