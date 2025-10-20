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

    def __str__(self):
        return f"Participant {self.id}"
