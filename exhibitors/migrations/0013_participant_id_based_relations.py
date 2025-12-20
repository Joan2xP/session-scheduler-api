# Generated manually for Participant ID-based relations migration

import django.db.models.deletion
from django.db import migrations, models


def create_default_session_group(apps, schema_editor):
    """Create a default SessionGroup if none exists"""
    SessionGroup = apps.get_model("exhibitors", "SessionGroup")
    if not SessionGroup.objects.exists():
        SessionGroup.objects.create(name="Default Session Group")


def assign_participants_to_default_group(apps, schema_editor):
    """Assign all existing participants to the default session group"""
    Participant = apps.get_model("exhibitors", "Participant")
    SessionGroup = apps.get_model("exhibitors", "SessionGroup")

    default_group = SessionGroup.objects.first()
    if default_group:
        Participant.objects.filter(session_group__isnull=True).update(
            session_group=default_group
        )


def migrate_partner_names_to_ids(apps, schema_editor):
    """Migrate partner names to partner_id ForeignKeys"""
    Participant = apps.get_model("exhibitors", "Participant")

    for participant in Participant.objects.exclude(partner_old__isnull=True).exclude(
        partner_old=""
    ):
        if participant.partner_old:
            try:
                # Try to find partner by name
                partner = Participant.objects.get(name=participant.partner_old)
                participant.partner_id = partner.id
                participant.save(update_fields=["partner_id"])
            except Participant.DoesNotExist:
                # Partner not found, set to None
                participant.partner_id = None
                participant.save(update_fields=["partner_id"])


def migrate_exclude_names_to_ids(apps, schema_editor):
    """Migrate exclude array of names to exclude_ids array of participant IDs"""
    Participant = apps.get_model("exhibitors", "Participant")

    for participant in Participant.objects.exclude(exclude_old__isnull=True):
        if participant.exclude_old and isinstance(participant.exclude_old, list):
            exclude_ids = []
            for name in participant.exclude_old:
                if isinstance(name, str):
                    try:
                        excluded_participant = Participant.objects.get(name=name)
                        exclude_ids.append(excluded_participant.id)
                    except Participant.DoesNotExist:
                        # Skip if participant not found
                        pass
            participant.exclude_ids = exclude_ids if exclude_ids else None
            participant.save(update_fields=["exclude_ids"])


def migrate_availability_days_to_session_ids(apps, schema_editor):
    """Migrate availability day strings to session IDs"""
    Participant = apps.get_model("exhibitors", "Participant")
    Session = apps.get_model("exhibitors", "Session")

    # Day string to day_of_week mapping
    day_mapping = {
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }

    for participant in Participant.objects.exclude(availability__isnull=True):
        if participant.availability and isinstance(participant.availability, list):
            session_ids = []
            for day_str in participant.availability:
                if isinstance(day_str, str) and day_str.lower() in day_mapping:
                    day_of_week = day_mapping[day_str.lower()]
                    # Find sessions in the same session group with matching day_of_week
                    sessions = Session.objects.filter(
                        session_group=participant.session_group, day_of_week=day_of_week
                    )
                    if sessions.exists():
                        # Use the first matching session
                        session_ids.append(sessions.first().id)
            participant.availability = session_ids if session_ids else None
            participant.save(update_fields=["availability"])


