import logging
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from .models import Exhibitor, Participant, SessionGroup, Session
from .serializers import (
    ExhibitorSerializer,
    ParticipantSerializer,
    SessionGroupSerializer,
    SessionSerializer,
)
from .services.SessionScheduler import SessionScheduler

logger = logging.getLogger(__name__)


class ExhibitorList(APIView):
    """List all exhibitors"""

    def get(self, request):
        exhibitors = Exhibitor.objects.all()
        serializer = ExhibitorSerializer(exhibitors, many=True)
        return Response(serializer.data)


class ExhibitorDetail(APIView):
    """Retrieve, create, or update an exhibitor by year and month"""

    def get(self, request, year, month):
        try:
            exhibitor = Exhibitor.objects.get(year=year, month=month)
            serializer = ExhibitorSerializer(exhibitor)
            return Response(serializer.data)
        except Exhibitor.DoesNotExist:
            return Response(
                {"error": f"Exhibitor not found for year {year}, month {month}"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def post(self, request, year, month):
        """Create a new exhibitor schedule"""
        schedule_data = request.data.get("scheduleData")
        schedule_statistics = request.data.get("statistics")
        days_with_details = request.data.get("daysWithDetails")

        exhibitor, created = Exhibitor.objects.get_or_create(year=year, month=month)
        if not created:
            return Response(
                {"error": "Schedule already exists for this month"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        exhibitor.schedule_data = schedule_data
        exhibitor.schedule_statistics = schedule_statistics
        exhibitor.days_with_details = days_with_details
        exhibitor.save()

        serializer = ExhibitorSerializer(exhibitor)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def put(self, request, year, month):
        """Update an existing exhibitor schedule"""
        try:
            exhibitor = Exhibitor.objects.get(year=year, month=month)
        except Exhibitor.DoesNotExist:
            return Response(
                {"error": f"Exhibitor not found for year {year}, month {month}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        schedule_data = request.data.get("scheduleData")
        schedule_statistics = request.data.get("statistics")
        days_with_details = request.data.get("daysWithDetails")

        exhibitor.schedule_data = schedule_data
        exhibitor.schedule_statistics = schedule_statistics
        exhibitor.days_with_details = days_with_details
        exhibitor.save()

        serializer = ExhibitorSerializer(exhibitor)
        return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["POST"])
def generateScheduleData(request):
    """Generate schedule data for a given year and month"""
    year = request.data.get("year")
    month = request.data.get("month")

    if not year or not month:
        return Response(
            {"error": "Year and month are required"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        year = int(year)
        month = int(month)

        # Validate month range
        if not (1 <= month <= 12):
            return Response(
                {"error": "Month must be between 1 and 12"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    except ValueError:
        return Response(
            {"error": "Year and month must be integers"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        start_date = f"{year}-{month:02d}-01"
        schedule_generator = SessionScheduler(
            start_date=start_date,
            selected_days_sessions={
                "mon": [1],  # Monday afternoon
                "wed": [0],  # Wednesday morning
                "thu": [1],  # Thursday afternoon
                "fri": [0],  # Friday morning
                "sat": [0],  # Saturday morning
            },
            exclude_days=[25],
        )

        res = schedule_generator.solve_group_scheduling()

        if not res:
            return Response(
                {"error": "Could not generate schedule"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        schedule_data, schedule_statistics, days_with_details = res

        return Response(
            {
                "scheduleData": schedule_data,
                "statistics": schedule_statistics,
                "daysWithDetails": days_with_details,
            },
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Error generating schedule: {str(e)}", exc_info=True)
        return Response(
            {"error": "An error occurred while generating the schedule"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ParticipantViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and editing Participant instances.
    Provides list, create, retrieve, update, partial_update, and destroy actions.
    """

    queryset = Participant.objects.all()
    serializer_class = ParticipantSerializer
    lookup_field = "id"


class SessionGroupList(APIView):
    """List all session groups or create a new one"""

    def get(self, request):
        groups = SessionGroup.objects.prefetch_related("sessions").all()
        serializer = SessionGroupSerializer(groups, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new session group with optional sessions"""
        serializer = SessionGroupSerializer(data=request.data)
        if serializer.is_valid():
            sessions_data = serializer.validated_data.pop("sessions_data", None)
            group = SessionGroup.objects.create(**serializer.validated_data)

            # Create nested sessions if provided
            if sessions_data:
                for session_data in sessions_data:
                    session_serializer = SessionSerializer(data=session_data)
                    if session_serializer.is_valid():
                        session_serializer.save(session_group=group)
                    else:
                        # If session creation fails, delete the group and return error
                        group.delete()
                        return Response(
                            {
                                "error": "Invalid session data",
                                "details": session_serializer.errors,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

            response_serializer = SessionGroupSerializer(group)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SessionGroupDetail(APIView):
    """Retrieve, update or delete a session group"""

    def get(self, request, group_id):
        group = get_object_or_404(
            SessionGroup.objects.prefetch_related("sessions"), id=group_id
        )
        serializer = SessionGroupSerializer(group)
        return Response(serializer.data)

    def put(self, request, group_id):
        """Update a session group"""
        group = get_object_or_404(SessionGroup, id=group_id)
        serializer = SessionGroupSerializer(group, data=request.data)
        if serializer.is_valid():
            sessions_data = serializer.validated_data.pop("sessions_data", None)
            serializer.save()

            # Update nested sessions if provided
            if sessions_data is not None:
                # Delete existing sessions
                group.sessions.all().delete()
                # Create new sessions
                for session_data in sessions_data:
                    session_serializer = SessionSerializer(data=session_data)
                    if session_serializer.is_valid():
                        session_serializer.save(session_group=group)
                    else:
                        return Response(
                            {
                                "error": "Invalid session data",
                                "details": session_serializer.errors,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

            response_serializer = SessionGroupSerializer(group)
            return Response(response_serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, group_id):
        """Delete a session group"""
        group = get_object_or_404(SessionGroup, id=group_id)
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionList(APIView):
    """Create a new session in a group"""

    def post(self, request, group_id):
        """Create a new session"""
        group = get_object_or_404(SessionGroup, id=group_id)
        serializer = SessionSerializer(data=request.data)
        if serializer.is_valid():
            session = serializer.save(session_group=group)
            response_serializer = SessionSerializer(session)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SessionDetail(APIView):
    """Update or delete a session"""

    def put(self, request, group_id, session_id):
        """Update a session"""
        group = get_object_or_404(SessionGroup, id=group_id)
        session = get_object_or_404(Session, id=session_id, session_group=group)
        serializer = SessionSerializer(session, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, group_id, session_id):
        """Delete a session"""
        group = get_object_or_404(SessionGroup, id=group_id)
        session = get_object_or_404(Session, id=session_id, session_group=group)
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
