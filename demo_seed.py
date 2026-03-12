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
env["dojo.member.subscription"].search([]).unlink()
env["dojo.subscription.plan"].search([]).unlink()
env["dojo.class.template"].search([]).unlink()
env["dojo.program"].search([]).unlink()
env["dojo.member.rank"].search([]).unlink()
env["dojo.belt.rank"].search([]).unlink()
env["dojo.guardian.link"].search([]).unlink()
env["dojo.household"].search([]).unlink()
demo_members = env["dojo.member"].search([("partner_id", "in", existing_partners.ids)])
demo_members.unlink()
env["dojo.instructor.profile"].search([("user_id", "in", existing_users.ids)]).unlink()
existing_users.unlink()
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

# ── 2. Parents ────────────────────────────────────────────────────────────
print("Creating parents...")
p1_user = make_user("Mary Smith", "parent1@demo.com", [group_parent_student])
p2_user = make_user("Bob Jones",  "parent2@demo.com", [group_parent_student])
p1 = env["dojo.member"].create({
    "partner_id": p1_user.partner_id.id, "role": "parent",
    "membership_state": "active", "phone": "555-0101", "email": "parent1@demo.com",
})
p2 = env["dojo.member"].create({
    "partner_id": p2_user.partner_id.id, "role": "parent",
    "membership_state": "active", "phone": "555-0102", "email": "parent2@demo.com",
})

# ── 3. Students ───────────────────────────────────────────────────────────
print("Creating students...")
students_raw = [
    ("Jordan Smith",  "student1@demo.com", "student", date(2014,  3, 15), "555-0111"),
    ("Casey Smith",   "student2@demo.com", "student", date(2016,  7, 22), "555-0112"),
    ("Taylor Jones",  "student3@demo.com", "student", date(2013, 11,  5), "555-0113"),
    ("Morgan Jones",  "student4@demo.com", "student", date(2015,  4, 18), "555-0114"),
    ("Riley Lee",     "student5@demo.com", "both",    date(2005,  8, 30), "555-0115"),
]
student_members = []
for name, login, role, dob, phone in students_raw:
    u = make_user(name, login, [group_parent_student])
    m = env["dojo.member"].create({
        "partner_id": u.partner_id.id, "role": role,
        "date_of_birth": dob, "membership_state": "active",
        "phone": phone, "email": login,
    })
    student_members.append(m)
s1, s2, s3, s4, s5 = student_members

# ── 4. Households & guardian links ───────────────────────────────────────
print("Creating households...")
smith_hh = env["dojo.household"].create({"name": "Smith Household"})
for m in [p1, s1, s2]:
    m.household_id = smith_hh
smith_hh.primary_guardian_id = p1
env["dojo.guardian.link"].create({"household_id": smith_hh.id, "guardian_member_id": p1.id, "student_member_id": s1.id, "relation": "mother", "is_primary": True})
env["dojo.guardian.link"].create({"household_id": smith_hh.id, "guardian_member_id": p1.id, "student_member_id": s2.id, "relation": "mother", "is_primary": True})

jones_hh = env["dojo.household"].create({"name": "Jones Household"})
for m in [p2, s3, s4]:
    m.household_id = jones_hh
jones_hh.primary_guardian_id = p2
env["dojo.guardian.link"].create({"household_id": jones_hh.id, "guardian_member_id": p2.id, "student_member_id": s3.id, "relation": "father", "is_primary": True})
env["dojo.guardian.link"].create({"household_id": jones_hh.id, "guardian_member_id": p2.id, "student_member_id": s4.id, "relation": "father", "is_primary": True})

# Riley Lee — solo household (every member needs one for billing)
lee_hh = env["dojo.household"].create({"name": "Lee Household"})
s5.household_id = lee_hh
lee_hh.primary_guardian_id = s5

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
    "instructor_profile_ids": [(4, instr1.id)],
    "description": "Foundational BJJ for younger kids (ages 5\u201310). Basic movements, escapes and positional control.",
})
tmpl_youth = env["dojo.class.template"].create({
    "name": "Youth Techniques", "code": "KIDS-INT",
    "program_id": prog_kids.id, "level": "intermediate",
    "duration_minutes": 75, "max_capacity": 12,
    "instructor_profile_ids": [(4, instr1.id)],
    "description": "Intermediate BJJ for older kids and teens (ages 10\u201316). Sweeps, submissions and live drilling.",
})
tmpl_adult_fund = env["dojo.class.template"].create({
    "name": "Adult Fundamentals", "code": "ADV-BEG",
    "program_id": prog_adults.id, "level": "beginner",
    "duration_minutes": 60, "max_capacity": 15,
    "instructor_profile_ids": [(4, instr1.id)],
    "description": "Entry-level adult BJJ. Perfect for beginners with no prior grappling experience.",
})
tmpl_adv = env["dojo.class.template"].create({
    "name": "Advanced Sparring", "code": "ADV-ADV",
    "program_id": prog_adults.id, "level": "advanced",
    "duration_minutes": 90, "max_capacity": 8,
    "instructor_profile_ids": [(4, instr2.id)],
    "description": "Competition-focused sparring and advanced technique for experienced students.",
})

