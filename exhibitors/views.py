import logging
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from django.core.exceptions import ValidationError
from .models import Exhibitor, Participant
from .serializers import ExhibitorSerializer, ParticipantSerializer
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
