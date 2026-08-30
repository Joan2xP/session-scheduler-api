import logging
from exhibitors.models import Exhibitor, SessionGroup
from exhibitors.services.SessionScheduler import SessionScheduler, SchedulerInfeasibleError

logger = logging.getLogger(__name__)


class SchedulerServiceError(Exception):
    pass


class SchedulerNotFoundError(SchedulerServiceError):
    pass


class SchedulerValidationError(SchedulerServiceError):
    pass


class SchedulerInfeasible(SchedulerServiceError):
    """Raised when the schedule is infeasible. Carries human-readable reasons."""

    def __init__(self, message, reasons=None):
        super().__init__(message)
        self.reasons = reasons or []


class SchedulerService:

    @staticmethod
    def generate(year, month, session_group_id, user, exclude_session_occurrences=None):
        if not (1 <= month <= 12):
            raise SchedulerValidationError("Month must be between 1 and 12")

        try:
            session_group = SessionGroup.objects.get(id=session_group_id, user=user)
        except SessionGroup.DoesNotExist:
            raise SchedulerNotFoundError(f"SessionGroup with id {session_group_id} does not exist")

        start_date = f"{year}-{month:02d}-01"
        scheduler_config = session_group.get_scheduler_config()

        scheduler = SessionScheduler(
            start_date=start_date,
            session_group_id=session_group_id,
            exclude_session_occurrences=exclude_session_occurrences or [],
            scheduler_config=scheduler_config,
        )

        try:
            result = scheduler.solve_group_scheduling()
        except SchedulerInfeasibleError as e:
            raise SchedulerInfeasible(str(e), reasons=e.reasons)

        if not result:
            raise SchedulerServiceError("Could not generate schedule")

        schedule_data, schedule_statistics, days_with_details = result
        return {
            "schedule_data": schedule_data,
            "statistics": schedule_statistics,
            "days_with_details": days_with_details,
        }

    @staticmethod
    def save_schedule(year, month, session_group_id, user, schedule_data, statistics, days_with_details):
        try:
            session_group = SessionGroup.objects.get(id=session_group_id, user=user)
        except SessionGroup.DoesNotExist:
            raise SchedulerNotFoundError("Session group not found")

        exhibitor, created = Exhibitor.objects.get_or_create(
            year=year, month=month, session_group=session_group
        )
        exhibitor.schedule_data = schedule_data
        exhibitor.schedule_statistics = statistics
        exhibitor.days_with_details = days_with_details
        exhibitor.save()

        return exhibitor, created
