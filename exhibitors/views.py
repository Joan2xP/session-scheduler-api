import logging
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from .models import Exhibitor, Participant, SessionGroup, Session, ParticipantTrait
from .serializers import (
    ExhibitorSerializer,
    ParticipantSerializer,
    ParticipantTraitSerializer,
    SessionGroupSerializer,
    SessionSerializer,
)
from .services import (
    SchedulerService,
    SchedulerServiceError,
    SchedulerNotFoundError,
    SchedulerValidationError,
    SchedulerInfeasible,
    ParticipantService,
    ParticipantServiceError,
    SessionGroupService,
    SessionGroupServiceError,
    ExhibitorService,
    ExhibitorServiceError,
)

logger = logging.getLogger(__name__)


class ExhibitorList(APIView):
    def get(self, request):
        exhibitors = ExhibitorService.list(request.user)
        serializer = ExhibitorSerializer(exhibitors, many=True)
        return Response(serializer.data)


class ExhibitorDetail(APIView):
    def get(self, request, year, month, session_group_id):
        try:
            exhibitor = ExhibitorService.get(year, month, session_group_id, request.user)
            serializer = ExhibitorSerializer(exhibitor)
            return Response(serializer.data)
        except ExhibitorServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, year, month, session_group_id):
        try:
            session_group = SessionGroup.objects.get(id=session_group_id, user=request.user)
        except SessionGroup.DoesNotExist:
            return Response({"error": "Session group not found"}, status=status.HTTP_404_NOT_FOUND)

        schedule_data = request.data.get("scheduleData")
        schedule_statistics = request.data.get("statistics")
        days_with_details = request.data.get("daysWithDetails")

        exhibitor, created = Exhibitor.objects.get_or_create(
            year=year, month=month, session_group=session_group
        )
        if not created:
            return Response(
                {"error": "Schedule already exists for this month and session group"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        exhibitor.schedule_data = schedule_data
        exhibitor.schedule_statistics = schedule_statistics
        exhibitor.days_with_details = days_with_details
        exhibitor.save()

        serializer = ExhibitorSerializer(exhibitor)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def put(self, request, year, month, session_group_id):
        try:
            exhibitor = ExhibitorService.get(year, month, session_group_id, request.user)
        except ExhibitorServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        exhibitor.schedule_data = request.data.get("scheduleData")
        exhibitor.schedule_statistics = request.data.get("statistics")
        exhibitor.days_with_details = request.data.get("daysWithDetails")
        exhibitor.save()

        serializer = ExhibitorSerializer(exhibitor)
        return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["POST"])
def generateScheduleData(request):
    year = request.data.get("year")
    month = request.data.get("month")
    session_group_id = request.data.get("sessionGroupId")
    exclude_session_occurrences = request.data.get("excludeSessionOccurrences", [])

    if not year or not month or not session_group_id:
        return Response(
            {"error": "Year, month, and sessionGroupId are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        year = int(year)
        month = int(month)
        session_group_id = int(session_group_id)
    except ValueError:
        return Response(
            {"error": "Year, month, and sessionGroupId must be integers"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = SchedulerService.generate(
            year, month, session_group_id, request.user, exclude_session_occurrences
        )
        return Response(
            {
                "scheduleData": result["schedule_data"],
                "statistics": result["statistics"],
                "daysWithDetails": result["days_with_details"],
            },
            status=status.HTTP_200_OK,
        )
    except SchedulerNotFoundError as e:
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
    except SchedulerValidationError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except SchedulerInfeasible as e:
        return Response(
            {"error": str(e), "reasons": e.reasons},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except SchedulerServiceError as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        logger.error(f"Error generating schedule: {str(e)}", exc_info=True)
        return Response(
            {"error": "An error occurred while generating the schedule"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ParticipantViewSet(viewsets.ModelViewSet):
    queryset = Participant.objects.all()
    serializer_class = ParticipantSerializer
    lookup_field = "id"

    def get_queryset(self):
        return Participant.objects.filter(session_group__user=self.request.user)

    def list(self, request, *args, **kwargs):
        session_group_id = request.query_params.get("sessionGroupId")
        try:
            sg_id = int(session_group_id) if session_group_id else None
        except ValueError:
            sg_id = None
        participants = ParticipantService.list(request.user, sg_id)
        serializer = self.get_serializer(participants, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        try:
            participant = ParticipantService.get(int(kwargs["id"]), request.user)
            serializer = self.get_serializer(participant)
            return Response(serializer.data)
        except ParticipantServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            traits = serializer.validated_data.pop("traits", [])
            participant = ParticipantService.create(serializer.validated_data, request.user)
            if traits:
                participant.traits.set(traits)
            response_serializer = self.get_serializer(participant)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except ParticipantServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as e:
            return Response(e.message_dict if hasattr(e, "message_dict") else {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            traits = serializer.validated_data.pop("traits", None)
            participant = ParticipantService.update(
                instance.id, serializer.validated_data, request.user, partial
            )
            if traits is not None:
                participant.traits.set(traits)
            response_serializer = self.get_serializer(participant)
            return Response(response_serializer.data)
        except ParticipantServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as e:
            return Response(e.message_dict if hasattr(e, "message_dict") else {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        try:
            ParticipantService.delete(int(kwargs["id"]), request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ParticipantServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)


class SessionGroupList(APIView):
    def get(self, request):
        groups = SessionGroupService.list(request.user)
        serializer = SessionGroupSerializer(groups, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = SessionGroupSerializer(data=request.data)
        if serializer.is_valid():
            sessions_data = serializer.validated_data.pop("sessions_data", None)
            try:
                group = SessionGroupService.create(
                    name=serializer.validated_data.get("name"),
                    user=request.user,
                    sessions_data=sessions_data,
                    scheduler_config=serializer.validated_data.get("scheduler_config"),
                )
                response_serializer = SessionGroupSerializer(group)
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            except SessionGroupServiceError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SessionGroupDetail(APIView):
    def get(self, request, group_id):
        try:
            group = SessionGroupService.get(group_id, request.user)
            serializer = SessionGroupSerializer(group)
            return Response(serializer.data)
        except SessionGroupServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, group_id):
        serializer = SessionGroupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            sessions_data = serializer.validated_data.pop("sessions_data", None)
            group = SessionGroupService.update(
                group_id=group_id,
                user=request.user,
                name=serializer.validated_data.get("name"),
                sessions_data=sessions_data,
                scheduler_config=serializer.validated_data.get("scheduler_config"),
            )
            response_serializer = SessionGroupSerializer(group)
            return Response(response_serializer.data)
        except SessionGroupServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, group_id):
        try:
            SessionGroupService.delete(group_id, request.user)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except SessionGroupServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)


class SessionList(APIView):
    def post(self, request, group_id):
        try:
            group = SessionGroupService.get(group_id, request.user)
        except SessionGroupServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        serializer = SessionSerializer(data=request.data)
        if serializer.is_valid():
            session = serializer.save(session_group=group)
            response_serializer = SessionSerializer(session)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SessionDetail(APIView):
    def put(self, request, group_id, session_id):
        try:
            group = SessionGroupService.get(group_id, request.user)
        except SessionGroupServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        session = get_object_or_404(Session, id=session_id, session_group=group)
        serializer = SessionSerializer(session, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, group_id, session_id):
        try:
            group = SessionGroupService.get(group_id, request.user)
        except SessionGroupServiceError as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        session = get_object_or_404(Session, id=session_id, session_group=group)
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ParticipantTraitViewSet(viewsets.ModelViewSet):
    queryset = ParticipantTrait.objects.all()
    serializer_class = ParticipantTraitSerializer
    lookup_field = "id"

    def get_queryset(self):
        queryset = ParticipantTrait.objects.filter(session_group__user=self.request.user)
        session_group_id = self.request.query_params.get("sessionGroupId")
        if session_group_id:
            try:
                queryset = queryset.filter(session_group_id=int(session_group_id))
            except ValueError:
                queryset = queryset.none()
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session_group = serializer.validated_data.get("session_group")
        if session_group and session_group.user != request.user:
            return Response(
                {"sessionGroupId": "Session group not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        participants = serializer.validated_data.pop("participants", [])
        self.perform_create(serializer)

        if participants:
            serializer.instance.participants.set(participants)

        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        participants = serializer.validated_data.pop("participants", None)
        self.perform_update(serializer)

        if participants is not None:
            serializer.instance.participants.set(participants)

        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)
