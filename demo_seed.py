"""
Full demo seed — creates all demo data from scratch.

Run:
  DB_PASS=$(cat odoo_pg_pass)
  docker compose exec -T web odoo shell -d odoo19 --db_host db --db_port 5432 \\
    --db_user odoo --db_password "$DB_PASS" < demo_seed.py

Accounts (password: dojo@2026):
  instructor1@demo.com  Alex Johnson   Head Instructor
  instructor2@demo.com  Sam Rivera     Assistant Instructor
  parent1@demo.com      Mary Smith     Smith Household guardian
  parent2@demo.com      Bob Jones      Jones Household guardian
  student1@demo.com     Jordan Smith   Kids BJJ, Smith HH
  student2@demo.com     Casey Smith    Kids BJJ, Smith HH
  student3@demo.com     Taylor Jones   Kids BJJ, Jones HH
  student4@demo.com     Morgan Jones   Kids BJJ, Jones HH
  student5@demo.com     Riley Lee      Adult BJJ, standalone
"""
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

today = date.today()
PASSWORD = "dojo@2026"

# ── Cleanup: remove any prior demo seed data ─────────────────────────────
print("Cleaning up prior demo data...")
DEMO_LOGINS = [
    "instructor1@demo.com", "instructor2@demo.com",
    "parent1@demo.com",     "parent2@demo.com",
    "student1@demo.com",    "student2@demo.com",
    "student3@demo.com",    "student4@demo.com",
    "student5@demo.com",
]
existing_users = env["res.users"].search([("login", "in", DEMO_LOGINS)])
existing_partners = existing_users.mapped("partner_id")
# Remove cascading records
env["dojo.class.enrollment"].search([]).unlink()
env["dojo.class.session"].search([]).unlink()
# Clean up subscription invoices before deleting subscriptions
_all_subs = env["dojo.member.subscription"].search([])
if _all_subs:
    _sub_invs = env["account.move"].sudo().search([
        "|",
        ("subscription_id", "in", _all_subs.ids),
        ("dojo_subscription_ids", "in", _all_subs.ids),
    ])
    if _sub_invs:
        _sub_invs.mapped("line_ids").remove_move_reconcile()
        _sub_invs.filtered(lambda m: m.state == "posted").button_cancel()
        _sub_invs.unlink()
# Clean up payments for demo partners (now that their invoices are gone)
if existing_partners:
    _demo_pmts = env["account.payment"].sudo().search([
        ("partner_id", "in", existing_partners.ids)
    ])
    if _demo_pmts:
        _pmt_moves = _demo_pmts.mapped("move_id")
        if _pmt_moves:
            _pmt_moves.mapped("line_ids").remove_move_reconcile()
            _pmt_moves.filtered(lambda m: m.state == "posted").button_cancel()
            _pmt_moves.unlink()  # cascades to account.payment
env["dojo.member.subscription"].search([]).unlink()
env["dojo.subscription.plan"].search([]).unlink()
env["dojo.class.template"].search([]).unlink()
env["dojo.program"].search([]).unlink()
env["dojo.member.rank"].search([]).unlink()
env["dojo.belt.test.registration"].search([]).unlink()
env["dojo.belt.test"].search([]).unlink()
env["dojo.belt.rank"].search([]).unlink()
# Households are now res.partner records — cleaned up via partner cascade
demo_members = env["dojo.member"].search([("partner_id", "in", existing_partners.ids)])
# Clear payment_transaction.token_id FKs to allow token deletion (RESTRICT constraint)
if "payment.token" in env:
    demo_tokens = env["payment.token"].sudo().search([("partner_id", "in", existing_partners.ids)])
    if demo_tokens:
        env.cr.execute(
            "UPDATE payment_transaction SET token_id = NULL WHERE token_id IN %s",
            (tuple(demo_tokens.ids),)
        )
        demo_tokens.unlink()
