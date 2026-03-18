"""
19.0.4.2.0 — add duration column to dojo_subscription_plan (was defined in the
model but never existed in the DB).
"""


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE dojo_subscription_plan
        ADD COLUMN IF NOT EXISTS duration integer DEFAULT 0;
    """)