def migrate_min_days_together_to_min_sessions_together(apps, schema_editor):
    """Migrate min_days_together to min_sessions_together"""
    Participant = apps.get_model("exhibitors", "Participant")
    Session = apps.get_model("exhibitors", "Session")

    day_mapping = {
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }

    for participant in Participant.objects.exclude(min_days_together__isnull=True):
        if participant.min_days_together and isinstance(
            participant.min_days_together, dict
        ):
            old_data = participant.min_days_together
            day_str = old_data.get("day")
            partner_name = old_data.get("partner")
            amount = old_data.get("amount", 1)

            new_data = {}

            # Map day to session_id
            if day_str and isinstance(day_str, str) and day_str.lower() in day_mapping:
                day_of_week = day_mapping[day_str.lower()]
                sessions = Session.objects.filter(
                    session_group=participant.session_group, day_of_week=day_of_week
                )
                if sessions.exists():
                    new_data["sessionId"] = sessions.first().id
                else:
                    # No matching session, skip this migration
                    continue
            else:
                # Invalid day, skip
                continue

            # Map partner name to participant ID
            if partner_name and isinstance(partner_name, str):
                try:
                    partner = Participant.objects.get(name=partner_name)
                    if partner.session_group_id == participant.session_group_id:
                        new_data["partnerId"] = partner.id
                    else:
                        # Partner in different group, skip
                        continue
                except Participant.DoesNotExist:
                    # Partner not found, skip
                    continue
            else:
                # No partner, skip
                continue

            # Add amount
            if isinstance(amount, int) and amount >= 1:
                new_data["amount"] = amount
            else:
                new_data["amount"] = 1

            participant.min_days_together = new_data
            participant.save(update_fields=["min_days_together"])


class Migration(migrations.Migration):

    dependencies = [
        ("exhibitors", "0012_remove_session_hour_remove_session_minute_and_more"),
    ]

    operations = [
        # Step 1: Create default SessionGroup if none exists
        migrations.RunPython(create_default_session_group, migrations.RunPython.noop),
        # Step 2: Add session_group ForeignKey (nullable initially)
        migrations.AddField(
            model_name="participant",
            name="session_group",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="participants",
                to="exhibitors.sessiongroup",
            ),
        ),
        # Step 3: Assign all existing participants to default SessionGroup
        migrations.RunPython(
            assign_participants_to_default_group, migrations.RunPython.noop
        ),
        # Step 4: Make session_group non-nullable
        migrations.AlterField(
            model_name="participant",
            name="session_group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="participants",
                to="exhibitors.sessiongroup",
            ),
        ),
        # Step 5: Rename old partner CharField to partner_old
        migrations.RenameField(
            model_name="participant",
            old_name="partner",
            new_name="partner_old",
        ),
        # Step 6: Add new partner ForeignKey
        migrations.AddField(
            model_name="participant",
            name="partner",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="partnered_with",
                to="exhibitors.participant",
            ),
        ),
        # Step 7: Migrate partner names to partner_id
        migrations.RunPython(migrate_partner_names_to_ids, migrations.RunPython.noop),
        # Step 8: Remove old partner CharField
        migrations.RemoveField(
            model_name="participant",
            name="partner_old",
        ),
        # Step 9: Rename exclude to exclude_old (temporary, will be removed later)
        migrations.RenameField(
            model_name="participant",
            old_name="exclude",
            new_name="exclude_old",
        ),
        # Step 10: Add exclude_ids field
        migrations.AddField(
            model_name="participant",
            name="exclude_ids",
            field=models.JSONField(default=None, null=True),
        ),
        # Step 11: Migrate exclude names to IDs
        migrations.RunPython(migrate_exclude_names_to_ids, migrations.RunPython.noop),
        # Step 12: Remove old exclude field
        migrations.RemoveField(
            model_name="participant",
            name="exclude_old",
        ),
        # Step 13: Migrate availability day strings to session IDs
        migrations.RunPython(
            migrate_availability_days_to_session_ids, migrations.RunPython.noop
        ),
        # Step 14: Rename only_days_of_month to only_session_occurrences
        migrations.RenameField(
            model_name="participant",
            old_name="only_days_of_month",
            new_name="only_session_occurrences",
        ),
        # Step 15: Rename exclude_days_of_month to exclude_session_occurrences
        migrations.RenameField(
            model_name="participant",
            old_name="exclude_days_of_month",
            new_name="exclude_session_occurrences",
        ),
        # Step 16: Migrate min_days_together data structure (before renaming)
        migrations.RunPython(
            migrate_min_days_together_to_min_sessions_together,
            migrations.RunPython.noop,
        ),
        # Step 17: Rename min_days_together to min_sessions_together
        migrations.RenameField(
            model_name="participant",
            old_name="min_days_together",
            new_name="min_sessions_together",
        ),
    ]