demo_members.unlink()
# demo_members.unlink() cascades and removes parent/student users already.
# Delete instructor profiles first, then remove any remaining users (instructors).
env["dojo.instructor.profile"].search([("user_id", "in", existing_users.ids)]).unlink()
remaining_users = env["res.users"].search([("login", "in", DEMO_LOGINS)])
if remaining_users:
    # Clear hr.employee.user_id FK (RESTRICT) before deleting instructor users
    env.cr.execute(
        "UPDATE hr_employee SET user_id = NULL WHERE user_id IN %s",
        (tuple(remaining_users.ids),)
    )
    remaining_users.unlink()
print("  cleanup done.")

group_instructor     = env.ref("dojo_base.group_dojo_instructor")
group_user           = env.ref("base.group_user")
group_parent_student = env.ref("dojo_base.group_dojo_parent_student")


def make_user(name, login, groups):
    u = env["res.users"].create({
        "name": name, "login": login, "email": login,
        "group_ids": [(6, 0, [g.id for g in groups])],
    })
    u.password = PASSWORD
    return u


# ── 1. Instructors ────────────────────────────────────────────────────────
print("Creating instructors...")
instr1_user = make_user("Alex Johnson", "instructor1@demo.com", [group_instructor, group_user])
instr2_user = make_user("Sam Rivera",   "instructor2@demo.com", [group_instructor, group_user])
instr1 = env["dojo.instructor.profile"].create({
    "name": "Alex Johnson", "user_id": instr1_user.id,
    "partner_id": instr1_user.partner_id.id,
    "bio": "Head instructor with 15 years of BJJ experience.",
})
instr2 = env["dojo.instructor.profile"].create({
    "name": "Sam Rivera", "user_id": instr2_user.id,
    "partner_id": instr2_user.partner_id.id,
    "bio": "Assistant instructor specialising in advanced sparring and competition prep.",
})

# ── 2. Parents (guardians — res.partner only, no dojo.member) ─────────────
print("Creating parents...")
p1_user = make_user("Mary Smith", "parent1@demo.com", [group_parent_student])
p2_user = make_user("Bob Jones",  "parent2@demo.com", [group_parent_student])
p1_partner = p1_user.partner_id
p1_partner.write({"is_guardian": True, "phone": "555-0101"})
p2_partner = p2_user.partner_id
p2_partner.write({"is_guardian": True, "phone": "555-0102"})

# ── 3. Students ───────────────────────────────────────────────────────────
print("Creating students...")
students_raw = [
    # (name, login, dob, phone, is_minor, is_guardian)
    ("Jordan Smith",  "student1@demo.com", date(2014,  3, 15), "555-0111", True,  False),
    ("Casey Smith",   "student2@demo.com", date(2016,  7, 22), "555-0112", True,  False),
    ("Taylor Jones",  "student3@demo.com", date(2013, 11,  5), "555-0113", True,  False),
    ("Morgan Jones",  "student4@demo.com", date(2015,  4, 18), "555-0114", True,  False),
    ("Riley Lee",     "student5@demo.com", date(2005,  8, 30), "555-0115", False, True),
]
student_members = []
for name, login, dob, phone, is_minor, is_guardian in students_raw:
    u = make_user(name, login, [group_parent_student])
    m = env["dojo.member"].create({
        "partner_id": u.partner_id.id,
        "date_of_birth": dob, "membership_state": "active",
        "phone": phone, "email": login,
    })
    u.partner_id.write({"is_minor": is_minor, "is_guardian": is_guardian})
    student_members.append(m)
s1, s2, s3, s4, s5 = student_members

# ── 4. Households (res.partner with is_household=True) ───────────────────
print("Creating households...")
smith_hh = env["res.partner"].create({
    "name": "Smith Household", "is_household": True, "is_company": True,
    "primary_guardian_id": p1_partner.id,
})
for m in [s1, s2]:
    m.partner_id.parent_id = smith_hh
