# Generated manually to remove UUID field
# SQLite doesn't support dropping UNIQUE columns, so we need to recreate the table

from django.db import migrations


def remove_uuid_column(apps, schema_editor):
    """Remove UUID column by recreating table without it"""
    connection = schema_editor.connection
    vendor = connection.vendor

    with connection.cursor() as cursor:
        if vendor == "sqlite":
            # SQLite doesn't support DROP COLUMN with UNIQUE constraints
            cursor.execute("""
                SELECT sql FROM sqlite_master
                WHERE type='table' AND name='exhibitors_participant'
            """)
            result = cursor.fetchone()

            if result:
                cursor.execute("""
                    CREATE TABLE exhibitors_participant_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(255) NOT NULL UNIQUE,
                        availability TEXT,
                        partner VARCHAR(255),
                        max_per_week INTEGER NOT NULL,
                        max_per_month INTEGER NOT NULL,
                        min_per_month INTEGER NOT NULL,
                        only_days_of_month TEXT,
                        exclude TEXT,
                        exclude_days_of_month TEXT,
                        min_days_together TEXT,
                        enforced_week_days TEXT
                    )
                """)

                cursor.execute("""
                    INSERT INTO exhibitors_participant_new
                    (id, name, availability, partner, max_per_week, max_per_month,
                     min_per_month, only_days_of_month, exclude, exclude_days_of_month,
                     min_days_together, enforced_week_days)
                    SELECT
                        id, name, availability, partner, max_per_week, max_per_month,
                        min_per_month, only_days_of_month, exclude, exclude_days_of_month,
                        min_days_together, enforced_week_days
                    FROM exhibitors_participant
                """)

                cursor.execute("DROP TABLE exhibitors_participant")
                cursor.execute("ALTER TABLE exhibitors_participant_new RENAME TO exhibitors_participant")

                cursor.execute("""
                    CREATE UNIQUE INDEX exhibitors_participant_name_uniq
                    ON exhibitors_participant(name)
                """)
        else:
            # PostgreSQL supports DROP COLUMN directly
            cursor.execute("ALTER TABLE exhibitors_participant DROP COLUMN IF EXISTS uuid")


class Migration(migrations.Migration):

    dependencies = [
        ("exhibitors", "0009_participant_enforced_week_days"),
    ]

    operations = [
        migrations.RunPython(remove_uuid_column, migrations.RunPython.noop),
    ]

