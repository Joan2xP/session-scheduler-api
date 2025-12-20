from django.db import models
from django.core.exceptions import ValidationError

# Create your models here.


class Exhibitor(models.Model):
    year = models.IntegerField()
    month = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    day_details = models.JSONField(default=list)
    schedule_data = models.JSONField(default=list)
    schedule_statistics = models.JSONField(default=list)
    days_with_details = models.JSONField(default=list)

    def __str__(self):
        return self.name


class Participant(models.Model):
    name = models.CharField(max_length=255, unique=True)
    session_group = models.ForeignKey(
        "SessionGroup", on_delete=models.CASCADE, related_name="participants"
    )
    availability = models.JSONField(
        default=None, null=True, blank=True
    )  # Array of session IDs
    partner = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partnered_with",
    )
    max_per_week = models.IntegerField()
    max_per_month = models.IntegerField()
    min_per_month = models.IntegerField()
    only_session_occurrences = models.JSONField(
        default=None, null=True, blank=True
    )  # Array of {sessionId, date} objects
    exclude_ids = models.JSONField(
        default=None, null=True, blank=True
    )  # Array of participant IDs
    exclude_session_occurrences = models.JSONField(
        default=None, null=True, blank=True
    )  # Array of {sessionId, date} objects
    min_sessions_together = models.JSONField(
        default=None, null=True, blank=True
    )  # Single object {sessionId, partnerId, amount}
    enforced_week_days = models.JSONField(default=None, null=True, blank=True)

    def clean(self):
        """Validate that all relations belong to the same session group"""
        if not self.session_group_id:
            return

        errors = {}

        # Validate partner_id belongs to same session group
        if self.partner_id:
            try:
                partner = Participant.objects.get(id=self.partner_id)
                if partner.session_group_id != self.session_group_id:
                    errors["partner"] = "Partner must belong to the same session group"
            except Participant.DoesNotExist:
                errors["partner"] = "Partner does not exist"

        # Validate exclude_ids all belong to same session group
        if self.exclude_ids:
            if not isinstance(self.exclude_ids, list):
                errors["exclude_ids"] = "exclude_ids must be an array"
            else:
                invalid_ids = []
                for participant_id in self.exclude_ids:
                    try:
                        excluded = Participant.objects.get(id=participant_id)
                        if excluded.session_group_id != self.session_group_id:
                            invalid_ids.append(participant_id)
                    except Participant.DoesNotExist:
                        invalid_ids.append(participant_id)
                if invalid_ids:
                    errors["exclude_ids"] = (
                        f"Participants {invalid_ids} do not exist or "
                        "do not belong to the same session group"
                    )

        # Validate availability session IDs belong to same session group
        if self.availability:
            if not isinstance(self.availability, list):
                errors["availability"] = "availability must be an array"
            else:
                invalid_ids = []
                for session_id in self.availability:
                    try:
                        session = Session.objects.get(id=session_id)
                        if session.session_group_id != self.session_group_id:
                            invalid_ids.append(session_id)
                    except Session.DoesNotExist:
                        invalid_ids.append(session_id)
                if invalid_ids:
                    errors["availability"] = (
                        f"Sessions {invalid_ids} do not exist or "
                        "do not belong to the same session group"
                    )

        # Validate only_session_occurrences
        if self.only_session_occurrences:
            if not isinstance(self.only_session_occurrences, list):
                errors["only_session_occurrences"] = (
                    "only_session_occurrences must be an array"
                )
            else:
                invalid_occurrences = []
                for idx, occurrence in enumerate(self.only_session_occurrences):
                    if not isinstance(occurrence, dict):
                        invalid_occurrences.append(f"index {idx}: not an object")
                        continue
                    session_id = occurrence.get("sessionId")
                    date = occurrence.get("date")
                    if session_id is None or date is None:
                        invalid_occurrences.append(
                            f"index {idx}: missing sessionId or date"
                        )
                        continue
                    try:
                        session = Session.objects.get(id=session_id)
                        if session.session_group_id != self.session_group_id:
                            invalid_occurrences.append(
                                f"index {idx}: session {session_id} not in same group"
                            )
                    except Session.DoesNotExist:
                        invalid_occurrences.append(
                            f"index {idx}: session {session_id} does not exist"
                        )
                if invalid_occurrences:
                    errors["only_session_occurrences"] = (
                        f"Invalid occurrences: {', '.join(invalid_occurrences)}"
                    )

        # Validate exclude_session_occurrences
        if self.exclude_session_occurrences:
            if not isinstance(self.exclude_session_occurrences, list):
                errors["exclude_session_occurrences"] = (
                    "exclude_session_occurrences must be an array"
                )
            else:
                invalid_occurrences = []
                for idx, occurrence in enumerate(self.exclude_session_occurrences):
                    if not isinstance(occurrence, dict):
                        invalid_occurrences.append(f"index {idx}: not an object")
                        continue
                    session_id = occurrence.get("sessionId")
                    date = occurrence.get("date")
                    if session_id is None or date is None:
                        invalid_occurrences.append(
                            f"index {idx}: missing sessionId or date"
                        )
                        continue
                    try:
                        session = Session.objects.get(id=session_id)
                        if session.session_group_id != self.session_group_id:
                            invalid_occurrences.append(
                                f"index {idx}: session {session_id} not in same group"
                            )
                    except Session.DoesNotExist:
                        invalid_occurrences.append(
                            f"index {idx}: session {session_id} does not exist"
                        )
                if invalid_occurrences:
                    errors["exclude_session_occurrences"] = (
                        f"Invalid occurrences: {', '.join(invalid_occurrences)}"
                    )

        # Validate min_sessions_together
        if self.min_sessions_together:
            if not isinstance(self.min_sessions_together, dict):
                errors["min_sessions_together"] = (
                    "min_sessions_together must be an object"
                )
            else:
                session_id = self.min_sessions_together.get("sessionId")
                partner_id = self.min_sessions_together.get("partnerId")
                amount = self.min_sessions_together.get("amount")

                if session_id is None:
                    errors["min_sessions_together"] = "Missing sessionId"
                else:
                    try:
                        session = Session.objects.get(id=session_id)
                        if session.session_group_id != self.session_group_id:
                            errors["min_sessions_together"] = (
                                "Session does not belong to the same session group"
                            )
                    except Session.DoesNotExist:
                        errors["min_sessions_together"] = "Session does not exist"

                if partner_id is None:
                    errors["min_sessions_together"] = (
                        errors.get("min_sessions_together", "") + " Missing partnerId"
                    ).strip()
                else:
                    try:
                        partner = Participant.objects.get(id=partner_id)
                        if partner.session_group_id != self.session_group_id:
                            errors["min_sessions_together"] = (
                                errors.get("min_sessions_together", "")
                                + " Partner does not belong to the same session group"
                            ).strip()
                    except Participant.DoesNotExist:
                        errors["min_sessions_together"] = (
                            errors.get("min_sessions_together", "")
                            + " Partner does not exist"
                        ).strip()

                if amount is None or not isinstance(amount, int) or amount < 1:
                    errors["min_sessions_together"] = (
                        errors.get("min_sessions_together", "") + " amount must be >= 1"
                    ).strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Participant {self.id}"


class SessionGroup(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Session(models.Model):
    FREQUENCY_CHOICES = [
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    ]

    session_group = models.ForeignKey(
        SessionGroup, on_delete=models.CASCADE, related_name="sessions"
    )
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    start_hour = models.IntegerField()  # 0-23
    start_minute = models.IntegerField()  # 0-59
    end_hour = models.IntegerField()  # 0-23
    end_minute = models.IntegerField()  # 0-59
    week = models.IntegerField(null=True, blank=True)  # 1-4 (for monthly/yearly)
    day_of_week = models.IntegerField(
        null=True, blank=True
    )  # 0-6 (for weekly/monthly/yearly)
    month = models.IntegerField(null=True, blank=True)  # 1-12 (for yearly only)
    location = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"Session {self.id} - {self.frequency} from {self.start_hour:02d}:{self.start_minute:02d} "
            f"to {self.end_hour:02d}:{self.end_minute:02d}"
        )