p1_partner.parent_id = smith_hh

jones_hh = env["res.partner"].create({
    "name": "Jones Household", "is_household": True, "is_company": True,
    "primary_guardian_id": p2_partner.id,
})
for m in [s3, s4]:
    m.partner_id.parent_id = jones_hh
p2_partner.parent_id = jones_hh

# Riley Lee — solo household (every member needs one for billing)
lee_hh = env["res.partner"].create({
    "name": "Lee Household", "is_household": True, "is_company": True,
    "primary_guardian_id": s5.partner_id.id,
})
s5.partner_id.parent_id = lee_hh

# ── 5. Belt ranks ─────────────────────────────────────────────────────────
print("Creating belt ranks...")
rank_defs = [
    ("White Belt",  10,  "#607d8b"),
    ("Yellow Belt", 20,  "#f9a825"),
    ("Orange Belt", 30,  "#ef6c00"),
    ("Green Belt",  40,  "#2e7d32"),
    ("Blue Belt",   50,  "#1565c0"),
    ("Purple Belt", 60,  "#6a1b9a"),
    ("Brown Belt",  70,  "#4e342e"),
    ("Black Belt",  80,  "#212529"),
]
ranks = {}
for rname, seq, color in rank_defs:
    ranks[rname] = env["dojo.belt.rank"].create({
        "name": rname, "sequence": seq, "color": color, "active": True,
    })

# ── 6. Programs ───────────────────────────────────────────────────────────
print("Creating programs...")
prog_kids = env["dojo.program"].create({
    "name": "BJJ Kids",
    "code": "KIDS",
    "sequence": 10,
    "color": 3,
    "description": "<p>Brazilian Jiu-Jitsu program for children aged 5\u201316. "
                   "Focuses on discipline, self-defence and age-appropriate technique.</p>",
})
prog_adults = env["dojo.program"].create({
    "name": "BJJ Adults",
    "code": "BJJ",
    "sequence": 20,
    "color": 4,
    "description": "<p>Brazilian Jiu-Jitsu program for adults (17+). "
                   "Covers fundamentals through to advanced competition preparation.</p>",
})
prog_kids.belt_rank_ids = [(6, 0, [
    ranks["White Belt"].id, ranks["Yellow Belt"].id,
    ranks["Orange Belt"].id, ranks["Green Belt"].id,
])]
prog_adults.belt_rank_ids = [(6, 0, [
    ranks["White Belt"].id,  ranks["Yellow Belt"].id,
    ranks["Orange Belt"].id, ranks["Green Belt"].id,
    ranks["Blue Belt"].id,   ranks["Purple Belt"].id,
    ranks["Brown Belt"].id,  ranks["Black Belt"].id,
])]

# ── 7. Belt rank history ──────────────────────────────────────────────────
print("Assigning belt rank history...")
env["dojo.member.rank"].create({"member_id": s1.id, "rank_id": ranks["White Belt"].id,  "date_awarded": today - timedelta(days=180), "awarded_by": instr1.id})
env["dojo.member.rank"].create({"member_id": s2.id, "rank_id": ranks["White Belt"].id,  "date_awarded": today - timedelta(days=120), "awarded_by": instr1.id})
env["dojo.member.rank"].create({"member_id": s3.id, "rank_id": ranks["White Belt"].id,  "date_awarded": today - timedelta(days=240), "awarded_by": instr1.id})
env["dojo.member.rank"].create({"member_id": s3.id, "rank_id": ranks["Yellow Belt"].id, "date_awarded": today - timedelta(days=90),  "awarded_by": instr1.id})
env["dojo.member.rank"].create({"member_id": s4.id, "rank_id": ranks["White Belt"].id,  "date_awarded": today - timedelta(days=150), "awarded_by": instr1.id})
env["dojo.member.rank"].create({"member_id": s5.id, "rank_id": ranks["White Belt"].id,  "date_awarded": today - timedelta(days=365), "awarded_by": instr2.id})
env["dojo.member.rank"].create({"member_id": s5.id, "rank_id": ranks["Yellow Belt"].id, "date_awarded": today - timedelta(days=270), "awarded_by": instr2.id})
env["dojo.member.rank"].create({"member_id": s5.id, "rank_id": ranks["Orange Belt"].id, "date_awarded": today - timedelta(days=120), "awarded_by": instr2.id})
env["dojo.member.rank"].create({"member_id": s5.id, "rank_id": ranks["Green Belt"].id,  "date_awarded": today - timedelta(days=30),  "awarded_by": instr2.id})

