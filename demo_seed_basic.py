"""
Basic demo seed — creates a simple parent + two student demo accounts.

Run:
  sudo -u odoo19 odoo shell -d odoo19 --no-http < /opt/odoo19/odoo19/custom-addons/demo_seed_basic.py

Accounts (password: Dojo@2026):
  Demo1@demo.com        Demo Student 1   Minor student, Demo Household
  Demo2@demo.com        Demo Student 2   Minor student, Demo Household
  DemoParent@demo.com   Demo Parent      Guardian, Demo Household
"""
from datetime import date

today = date.today()
PASSWORD = "Dojo@2026"

DEMO_LOGINS = [
    "Demo1@demo.com",
    "Demo2@demo.com",
    "DemoParent@demo.com",
]

# ── Cleanup: remove any prior run of this seed ────────────────────────────
print("Cleaning up prior basic demo data...")
existing_users = env["res.users"].search([("login", "in", DEMO_LOGINS)])
existing_partners = existing_users.mapped("partner_id")

if existing_partners:
    demo_members = env["dojo.member"].search([
        ("partner_id", "in", existing_partners.ids)
    ])
    if demo_members:
        demo_members.unlink()

    # Remove any household that has these partners as members
    for partner in existing_partners:
        hh = partner.parent_id
        if hh and getattr(hh, "is_household", False):
            # Only delete the household if it was created for this seed
            if hh.name == "Demo Household":
                hh.parent_id = False  # detach first to avoid cascade issues

if existing_users:
    existing_users.unlink()

# Also clean up the Demo Household partner itself if it still exists
demo_hh_existing = env["res.partner"].search([
    ("name", "=", "Demo Household"), ("is_household", "=", True)
])
if demo_hh_existing:
    demo_hh_existing.unlink()

print("  cleanup done.")

# ── Group references ──────────────────────────────────────────────────────
group_parent_student = env.ref("dojo_base.group_dojo_parent_student")


def make_user(name, login, groups):
    u = env["res.users"].create({
        "name": name,
        "login": login,
        "email": login,
        "group_ids": [(6, 0, [g.id for g in groups])],
    })
    u.password = PASSWORD
    return u


# ── 1. Demo Parent ────────────────────────────────────────────────────────
print("Creating Demo Parent...")
parent_user = make_user("Demo Parent", "DemoParent@demo.com", [group_parent_student])
parent_partner = parent_user.partner_id
parent_partner.write({
    "is_guardian": True,
    "phone": "555-0200",
})

# ── 2. Demo Students ──────────────────────────────────────────────────────
print("Creating Demo Students...")

students_raw = [
    # (name, login, dob, phone)
    ("Demo Student 1", "Demo1@demo.com", date(2015, 6, 15), "555-0201"),
    ("Demo Student 2", "Demo2@demo.com", date(2017, 9, 20), "555-0202"),
]

student_members = []
for name, login, dob, phone in students_raw:
    u = make_user(name, login, [group_parent_student])
    m = env["dojo.member"].create({
        "partner_id": u.partner_id.id,
        "date_of_birth": dob,
        "membership_state": "active",
        "phone": phone,
        "email": login,
    })
    u.partner_id.write({
        "is_minor": True,
        "is_guardian": False,
        "phone": phone,
    })
    print(f"  Created {name} ({login})")
    student_members.append((u, m))

(s1_user, s1), (s2_user, s2) = student_members

# ── 3. Demo Household ─────────────────────────────────────────────────────
print("Creating Demo Household...")
demo_hh = env["res.partner"].create({
    "name": "Demo Household",
    "is_household": True,
    "is_company": True,
    "primary_guardian_id": parent_partner.id,
    "phone": "555-0200",
})

# Assign everyone to the household
for partner in [s1.partner_id, s2.partner_id, parent_partner]:
    partner.parent_id = demo_hh

env.cr.commit()
print("\nBasic demo seed complete!")
print(f"  Demo Student 1  :  Demo1@demo.com         /  {PASSWORD}")
print(f"  Demo Student 2  :  Demo2@demo.com         /  {PASSWORD}")
print(f"  Demo Parent     :  DemoParent@demo.com    /  {PASSWORD}")
print(f"  Household       :  Demo Household")
