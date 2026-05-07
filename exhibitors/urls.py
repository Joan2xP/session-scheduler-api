from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ExhibitorDetail,
    ExhibitorList,
    generateScheduleData,
    ParticipantViewSet,
    ParticipantTraitViewSet,
    SessionGroupList,
    SessionGroupDetail,
    SessionList,
    SessionDetail,
)

# Create a router and register the ParticipantViewSet
router = DefaultRouter()
router.register(r"participants", ParticipantViewSet, basename="participant")
router.register(r"traits", ParticipantTraitViewSet, basename="trait")

urlpatterns = [
    # Exhibitor routes
    path("", ExhibitorList.as_view(), name="exhibitor-list"),
    path("<int:year>/<int:month>/", ExhibitorDetail.as_view(), name="exhibitor-detail"),
    path("generate", generateScheduleData, name="generate-schedule-data"),
    # Session routes
    path(
        "sessions/groups/",
        SessionGroupList.as_view(),
        name="session-group-list",
    ),
    path(
        "sessions/groups/<int:group_id>/",
        SessionGroupDetail.as_view(),
        name="session-group-detail",
    ),
    path(
        "sessions/groups/<int:group_id>/sessions/",
        SessionList.as_view(),
        name="session-list",
    ),
    path(
        "sessions/groups/<int:group_id>/sessions/<int:session_id>/",
        SessionDetail.as_view(),
        name="session-detail",
    ),
    # Participant routes (via router)
] + router.urls
