import logging
from django.core.exceptions import ValidationError
from exhibitors.models import Participant, SessionGroup, Session, ParticipantTrait

logger = logging.getLogger(__name__)


class ParticipantServiceError(Exception):
    pass


class ParticipantService:

    @staticmethod
    def list(user, session_group_id=None):
        queryset = Participant.objects.filter(session_group__user=user)
        if session_group_id:
            queryset = queryset.filter(session_group_id=session_group_id)
        return list(queryset.select_related("partner", "session_group").prefetch_related("traits"))

    @staticmethod
    def get(participant_id, user):
        try:
            return Participant.objects.select_related("partner", "session_group").prefetch_related("traits").get(
                id=participant_id, session_group__user=user
            )
        except Participant.DoesNotExist:
            raise ParticipantServiceError("Participant not found")

    @staticmethod
    def create(data, user):
        session_group = data.get("session_group")
        if session_group and session_group.user != user:
            raise ParticipantServiceError("Session group not found")

        session_group_id = session_group.id if session_group else None
        ParticipantService._validate_same_session_group(data, None, session_group_id)

        traits = data.pop("traits", [])
        participant = Participant.objects.create(**data)

        if traits:
            participant.traits.set(traits)

        return participant

    @staticmethod
    def update(participant_id, data, user, partial=False):
        participant = ParticipantService.get(participant_id, user)

        if "session_group" in data:
            if data["session_group"].id != participant.session_group_id:
                raise ParticipantServiceError("sessionGroupId cannot be changed after creation")

        session_group_id = participant.session_group_id
        ParticipantService._validate_same_session_group(data, participant, session_group_id)

        traits = data.pop("traits", None)

        for field, value in data.items():
            setattr(participant, field, value)
        participant.save()

        if traits is not None:
            participant.traits.set(traits)

        return participant

    @staticmethod
    def delete(participant_id, user):
        participant = ParticipantService.get(participant_id, user)
        participant.delete()

    @staticmethod
    def _validate_same_session_group(data, instance, session_group_id):
        if not session_group_id:
            return

        errors = {}

        if "partner" in data and data["partner"]:
            partner = data["partner"]
            if hasattr(partner, "session_group_id") and partner.session_group_id != session_group_id:
                errors["partnerId"] = "Partner must belong to the same session group"

        if "exclude_ids" in data and data["exclude_ids"]:
            exclude_ids = data["exclude_ids"]
            if isinstance(exclude_ids, list):
                invalid_ids = []
                for pid in exclude_ids:
                    try:
                        excluded = Participant.objects.get(id=pid)
                        if excluded.session_group_id != session_group_id:
                            invalid_ids.append(pid)
                    except Participant.DoesNotExist:
                        invalid_ids.append(pid)
                if invalid_ids:
                    errors["excludeIds"] = (
                        f"Participants {invalid_ids} do not exist or do not belong to the same session group"
                    )

        if "availability" in data and data["availability"]:
            availability = data["availability"]
            if isinstance(availability, list):
                invalid_ids = []
                for sid in availability:
                    try:
                        session = Session.objects.get(id=sid)
                        if session.session_group_id != session_group_id:
                            invalid_ids.append(sid)
                    except Session.DoesNotExist:
                        invalid_ids.append(sid)
                if invalid_ids:
                    errors["availability"] = (
                        f"Sessions {invalid_ids} do not exist or do not belong to the same session group"
                    )

        if "only_session_occurrences" in data and data["only_session_occurrences"]:
            occurrences = data["only_session_occurrences"]
            if isinstance(occurrences, list):
                invalid = []
                for idx, occ in enumerate(occurrences):
                    if isinstance(occ, dict):
                        sid = occ.get("sessionId")
                        if sid:
                            try:
                                session = Session.objects.get(id=sid)
                                if session.session_group_id != session_group_id:
                                    invalid.append(f"index {idx}: session {sid} not in same group")
                            except Session.DoesNotExist:
                                invalid.append(f"index {idx}: session {sid} does not exist")
                if invalid:
                    errors["onlySessionOccurrences"] = f"Invalid occurrences: {', '.join(invalid)}"

        if "exclude_session_occurrences" in data and data["exclude_session_occurrences"]:
            occurrences = data["exclude_session_occurrences"]
            if isinstance(occurrences, list):
                invalid = []
                for idx, occ in enumerate(occurrences):
                    if isinstance(occ, dict):
                        sid = occ.get("sessionId")
                        if sid:
                            try:
                                session = Session.objects.get(id=sid)
                                if session.session_group_id != session_group_id:
                                    invalid.append(f"index {idx}: session {sid} not in same group")
                            except Session.DoesNotExist:
                                invalid.append(f"index {idx}: session {sid} does not exist")
                if invalid:
                    errors["excludeSessionOccurrences"] = f"Invalid occurrences: {', '.join(invalid)}"

        if "min_sessions_together" in data and data["min_sessions_together"]:
            min_together = data["min_sessions_together"]
            if isinstance(min_together, dict):
                sid = min_together.get("sessionId")
                pid = min_together.get("partnerId")
                if sid:
                    try:
                        session = Session.objects.get(id=sid)
                        if session.session_group_id != session_group_id:
                            errors["minSessionsTogether"] = "Session does not belong to the same session group"
                    except Session.DoesNotExist:
                        errors["minSessionsTogether"] = "Session does not exist"
                if pid:
                    try:
                        partner = Participant.objects.get(id=pid)
                        if partner.session_group_id != session_group_id:
                            existing = errors.get("minSessionsTogether", "")
                            errors["minSessionsTogether"] = (
                                existing + " Partner does not belong to the same session group"
                            ).strip()
                    except Participant.DoesNotExist:
                        existing = errors.get("minSessionsTogether", "")
                        errors["minSessionsTogether"] = (
                            existing + " Partner does not exist"
                        ).strip()

        if errors:
            raise ValidationError(errors)