# ── 9. Subscription plans (program-based) ────────────────────────────────
print("Creating subscription plans...")
currency = env.company.currency_id

plan_kids = env["dojo.subscription.plan"].create({
    "name": "Kids BJJ Monthly", "code": "KIDS-MTH",
    "plan_type": "program", "program_id": prog_kids.id,
    "billing_period": "monthly", "price": 80.00, "initial_fee": 50.00,
    "currency_id": currency.id, "unlimited_sessions": True, "max_sessions_per_week": 3,
    "description": "Unlimited BJJ Kids classes, up to 3 sessions per week.",
})
plan_adult = env["dojo.subscription.plan"].create({
    "name": "Adult BJJ Monthly", "code": "ADV-MTH",
    "plan_type": "program", "program_id": prog_adults.id,
    "billing_period": "monthly", "price": 120.00, "initial_fee": 50.00,
    "currency_id": currency.id, "unlimited_sessions": True, "max_sessions_per_week": 5,
    "description": "Unlimited adult BJJ classes, up to 5 sessions per week.",
})
env["dojo.subscription.plan"].create({
    "name": "Private Lessons", "code": "PRIV-MTH",
    "plan_type": "course", "billing_period": "monthly",
    "price": 250.00, "initial_fee": 0.00,
    "currency_id": currency.id, "unlimited_sessions": False,
    "sessions_per_period": 4, "max_sessions_per_week": 1,
    "allowed_template_ids": [(4, tmpl_adv.id)],
    "description": "Four private advanced sparring sessions per month.",
})

# ── 10. Member subscriptions ──────────────────────────────────────────────
# IMPORTANT: must be created BEFORE enrollments — constraint checks active sub.
print("Creating member subscriptions...")
sub_start = today - timedelta(days=60)
sub_next  = today + timedelta(days=30 - today.day + 1)

def make_sub(member, plan, note):
    return env["dojo.member.subscription"].create({
        "member_id": member.id, "plan_id": plan.id,
        "start_date": sub_start, "next_billing_date": sub_next,
        "state": "active", "company_id": env.company.id, "note": note,
    })

make_sub(s1, plan_kids,  "Jordan Smith \u2014 Kids BJJ")
make_sub(s2, plan_kids,  "Casey Smith \u2014 Kids BJJ")
make_sub(s3, plan_kids,  "Taylor Jones \u2014 Kids BJJ")
make_sub(s4, plan_kids,  "Morgan Jones \u2014 Kids BJJ")
make_sub(s5, plan_adult, "Riley Lee \u2014 Adult BJJ")

# ── 11. Sessions & enrollments ────────────────────────────────────────────
print("Creating sessions and enrollments...")

def seed_sessions(template, instructor, members, hour, day_shift=0):
    """3 past (done) + 3 upcoming (open) sessions."""
    for offset, state in [(-15, "done"), (-8, "done"), (-2, "done"),
                          (  3, "open"), ( 8, "open"), (13, "open")]:
        day = today + timedelta(days=offset + day_shift)
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
        for m in members:
            env["dojo.class.enrollment"].create({
                "session_id": session.id, "member_id": m.id,
                "status": "registered",
                "attendance_state": "present" if state == "done" else "pending",
            })

# Little Champions: Jordan & Casey @ 4 PM
seed_sessions(tmpl_little, instr1, [s1, s2], hour=16, day_shift=0)
# Youth Techniques: Taylor & Morgan @ 5 PM
seed_sessions(tmpl_youth, instr1, [s3, s4], hour=17, day_shift=1)
# Adult Fundamentals: empty — open for walk-ins
seed_sessions(tmpl_adult_fund, instr1, [], hour=18, day_shift=0)
# Advanced Sparring: Riley Lee @ 7 PM
seed_sessions(tmpl_adv, instr2, [s5], hour=19, day_shift=2)

# ── 12. Force-recompute stored computed fields ─────────────────────────────
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

Class Templates
  Little Champions   (BJJ Kids,   beginner)     Jordan & Casey enrolled
  Youth Techniques   (BJJ Kids,   intermediate) Taylor & Morgan enrolled
  Adult Fundamentals (BJJ Adults, beginner)     open enrollment (empty)
  Advanced Sparring  (BJJ Adults, advanced)     Riley Lee enrolled

Subscription Plans
  Kids BJJ Monthly  $80/mo  + $50 setup  program-based, max 3 sessions/week
  Adult BJJ Monthly $120/mo + $50 setup  program-based, max 5 sessions/week
  Private Lessons   $250/mo, no setup    course-based, 4 sessions/period, 1/week

Sessions: 3 past (done) + 3 upcoming (open) per template = 24 sessions total
""")