# ── 8. Class templates (linked to programs) ───────────────────────────────
print("Creating class templates...")
tmpl_little = env["dojo.class.template"].create({
    "name": "Little Champions", "code": "KIDS-BEG",
    "program_id": prog_kids.id, "level": "beginner",
    "duration_minutes": 60, "max_capacity": 12,
    "recurrence_active": True,
    "recurrence_time": 16.0,          # 4:00 PM
    "rec_mon": True, "rec_wed": True,  # Mon & Wed
    "recurrence_start_date": date(2026, 1, 12),
    "recurrence_instructor_id": instr1.id,
    "instructor_profile_ids": [(4, instr1.id)],
    "course_member_ids": [(6, 0, [s1.id, s2.id])],  # Jordan & Casey
    "description": "Foundational BJJ for younger kids (ages 5\u201310). Basic movements, escapes and positional control.",
})
tmpl_youth = env["dojo.class.template"].create({
    "name": "Youth Techniques", "code": "KIDS-INT",
    "program_id": prog_kids.id, "level": "intermediate",
    "duration_minutes": 75, "max_capacity": 12,
    "recurrence_active": True,
    "recurrence_time": 16.5,          # 4:30 PM
    "rec_tue": True, "rec_thu": True,  # Tue & Thu
    "recurrence_start_date": date(2026, 1, 12),
    "recurrence_instructor_id": instr1.id,
    "instructor_profile_ids": [(4, instr1.id)],
    "course_member_ids": [(6, 0, [s3.id, s4.id])],  # Taylor & Morgan
    "description": "Intermediate BJJ for older kids and teens (ages 10\u201316). Sweeps, submissions and live drilling.",
})
tmpl_adult_fund = env["dojo.class.template"].create({
    "name": "Adult Fundamentals", "code": "ADV-BEG",
    "program_id": prog_adults.id, "level": "beginner",
    "duration_minutes": 60, "max_capacity": 15,
    "recurrence_active": True,
    "recurrence_time": 18.0,                        # 6:00 PM
    "rec_mon": True, "rec_wed": True, "rec_fri": True,  # Mon, Wed & Fri
    "recurrence_start_date": date(2026, 1, 12),
    "recurrence_instructor_id": instr1.id,
    "instructor_profile_ids": [(4, instr1.id)],
    "course_member_ids": [(6, 0, [s5.id])],  # Riley
    "description": "Entry-level adult BJJ. Perfect for beginners with no prior grappling experience.",
})
tmpl_adv = env["dojo.class.template"].create({
    "name": "Advanced Sparring", "code": "ADV-ADV",
    "program_id": prog_adults.id, "level": "advanced",
    "duration_minutes": 90, "max_capacity": 8,
    "recurrence_active": True,
    "recurrence_time": 19.5,          # 7:30 PM
    "rec_tue": True, "rec_thu": True,  # Tue & Thu
    "recurrence_start_date": date(2026, 1, 12),
    "recurrence_instructor_id": instr2.id,
    "instructor_profile_ids": [(4, instr2.id)],
    "course_member_ids": [(6, 0, [s5.id])],  # Riley
    "description": "Competition-focused sparring and advanced technique for experienced students.",
})

