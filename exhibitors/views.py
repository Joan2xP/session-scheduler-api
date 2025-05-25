from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Exhibitor, Participant
from .serializers import ExhibitorSerializer, ParticipantSerializer
from .services.SessionScheduler import SessionScheduler
from django.http import JsonResponse
from django.http import HttpRequest
from django.core.handlers.wsgi import WSGIRequest
from rest_framework.decorators import api_view


class ExhibitorList(APIView):
    def get(self, request):
        exhibitors = Exhibitor.objects.all()
        serializer = ExhibitorSerializer(exhibitors, many=True)
        return Response(serializer.data)

    def post(self, request):

        return Response({"message": "POST request received"})


@api_view(["POST"])
def generateScheduleData(request):
    year = request.data.get("year")
    month = request.data.get("month")
    if not year or not month:
        return JsonResponse({"error": "Year and month are required"}, status=400)
    try:
        year = int(year)
        month = int(month)
    except ValueError:
        return JsonResponse({"error": "Year and month must be integers"}, status=400)
    # Here you would implement the logic to generate the schedule data
    # based on the year and month provided.
    start_date = f"{year}-{month:02d}-01"
    schedule_generator = SessionScheduler(
        excel_path="/home/joanpp/coding/task-manager-services/django/exhibitors/assets/people_availability.xlsx",
        start_date=start_date,
        exclude_days=[],
    )

    schedule_data, schedule_statistics, days_with_details = (
        schedule_generator.solve_group_scheduling()
    )

    return JsonResponse(
        {
            "scheduleData": schedule_data,
            "statistics": schedule_statistics,
            "daysWithDetails": days_with_details,
        }
    )


class ParticipantList(APIView):
    def get(self, request):
        participants = Participant.objects.all()
        serializer = ParticipantSerializer(participants, many=True)
        return Response(serializer.data)

    def post(self, request):

        return Response({"message": "POST request received"})
