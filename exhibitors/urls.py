from django.urls import path
from .views import ExhibitorList, generateScheduleData

urlpatterns = [
    # Example:
    path("", ExhibitorList.as_view(), name="exhibitor-list"),
    path("generate", generateScheduleData, name="generate-schedule-data"),
]