# ── 9. Subscription plans (program-based) ────────────────────────────────
print("Creating subscription plans...")
currency = env.company.currency_id

plan_kids = env["dojo.subscription.plan"].create({
    "name": "Kids BJJ Monthly", "code": "KIDS-MTH",
    "plan_type": "program", "program_id": prog_kids.id,
    "billing_period": "monthly", "price": 80.00, "initial_fee": 50.00,
    "currency_id": currency.id, "unlimited_sessions": True,
    "max_sessions_per_week": 3,
    "description": "Unlimited BJJ Kids classes, up to 3 sessions per week.",
})
plan_adult = env["dojo.subscription.plan"].create({
    "name": "Adult BJJ Monthly", "code": "ADV-MTH",
    "plan_type": "program", "program_id": prog_adults.id,
    "billing_period": "monthly", "price": 120.00, "initial_fee": 50.00,
    "currency_id": currency.id, "unlimited_sessions": False,
    "max_sessions_per_week": 5, "credits_per_period": 12,
    "description": "12 credits per month. Access to all adult BJJ classes, up to 5 sessions per week.",
})
env["dojo.subscription.plan"].create({
    "name": "Private Lessons", "code": "PRIV-MTH",
    "plan_type": "course", "billing_period": "monthly",
    "price": 250.00, "initial_fee": 0.00,
    "currency_id": currency.id, "unlimited_sessions": False,
    "credits_per_period": 4, "max_sessions_per_week": 1,
    "allowed_template_ids": [(4, tmpl_adv.id)],
    "description": "4 credits per month. Advanced Sparring sessions only.",
})

# ── 10. Member subscriptions ──────────────────────────────────────────────
print("Creating member subscriptions...")
sub_start = date(2026, 1, 12)   # subscriptions started Jan 12
sub_next  = date(2026, 1, 12)   # will be advanced by invoice generation

def make_sub(member, plan, note):
    sub = env["dojo.member.subscription"].create({
        "member_id": member.id, "plan_id": plan.id,
        "start_date": sub_start, "next_billing_date": sub_next,
        "state": "draft", "company_id": env.company.id, "note": note,
    })
    # write() to 'active' triggers _issue_period_credits() for credit-based plans
    sub.write({"state": "active"})
    print(f"  {member.name} \u2192 {plan.name}")
    return sub

sub_s1 = make_sub(s1, plan_kids,  "Jordan Smith \u2014 Kids BJJ")
sub_s2 = make_sub(s2, plan_kids,  "Casey Smith \u2014 Kids BJJ")
sub_s3 = make_sub(s3, plan_kids,  "Taylor Jones \u2014 Kids BJJ")
sub_s4 = make_sub(s4, plan_kids,  "Morgan Jones \u2014 Kids BJJ")
sub_s5 = make_sub(s5, plan_adult, "Riley Lee \u2014 Adult BJJ")

# ── 11. Seed invoices (Jan 12 → Mar 12 billing cycles) ──────────────────
# Three monthly cycles: Jan 12 (paid), Feb 12 (paid), Mar 12 (open/current).
# Household billing is consolidated: Smith HH (s1+s2 → Mary Smith),
# Jones HH (s3+s4 → Bob Jones), Riley Lee is invoiced directly.
print("Seeding subscription invoices...")

_bank_journal = env["account.journal"].search(
    [("type", "in", ["bank", "cash"])], limit=1
)
_membership_product = env.ref(
    "dojo_subscriptions.product_membership_subscription", raise_if_not_found=False
)


