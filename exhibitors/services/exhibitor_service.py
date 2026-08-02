import logging
from exhibitors.models import Exhibitor

logger = logging.getLogger(__name__)


class ExhibitorServiceError(Exception):
    pass


class ExhibitorService:

    @staticmethod
    def list(user):
        return list(Exhibitor.objects.filter(session_group__user=user))

    @staticmethod
    def get(year, month, session_group_id, user):
        try:
            return Exhibitor.objects.get(
                year=year, month=month, session_group_id=session_group_id,
                session_group__user=user
            )
        except Exhibitor.DoesNotExist:
            raise ExhibitorServiceError(
                f"Exhibitor not found for year {year}, month {month}, session group {session_group_id}"
            )
