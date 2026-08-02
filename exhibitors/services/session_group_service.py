import logging
from exhibitors.models import SessionGroup, Session
from exhibitors.serializers import SessionSerializer

logger = logging.getLogger(__name__)


class SessionGroupServiceError(Exception):
    pass


class SessionGroupService:

    @staticmethod
    def list(user):
        return list(SessionGroup.objects.prefetch_related("sessions").filter(user=user))

    @staticmethod
    def get(group_id, user):
        try:
            return SessionGroup.objects.prefetch_related("sessions").get(id=group_id, user=user)
        except SessionGroup.DoesNotExist:
            raise SessionGroupServiceError("Session group not found")

    @staticmethod
    def create(name, user, sessions_data=None, scheduler_config=None):
        group = SessionGroup.objects.create(
            user=user,
            name=name,
            scheduler_config=scheduler_config or {},
        )

        if sessions_data:
            for session_data in sessions_data:
                session_serializer = SessionSerializer(data=session_data)
                if session_serializer.is_valid():
                    session_serializer.save(session_group=group)
                else:
                    group.delete()
                    raise SessionGroupServiceError(f"Invalid session data: {session_serializer.errors}")

        return group

    @staticmethod
    def update(group_id, user, name=None, sessions_data=None, scheduler_config=None):
        group = SessionGroupService.get(group_id, user)

        if name is not None:
            group.name = name
        if scheduler_config is not None:
            group.scheduler_config = scheduler_config
        group.save()

        if sessions_data is not None:
            session_ids = [s.get("id") for s in sessions_data if s.get("id")]
            group.sessions.exclude(id__in=session_ids).delete()

            for session_data in sessions_data:
                session_id = session_data.get("id")
                if session_id:
                    try:
                        session = Session.objects.get(id=session_id, session_group=group)
                    except Session.DoesNotExist:
                        raise SessionGroupServiceError(f"Session {session_id} not found in group")
                    session_serializer = SessionSerializer(session, data=session_data)
                else:
                    session_serializer = SessionSerializer(data=session_data)

                if session_serializer.is_valid():
                    session_serializer.save(session_group=group)
                else:
                    raise SessionGroupServiceError(f"Invalid session data: {session_serializer.errors}")

        return group

    @staticmethod
    def delete(group_id, user):
        group = SessionGroupService.get(group_id, user)
        group.delete()