def _inv_lines(plan, period_start, include_fee=False):
    """Return (0,0,{}) invoice line tuples for one subscription plan + period."""
    period_end = period_start + relativedelta(months=1) - relativedelta(days=1)
    date_range = "{} \u2013 {}".format(
        period_start.strftime("%-d %b %Y"), period_end.strftime("%-d %b %Y")
    )
    lines = []
    if include_fee and plan.initial_fee:
        fee = {
            "name": f"{plan.name} \u2013 Enrollment Fee",
            "quantity": 1.0,
            "price_unit": plan.initial_fee,
        }
        if _membership_product:
            fee["product_id"] = _membership_product.id
        lines.append((0, 0, fee))
    rec = {
        "name": f"{plan.name} \u2013 Monthly Membership ({date_range})",
        "quantity": 1.0,
        "price_unit": plan.price,
    }
    if _membership_product:
        rec["product_id"] = _membership_product.id
    lines.append((0, 0, rec))
    return lines


def _register_payment(invoice):
    """Reconcile a demo invoice as fully paid via a bank payment."""
    payment = env["account.payment"].sudo().create({
        "payment_type": "inbound",
        "partner_type": "customer",
        "partner_id": invoice.partner_id.id,
        "amount": invoice.amount_total,
        "currency_id": invoice.currency_id.id,
        "date": invoice.invoice_date,
        "journal_id": _bank_journal.id,
    })
    payment.action_post()
    inv_recv = invoice.line_ids.filtered(
        lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
    )
    pay_recv = payment.move_id.line_ids.filtered(
        lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
    )
    if inv_recv and pay_recv:
        (inv_recv + pay_recv).reconcile()


def _make_inv(partner, subs_list, line_vals, inv_date, paid=True):
    """Create, post, and optionally pay a subscription invoice."""
    is_household = len(subs_list) > 1
    vals = {
        "move_type": "out_invoice",
        "partner_id": partner.id,
        "invoice_date": inv_date,
        "invoice_date_due": inv_date + relativedelta(days=7),
        "company_id": env.company.id,
        "invoice_line_ids": line_vals,
    }
    if is_household:
        vals["dojo_subscription_ids"] = [(6, 0, [s.id for s in subs_list])]
    else:
        vals["subscription_id"] = subs_list[0].id
    inv = env["account.move"].sudo().create(vals)
    inv.action_post()
    for sub in subs_list:
        sub.last_invoice_id = inv
    status = "paid"
    if paid:
        _register_payment(inv)
    else:
        status = "open"
    print(f"    {inv.name}  {inv_date}  {partner.name}  ${inv.amount_total:.2f}  [{status}]")
    return inv


_billing_cycles = [
    (date(2026, 1, 12), True),   # Jan \u2014 paid
    (date(2026, 2, 12), True),   # Feb \u2014 paid
    (date(2026, 3, 12), False),  # Mar \u2014 open (current)
]

for _cycle_num, (_inv_date, _paid) in enumerate(_billing_cycles):
    _is_first = (_cycle_num == 0)

    # Smith Household: Mary Smith billed for Jordan (s1) + Casey (s2)
    _smith_lines = (
        _inv_lines(plan_kids, _inv_date, include_fee=_is_first)  # s1 lines
        + _inv_lines(plan_kids, _inv_date, include_fee=False)    # s2 lines
    )
    _make_inv(p1_partner, [sub_s1, sub_s2], _smith_lines, _inv_date, _paid)

    # Jones Household: Bob Jones billed for Taylor (s3) + Morgan (s4)
    _jones_lines = (
        _inv_lines(plan_kids, _inv_date, include_fee=_is_first)  # s3 lines
        + _inv_lines(plan_kids, _inv_date, include_fee=False)    # s4 lines
    )
    _make_inv(p2_partner, [sub_s3, sub_s4], _jones_lines, _inv_date, _paid)

    # Riley Lee: standalone (Adult BJJ)
    _riley_lines = _inv_lines(plan_adult, _inv_date, include_fee=_is_first)
    _make_inv(s5.partner_id, [sub_s5], _riley_lines, _inv_date, _paid)

# After 3 cycles, set next billing date to Apr 12 for all subscriptions
for _sub in [sub_s1, sub_s2, sub_s3, sub_s4, sub_s5]:
    _sub.next_billing_date = date(2026, 4, 12)
