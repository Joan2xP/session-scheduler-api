from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ExhibitorDetail,
    ExhibitorList,
    generateScheduleData,
    ParticipantViewSet,
)

# Create a router and register the ParticipantViewSet
router = DefaultRouter()
router.register(r"participants", ParticipantViewSet, basename="participant")

urlpatterns = [
    # Exhibitor routes
    path("", ExhibitorList.as_view(), name="exhibitor-list"),
    path("<int:year>/<int:month>/", ExhibitorDetail.as_view(), name="exhibitor-detail"),
    path("generate", generateScheduleData, name="generate-schedule-data"),
    # Participant routes (via router)
] + router.urls
