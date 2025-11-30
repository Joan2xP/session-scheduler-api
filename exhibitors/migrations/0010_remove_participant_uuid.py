# Generated manually to remove UUID field
# SQLite doesn't support dropping UNIQUE columns, so we need to recreate the table

from django.db import migrations


def remove_uuid_column(apps, schema_editor):
    """Remove UUID column by recreating table without it"""
    with schema_editor.connection.cursor() as cursor:
        # Get the current table structure by querying sqlite_master
        cursor.execute("""
            SELECT sql FROM sqlite_master 
            WHERE type='table' AND name='exhibitors_participant'
        """)
        result = cursor.fetchone()
        
        if result:
            # Create new table without uuid column
            # SQLite stores JSON as TEXT, so we'll create the table structure manually
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
            
            # Copy data from old table to new table (excluding uuid)
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
            
            # Drop old table
            cursor.execute("DROP TABLE exhibitors_participant")
            
            # Rename new table
            cursor.execute("ALTER TABLE exhibitors_participant_new RENAME TO exhibitors_participant")
            
            # Recreate indexes if any (name has UNIQUE constraint which creates an index)
            cursor.execute("""
                CREATE UNIQUE INDEX exhibitors_participant_name_uniq 
                ON exhibitors_participant(name)
            """)


class Migration(migrations.Migration):

    dependencies = [
        ("exhibitors", "0009_participant_enforced_week_days"),
    ]

    operations = [
        migrations.RunPython(remove_uuid_column, migrations.RunPython.noop),
    ]

