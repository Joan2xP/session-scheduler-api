from django.urls import path
from .views import ExhibitorList, generateScheduleData, ParticipantList

urlpatterns = [
    # Example:
    path("participants", ParticipantList.as_view(), name="participant-list"),
    path("", ExhibitorList.as_view(), name="exhibitor-list"),
    path("generate", generateScheduleData, name="generate-schedule-data"),
]