print("  invoices done (next billing: Apr 12).")

# ── 12. Auto-enroll preferences (this month, specific days) ─────────────
print("Creating auto-enroll preferences...")
month_start = today.replace(day=1)
month_end   = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

# Jordan & Casey → Little Champions  Mon / Wed / Fri
for _m in [s1, s2]:
    env["dojo.course.auto.enroll"].create({
        "member_id": _m.id, "template_id": tmpl_little.id,
        "mode": "multiday", "date_from": month_start, "date_to": month_end,
        "pref_mon": True, "pref_wed": True, "pref_fri": True,
    })
# Taylor & Morgan → Youth Techniques  Tue / Thu
for _m in [s3, s4]:
    env["dojo.course.auto.enroll"].create({
        "member_id": _m.id, "template_id": tmpl_youth.id,
        "mode": "multiday", "date_from": month_start, "date_to": month_end,
        "pref_tue": True, "pref_thu": True,
    })
# Riley → Adult Fundamentals  Mon / Wed
env["dojo.course.auto.enroll"].create({
    "member_id": s5.id, "template_id": tmpl_adult_fund.id,
    "mode": "multiday", "date_from": month_start, "date_to": month_end,
    "pref_mon": True, "pref_wed": True,
})
# Riley → Advanced Sparring  Tue / Thu
env["dojo.course.auto.enroll"].create({
    "member_id": s5.id, "template_id": tmpl_adv.id,
    "mode": "multiday", "date_from": month_start, "date_to": month_end,
    "pref_tue": True, "pref_thu": True,
})

# ── 13. Sessions + selective enrollment ──────────────────────────────────
# 6 sessions per template (3 past/done + 3 upcoming/open).
# Past sessions: enrollment created with realistic attendance (one absence per member).
# Upcoming sessions: enrolled in 2 of 3 (one session left unenrolled).
print("Creating sessions...")

def seed_sessions(template, instructor, hour, day_shift=0, enroll=None, skip=None):
    """Create 3 past (done) + 3 upcoming (open) sessions.

    enroll   — list of dojo.member records to enroll into each session.
    skip     — set of session indices (0-5) where enrollment is omitted
               (0-2 = past sessions, 3-5 = upcoming sessions).
    """
    skip = skip or set()
    specs = [(-15, "done"), (-8, "done"), (-2, "done"),
             (  3, "open"), ( 8, "open"), (13, "open")]
    for idx, (offset, state) in enumerate(specs):
        day      = today + timedelta(days=offset + day_shift)
        start_dt = datetime(day.year, day.month, day.day, hour, 0)
        end_dt   = start_dt + timedelta(minutes=template.duration_minutes)
        session  = env["dojo.class.session"].create({
            "template_id": template.id,
            "instructor_profile_id": instructor.id,
            "start_datetime": start_dt,
            "end_datetime": end_dt,
            "capacity": template.max_capacity,
            "state": state,
        })
        if enroll and idx not in skip:
            att = "present" if state == "done" else "pending"
            for _m in enroll:
                env["dojo.class.enrollment"].create({
                    "session_id": session.id,
                    "member_id": _m.id,
                    "status": "registered",
                    "attendance_state": att,
                })

# Little Champions @ 4 PM — Jordan & Casey, Mon/Wed/Fri schedule
# skip index 1 (past: one absence) + index 5 (last upcoming: not yet signed up)
seed_sessions(tmpl_little, instr1, hour=16, day_shift=0,
              enroll=[s1, s2], skip={1, 5})

# Youth Techniques @ 5 PM — Taylor & Morgan, Tue/Thu schedule
# skip index 2 (past: one absence) + index 4 (middle upcoming: not yet signed up)
seed_sessions(tmpl_youth, instr1, hour=17, day_shift=1,
              enroll=[s3, s4], skip={2, 4})

