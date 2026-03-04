"""Post-migration script for dojo_classes 19.0.1.1.0

Migrates dojo.course.auto.enroll records:
  - mode 'weekly_limited' → 'multiday'
  - date_from  ← old week_start_date
  - date_to    ← old week_start_date + 6 days
  - Drops the week_start_date column
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 1. Add new columns if they don't exist yet (ORM may have already added them,
    #    but be defensive in case the migration runs before the ORM update).
    cr.execute("""
        ALTER TABLE dojo_course_auto_enroll
            ADD COLUMN IF NOT EXISTS date_from date,
            ADD COLUMN IF NOT EXISTS date_to   date;
    """)

    # 2. Migrate weekly_limited → multiday, carrying over the date range.
    cr.execute("""
        UPDATE dojo_course_auto_enroll
           SET mode      = 'multiday',
               date_from = week_start_date,
               date_to   = week_start_date + INTERVAL '6 days'
         WHERE mode = 'weekly_limited'
           AND week_start_date IS NOT NULL;
    """)
    cr.execute("""
        SELECT COUNT(*) FROM dojo_course_auto_enroll WHERE mode = 'multiday';
    """)
    migrated = cr.fetchone()[0]
    _logger.info("dojo_classes migration: %d records converted to 'multiday'.", migrated)

    # 3. Drop the old week_start_date column.
    cr.execute("""
        ALTER TABLE dojo_course_auto_enroll
            DROP COLUMN IF EXISTS week_start_date;
    """)
    _logger.info("dojo_classes migration: week_start_date column dropped.")
