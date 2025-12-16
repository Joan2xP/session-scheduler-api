from django.db import models

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
    availability = models.JSONField(default=None, null=True)
    partner = models.CharField(max_length=255, default=None, null=True)
    max_per_week = models.IntegerField()
    max_per_month = models.IntegerField()
    min_per_month = models.IntegerField()
    only_days_of_month = models.JSONField(default=None, null=True)
    exclude = models.JSONField(default=None, null=True)
    exclude_days_of_month = models.JSONField(default=None, null=True)
    min_days_together = models.JSONField(default=None, null=True)
    enforced_week_days = models.JSONField(default=None, null=True)

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