# Adult Fundamentals @ 6 PM — Riley, Mon/Wed schedule
# skip index 0 (past: first class missed) + index 5 (last upcoming)
seed_sessions(tmpl_adult_fund, instr1, hour=18, day_shift=0,
              enroll=[s5], skip={0, 5})

# Advanced Sparring @ 7 PM — Riley, Tue/Thu schedule
# skip index 1 (past: one absence) + indices 4-5 (last two upcoming)
seed_sessions(tmpl_adv, instr2, hour=19, day_shift=2,
              enroll=[s5], skip={1, 4, 5})

# ── 14. Force-recompute stored computed fields ─────────────────────────────
# has_portal_login is a stored computed field on dojo.member that checks
# partner_id.user_ids.group_ids. The users were created before the member
# records, so the compute trigger fired before all group implications were
# fully resolved. Force a recompute so the list/form shows the correct value.
print("Recomputing stored fields...")
all_members = env["dojo.member"].search([])
all_members._compute_has_portal_login()
# Flush to DB
all_members.flush_recordset(["has_portal_login"])

env.cr.commit()

print("""
Done! All demo data created.

Logins (password: dojo@2026)
  instructor1@demo.com  Alex Johnson   (Head Instructor)
  instructor2@demo.com  Sam Rivera     (Assistant Instructor)
  parent1@demo.com      Mary Smith     (Smith Household)
  parent2@demo.com      Bob Jones      (Jones Household)
  student1@demo.com     Jordan Smith   (Kids BJJ, Smith HH)
  student2@demo.com     Casey Smith    (Kids BJJ, Smith HH)
  student3@demo.com     Taylor Jones   (Kids BJJ, Jones HH)
  student4@demo.com     Morgan Jones   (Kids BJJ, Jones HH)
  student5@demo.com     Riley Lee      (Adult BJJ, standalone)

Programs
  BJJ Kids   belt path: White -> Yellow -> Orange -> Green
  BJJ Adults belt path: White -> Yellow -> Orange -> Green -> Blue -> Purple -> Brown -> Black

Class Templates + Auto-Enroll (this month)
  Little Champions   (BJJ Kids,   beginner)     Jordan & Casey  — Mon/Wed/Fri
  Youth Techniques   (BJJ Kids,   intermediate) Taylor & Morgan — Tue/Thu
  Adult Fundamentals (BJJ Adults, beginner)     Riley Lee       — Mon/Wed
  Advanced Sparring  (BJJ Adults, advanced)     Riley Lee       — Tue/Thu

Subscription Plans
  Kids BJJ Monthly  $80/mo  + $50 setup  program-based, unlimited sessions (up to 3/week)
  Adult BJJ Monthly $120/mo + $50 setup  program-based, 12 credits/month (up to 5/week)
  Private Lessons   $250/mo, no setup    course-based,  4 credits/month (max 1/week)

Invoices (subscriptions started Jan 12, 2026)
  Smith Household (Mary Smith)  Jan 12: $260 paid  Feb 12: $160 paid  Mar 12: $160 open
    └─ Jordan + Casey each on Kids BJJ Monthly ($80); Jan includes $50 enrollment fee each
  Jones Household (Bob Jones)   Jan 12: $260 paid  Feb 12: $160 paid  Mar 12: $160 open
    └─ Taylor + Morgan each on Kids BJJ Monthly ($80); Jan includes $50 enrollment fee each
  Riley Lee (standalone)        Jan 12: $170 paid  Feb 12: $120 paid  Mar 12: $120 open
    └─ Adult BJJ Monthly ($120); Jan includes $50 enrollment fee
  Next billing date for all subscriptions: Apr 12, 2026

Sessions: 3 past (done) + 3 upcoming (open) per template = 24 sessions total
Enrollments seeded selectively — members miss 1 past class and aren't pre-booked
  for all upcoming sessions (reflects realistic attendance patterns).
""")
