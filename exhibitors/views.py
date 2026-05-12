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
from .services.SessionScheduler import SessionScheduler

logger = logging.getLogger(__name__)


class ExhibitorList(APIView):
    """List all exhibitors"""

    def get(self, request):
        exhibitors = Exhibitor.objects.filter(session_group__user=request.user)
        serializer = ExhibitorSerializer(exhibitors, many=True)
        return Response(serializer.data)


class ExhibitorDetail(APIView):
    """Retrieve, create, or update an exhibitor by year, month, and session group"""

    def get(self, request, year, month, session_group_id):
        try:
            exhibitor = Exhibitor.objects.get(
                year=year, month=month, session_group_id=session_group_id,
                session_group__user=request.user
            )
            serializer = ExhibitorSerializer(exhibitor)
            return Response(serializer.data)
        except Exhibitor.DoesNotExist:
            return Response(
                {"error": f"Exhibitor not found for year {year}, month {month}, session group {session_group_id}"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def post(self, request, year, month, session_group_id):
        """Create a new exhibitor schedule"""
        # Validate session group belongs to user
        try:
            session_group = SessionGroup.objects.get(id=session_group_id, user=request.user)
        except SessionGroup.DoesNotExist:
            return Response(
                {"error": "Session group not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

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
        """Update an existing exhibitor schedule"""
        try:
            exhibitor = Exhibitor.objects.get(
                year=year, month=month, session_group_id=session_group_id,
                session_group__user=request.user
            )
        except Exhibitor.DoesNotExist:
            return Response(
                {"error": f"Exhibitor not found for year {year}, month {month}, session group {session_group_id}"},
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
    """Generate schedule data for a given year, month, and session group"""
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

        # Validate month range
        if not (1 <= month <= 12):
            return Response(
                {"error": "Month must be between 1 and 12"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate session_group_id exists and belongs to user
        try:
            SessionGroup.objects.get(id=session_group_id, user=request.user)
        except SessionGroup.DoesNotExist:
            return Response(
                {"error": f"SessionGroup with id {session_group_id} does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )
    except ValueError:
        return Response(
            {"error": "Year, month, and sessionGroupId must be integers"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        start_date = f"{year}-{month:02d}-01"

        # Get session group with scheduler config
        session_group = SessionGroup.objects.get(id=session_group_id, user=request.user)
        scheduler_config = session_group.get_scheduler_config()

        schedule_generator = SessionScheduler(
            start_date=start_date,
            session_group_id=session_group_id,
            exclude_session_occurrences=exclude_session_occurrences,
            scheduler_config=scheduler_config,
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

    def get_queryset(self):
        """Filter participants by user and optional sessionGroupId"""
        queryset = Participant.objects.filter(session_group__user=self.request.user)
        session_group_id = self.request.query_params.get("sessionGroupId")
        if session_group_id:
            try:
                queryset = queryset.filter(session_group_id=int(session_group_id))
            except ValueError:
                queryset = queryset.none()
        return queryset

    def create(self, request, *args, **kwargs):
        """Create a new participant with validation"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Validate session_group belongs to user
        session_group = serializer.validated_data.get("session_group")
        if session_group and session_group.user != request.user:
            return Response(
                {"sessionGroupId": "Session group not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Additional validation for same session group
        self._validate_same_session_group(serializer.validated_data, None)

        traits = serializer.validated_data.pop("traits", [])
        self.perform_create(serializer)

        # Handle M2M traits
        if traits:
            serializer.instance.traits.set(traits)

        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def update(self, request, *args, **kwargs):
        """Update a participant with validation"""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        # Prevent session_group_id changes
        if "session_group" in serializer.validated_data:
            if (
                serializer.validated_data["session_group"].id
                != instance.session_group_id
            ):
                return Response(
                    {
                        "sessionGroupId": "sessionGroupId cannot be changed after creation"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Additional validation for same session group
        self._validate_same_session_group(serializer.validated_data, instance)

        traits = serializer.validated_data.pop("traits", None)
        self.perform_update(serializer)

        # Handle M2M traits (only if provided)
        if traits is not None:
            serializer.instance.traits.set(traits)

        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        """Partial update a participant with validation"""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def _validate_same_session_group(self, validated_data, instance):
        """Validate that all referenced IDs belong to the same session group"""
        # Get the session group ID (from instance if updating, from data if creating)
        if instance:
            session_group_id = instance.session_group_id
        else:
            if "session_group" in validated_data:
                session_group_id = validated_data["session_group"].id
            else:
                return  # No session group to validate against

        errors = {}

        # Validate partner_id
        if "partner" in validated_data and validated_data["partner"]:
            partner = validated_data["partner"]
            if partner.session_group_id != session_group_id:
                errors["partnerId"] = "Partner must belong to the same session group"

        # Validate exclude_ids
        if "exclude_ids" in validated_data and validated_data["exclude_ids"]:
            exclude_ids = validated_data["exclude_ids"]
            if isinstance(exclude_ids, list):
                invalid_ids = []
                for participant_id in exclude_ids:
                    try:
                        excluded = Participant.objects.get(id=participant_id)
                        if excluded.session_group_id != session_group_id:
                            invalid_ids.append(participant_id)
                    except Participant.DoesNotExist:
                        invalid_ids.append(participant_id)
                if invalid_ids:
                    errors["excludeIds"] = (
                        f"Participants {invalid_ids} do not exist or "
                        "do not belong to the same session group"
                    )

        # Validate availability session IDs
        if "availability" in validated_data and validated_data["availability"]:
            availability = validated_data["availability"]
            if isinstance(availability, list):
                invalid_ids = []
                for session_id in availability:
                    try:
                        session = Session.objects.get(id=session_id)
                        if session.session_group_id != session_group_id:
                            invalid_ids.append(session_id)
                    except Session.DoesNotExist:
                        invalid_ids.append(session_id)
                if invalid_ids:
                    errors["availability"] = (
                        f"Sessions {invalid_ids} do not exist or "
                        "do not belong to the same session group"
                    )

        # Validate only_session_occurrences
        if (
            "only_session_occurrences" in validated_data
            and validated_data["only_session_occurrences"]
        ):
            occurrences = validated_data["only_session_occurrences"]
            if isinstance(occurrences, list):
                invalid_occurrences = []
                for idx, occurrence in enumerate(occurrences):
                    if isinstance(occurrence, dict):
                        session_id = occurrence.get("sessionId")
                        if session_id:
                            try:
                                session = Session.objects.get(id=session_id)
                                if session.session_group_id != session_group_id:
                                    invalid_occurrences.append(
                                        f"index {idx}: session {session_id} not in same group"
                                    )
                            except Session.DoesNotExist:
                                invalid_occurrences.append(
                                    f"index {idx}: session {session_id} does not exist"
                                )
                if invalid_occurrences:
                    errors["onlySessionOccurrences"] = (
                        f"Invalid occurrences: {', '.join(invalid_occurrences)}"
                    )

        # Validate exclude_session_occurrences
        if (
            "exclude_session_occurrences" in validated_data
            and validated_data["exclude_session_occurrences"]
        ):
            occurrences = validated_data["exclude_session_occurrences"]
            if isinstance(occurrences, list):
                invalid_occurrences = []
                for idx, occurrence in enumerate(occurrences):
                    if isinstance(occurrence, dict):
                        session_id = occurrence.get("sessionId")
                        if session_id:
                            try:
                                session = Session.objects.get(id=session_id)
                                if session.session_group_id != session_group_id:
                                    invalid_occurrences.append(
                                        f"index {idx}: session {session_id} not in same group"
                                    )
                            except Session.DoesNotExist:
                                invalid_occurrences.append(
                                    f"index {idx}: session {session_id} does not exist"
                                )
                if invalid_occurrences:
                    errors["excludeSessionOccurrences"] = (
                        f"Invalid occurrences: {', '.join(invalid_occurrences)}"
                    )

        # Validate min_sessions_together
        if (
            "min_sessions_together" in validated_data
            and validated_data["min_sessions_together"]
        ):
            min_together = validated_data["min_sessions_together"]
            if isinstance(min_together, dict):
                session_id = min_together.get("sessionId")
                partner_id = min_together.get("partnerId")

                if session_id:
                    try:
                        session = Session.objects.get(id=session_id)
                        if session.session_group_id != session_group_id:
                            errors["minSessionsTogether"] = (
                                "Session does not belong to the same session group"
                            )
                    except Session.DoesNotExist:
                        errors["minSessionsTogether"] = "Session does not exist"

                if partner_id:
                    try:
                        partner = Participant.objects.get(id=partner_id)
                        if partner.session_group_id != session_group_id:
                            errors["minSessionsTogether"] = (
                                errors.get("minSessionsTogether", "")
                                + " Partner does not belong to the same session group"
                            ).strip()
                    except Participant.DoesNotExist:
                        errors["minSessionsTogether"] = (
                            errors.get("minSessionsTogether", "")
                            + " Partner does not exist"
                        ).strip()

        if errors:
            raise ValidationError(errors)


class SessionGroupList(APIView):
    """List all session groups or create a new one"""

    def get(self, request):
        groups = SessionGroup.objects.prefetch_related("sessions").filter(user=request.user)
        serializer = SessionGroupSerializer(groups, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new session group with optional sessions"""
        serializer = SessionGroupSerializer(data=request.data)
        if serializer.is_valid():
            sessions_data = serializer.validated_data.pop("sessions_data", None)
            group = SessionGroup.objects.create(user=request.user, **serializer.validated_data)

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
            SessionGroup.objects.prefetch_related("sessions"), id=group_id, user=request.user
        )
        serializer = SessionGroupSerializer(group)
        return Response(serializer.data)

    def put(self, request, group_id):
        """Update a session group"""
        group = get_object_or_404(SessionGroup, id=group_id, user=request.user)
        serializer = SessionGroupSerializer(group, data=request.data)
        if serializer.is_valid():
            sessions_data = serializer.validated_data.pop("sessions_data", None)
            serializer.save()

            # Update nested sessions if provided
            if sessions_data is not None:
                # Get IDs of sessions that should be kept/updated
                session_ids = [s.get("id") for s in sessions_data if s.get("id")]
                
                # Delete sessions not in the new array
                group.sessions.exclude(id__in=session_ids).delete()
                
                # Update or create sessions
                for session_data in sessions_data:
                    session_id = session_data.get("id")
                    if session_id:
                        session = get_object_or_404(
                            Session, id=session_id, session_group=group
                        )
                        session_serializer = SessionSerializer(
                            session, data=session_data
                        )
                    else:
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
        group = get_object_or_404(SessionGroup, id=group_id, user=request.user)
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionList(APIView):
    """Create a new session in a group"""

    def post(self, request, group_id):
        """Create a new session"""
        group = get_object_or_404(SessionGroup, id=group_id, user=request.user)
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
        group = get_object_or_404(SessionGroup, id=group_id, user=request.user)
        session = get_object_or_404(Session, id=session_id, session_group=group)
        serializer = SessionSerializer(session, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, group_id, session_id):
        """Delete a session"""
        group = get_object_or_404(SessionGroup, id=group_id, user=request.user)
        session = get_object_or_404(Session, id=session_id, session_group=group)
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ParticipantTraitViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and editing ParticipantTrait instances.
    Provides list, create, retrieve, update, partial_update, and destroy actions.
    """

    queryset = ParticipantTrait.objects.all()
    serializer_class = ParticipantTraitSerializer
    lookup_field = "id"

    def get_queryset(self):
        """Filter traits by user and optional sessionGroupId"""
        queryset = ParticipantTrait.objects.filter(session_group__user=self.request.user)
        session_group_id = self.request.query_params.get("sessionGroupId")
        if session_group_id:
            try:
                queryset = queryset.filter(session_group_id=int(session_group_id))
            except ValueError:
                queryset = queryset.none()
        return queryset

    def create(self, request, *args, **kwargs):
        """Create a new trait"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Validate session_group belongs to user
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
        """Update a trait"""
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
        """Partial update a trait"""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)
