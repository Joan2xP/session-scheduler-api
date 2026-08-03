import json
import logging
from datetime import datetime

from django.core.cache import cache

from exhibitors.services import (
    SchedulerService,
    ParticipantService,
    SessionGroupService,
    ExhibitorService,
)
from .provider import ToolDefinition

logger = logging.getLogger(__name__)

SCHEDULE_CACHE_TTL = 3600


def _schedule_cache_key(user_id, session_group_id, year, month):
    return f"ai:sched:{user_id}:{session_group_id}:{year}:{month}"


def _serialize_participant(p, fields=None):
    data = {
        "id": p.id,
        "name": p.name,
        "sessionGroupId": p.session_group_id,
        "isAnchor": p.is_anchor,
    }
    if fields:
        field_set = set(fields)
        extras = {
            "maxPerWeek": p.max_per_week,
            "maxPerMonth": p.max_per_month,
            "minPerMonth": p.min_per_month,
            "partnerId": p.partner_id,
            "availability": p.availability,
            "excludeIds": p.exclude_ids,
            "onlySessionOccurrences": p.only_session_occurrences,
            "excludeSessionOccurrences": p.exclude_session_occurrences,
            "minSessionsTogether": p.min_sessions_together,
            "enforcedWeekDays": p.enforced_week_days,
            "traitIds": [t.id for t in p.traits.all()],
        }
        for key in field_set:
            if key in extras:
                data[key] = extras[key]
    return data


def _serialize_participant_full(p):
    return {
        "id": p.id,
        "name": p.name,
        "sessionGroupId": p.session_group_id,
        "maxPerWeek": p.max_per_week,
        "maxPerMonth": p.max_per_month,
        "minPerMonth": p.min_per_month,
        "partnerId": p.partner_id,
        "availability": p.availability,
        "excludeIds": p.exclude_ids,
        "onlySessionOccurrences": p.only_session_occurrences,
        "excludeSessionOccurrences": p.exclude_session_occurrences,
        "minSessionsTogether": p.min_sessions_together,
        "enforcedWeekDays": p.enforced_week_days,
        "isAnchor": p.is_anchor,
        "traitIds": [t.id for t in p.traits.all()],
    }


def _serialize_session_group(g, fields=None):
    data = {
        "id": g.id,
        "name": g.name,
        "sessionCount": g.sessions.count(),
    }
    if fields:
        field_set = set(fields)
        if "sessions" in field_set:
            data["sessions"] = [
                {
                    "id": s.id,
                    "frequency": s.frequency,
                    "startHour": s.start_hour,
                    "startMinute": s.start_minute,
                    "endHour": s.end_hour,
                    "endMinute": s.end_minute,
                    "week": s.week,
                    "dayOfWeek": s.day_of_week,
                    "month": s.month,
                    "location": s.location,
                }
                for s in g.sessions.all()
            ]
        if "schedulerConfig" in field_set:
            data["schedulerConfig"] = g.get_scheduler_config()
    return data


def _serialize_session_group_full(g):
    return {
        "id": g.id,
        "name": g.name,
        "sessions": [
            {
                "id": s.id,
                "frequency": s.frequency,
                "startHour": s.start_hour,
                "startMinute": s.start_minute,
                "endHour": s.end_hour,
                "endMinute": s.end_minute,
                "week": s.week,
                "dayOfWeek": s.day_of_week,
                "month": s.month,
                "location": s.location,
            }
            for s in g.sessions.all()
        ],
        "schedulerConfig": g.get_scheduler_config(),
    }


def _serialize_exhibitor_summary(e):
    return {
        "year": e.year,
        "month": e.month,
        "sessionGroupId": e.session_group_id,
    }


def _serialize_exhibitor(e, fields=None):
    data = _serialize_exhibitor_summary(e)
    if fields:
        field_set = set(fields)
        if "statistics" in field_set:
            data["statistics"] = e.schedule_statistics
        if "scheduleData" in field_set:
            data["scheduleData"] = e.schedule_data
        if "daysWithDetails" in field_set:
            data["daysWithDetails"] = e.days_with_details
    return data


def _serialize_schedule_summary(result):
    schedule_data = result["schedule_data"]
    statistics = result["statistics"]
    days_with_details = result["days_with_details"]

    participant_names = set()
    total_assignments = 0
    for week in schedule_data:
        for session in week.get("sessions", []):
            for member in session.get("members", []):
                participant_names.add(member.get("name", ""))
                total_assignments += 1

    return {
        "statistics": statistics,
        "summary": {
            "weekCount": len(schedule_data),
            "sessionCount": len(days_with_details),
            "participantCount": len(participant_names),
            "totalAssignments": total_assignments,
        },
    }


def list_session_groups(params, user):
    fields = params.get("fields")
    groups = SessionGroupService.list(user)
    return [_serialize_session_group(g, fields) for g in groups]


def get_session_group(params, user):
    group_id = params.get("sessionGroupId")
    group = SessionGroupService.get(group_id, user)
    return _serialize_session_group_full(group)


def list_participants(params, user):
    fields = params.get("fields")
    session_group_id = params.get("sessionGroupId")
    participants = ParticipantService.list(user, session_group_id)
    return [_serialize_participant(p, fields) for p in participants]


def get_participant(params, user):
    participant_id = params.get("participantId")
    participant = ParticipantService.get(participant_id, user)
    return _serialize_participant_full(participant)


def create_participant(params, user):
    from exhibitors.models import SessionGroup
    session_group = SessionGroup.objects.get(id=params["sessionGroupId"], user=user)
    data = {
        "session_group": session_group,
        "name": params["name"],
        "max_per_week": params["maxPerWeek"],
        "max_per_month": params["maxPerMonth"],
        "min_per_month": params["minPerMonth"],
        "partner": None,
        "availability": params.get("availability"),
        "exclude_ids": params.get("excludeIds"),
        "only_session_occurrences": params.get("onlySessionOccurrences"),
        "exclude_session_occurrences": params.get("excludeSessionOccurrences"),
        "min_sessions_together": params.get("minSessionsTogether"),
        "enforced_week_days": params.get("enforcedWeekDays"),
        "is_anchor": params.get("isAnchor", False),
    }
    participant = ParticipantService.create(data, user)
    return _serialize_participant_full(participant)


def update_participant(params, user):
    participant_id = params.pop("participantId")
    field_mapping = {
        "name": "name",
        "maxPerWeek": "max_per_week",
        "maxPerMonth": "max_per_month",
        "minPerMonth": "min_per_month",
        "availability": "availability",
        "excludeIds": "exclude_ids",
        "onlySessionOccurrences": "only_session_occurrences",
        "excludeSessionOccurrences": "exclude_session_occurrences",
        "minSessionsTogether": "min_sessions_together",
        "enforcedWeekDays": "enforced_week_days",
        "isAnchor": "is_anchor",
    }
    data = {}
    for camel_key, snake_key in field_mapping.items():
        if camel_key in params:
            data[snake_key] = params[camel_key]
    participant = ParticipantService.update(participant_id, data, user)
    return _serialize_participant_full(participant)


def delete_participant(params, user):
    participant_id = params.get("participantId")
    ParticipantService.delete(participant_id, user)
    return {"success": True, "message": f"Participant {participant_id} deleted"}


def bulk_update_participants(params, user):
    updates = params.get("updates", [])
    field_mapping = {
        "name": "name",
        "maxPerWeek": "max_per_week",
        "maxPerMonth": "max_per_month",
        "minPerMonth": "min_per_month",
        "availability": "availability",
        "excludeIds": "exclude_ids",
        "onlySessionOccurrences": "only_session_occurrences",
        "excludeSessionOccurrences": "exclude_session_occurrences",
        "minSessionsTogether": "min_sessions_together",
        "enforcedWeekDays": "enforced_week_days",
        "isAnchor": "is_anchor",
    }
    results = []
    for item in updates:
        participant_id = item.get("participantId")
        if not participant_id:
            results.append({"error": "Missing participantId"})
            continue
        data = {}
        for camel_key, snake_key in field_mapping.items():
            if camel_key in item:
                data[snake_key] = item[camel_key]
        try:
            participant = ParticipantService.update(participant_id, data, user)
            results.append(_serialize_participant_full(participant))
        except Exception as e:
            results.append({"participantId": participant_id, "error": str(e)})
    return {"results": results}


def generate_schedule(params, user):
    year = params.get("year")
    month = params.get("month")
    session_group_id = params.get("sessionGroupId")
    exclude_session_occurrences = params.get("excludeSessionOccurrences", [])

    result = SchedulerService.generate(year, month, session_group_id, user, exclude_session_occurrences)

    cache_key = _schedule_cache_key(user.id, session_group_id, year, month)
    cache.set(cache_key, {
        "schedule_data": result["schedule_data"],
        "statistics": result["statistics"],
        "days_with_details": result["days_with_details"],
    }, SCHEDULE_CACHE_TTL)

    summary = _serialize_schedule_summary(result)
    summary["cached"] = True
    return summary


def save_schedule(params, user):
    year = params.get("year")
    month = params.get("month")
    session_group_id = params.get("sessionGroupId")

    cache_key = _schedule_cache_key(user.id, session_group_id, year, month)
    cached = cache.get(cache_key)
    if not cached:
        return {
            "error": f"No generated schedule found for {month}/{year}. Generate a schedule first.",
        }

    exhibitor, created = SchedulerService.save_schedule(
        year, month, session_group_id, user,
        cached["schedule_data"], cached["statistics"], cached["days_with_details"],
    )
    cache.delete(cache_key)

    return {
        "success": True,
        "created": created,
        "message": "Schedule saved successfully",
    }


def get_schedule(params, user):
    year = params.get("year")
    month = params.get("month")
    session_group_id = params.get("sessionGroupId")
    exhibitor = ExhibitorService.get(year, month, session_group_id, user)

    schedule_data = exhibitor.schedule_data or []
    days_with_details = exhibitor.days_with_details or []
    statistics = exhibitor.schedule_statistics or []

    participant_names = set()
    total_assignments = 0
    for week in schedule_data:
        for session in week.get("sessions", []):
            for member in session.get("members", []):
                participant_names.add(member.get("name", ""))
                total_assignments += 1

    return {
        "year": exhibitor.year,
        "month": exhibitor.month,
        "sessionGroupId": exhibitor.session_group_id,
        "statistics": statistics,
        "summary": {
            "weekCount": len(schedule_data),
            "sessionCount": len(days_with_details),
            "participantCount": len(participant_names),
            "totalAssignments": total_assignments,
        },
    }


def list_schedules(params, user):
    fields = params.get("fields")
    exhibitors = ExhibitorService.list(user)
    return [_serialize_exhibitor(e, fields) for e in exhibitors]


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "list_session_groups": ToolDefinition(
        name="list_session_groups",
        description="List the user's session groups with session counts. Use get_session_group for full details.",
        parameters={
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["sessions", "schedulerConfig"]},
                    "description": "Extra fields to include beyond default (id, name, sessionCount). Options: sessions, schedulerConfig.",
                },
            },
        },
        execute=list_session_groups,
    ),
    "get_session_group": ToolDefinition(
        name="get_session_group",
        description="Get full details of a session group including sessions and scheduler config.",
        parameters={
            "type": "object",
            "properties": {
                "sessionGroupId": {"type": "integer"},
            },
            "required": ["sessionGroupId"],
        },
        execute=get_session_group,
    ),
    "list_participants": ToolDefinition(
        name="list_participants",
        description="List participants with summary info. Optionally filter by session group and request extra fields. Use get_participant for full details.",
        parameters={
            "type": "object",
            "properties": {
                "sessionGroupId": {
                    "type": "integer",
                    "description": "Filter by session group ID",
                },
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "maxPerWeek", "maxPerMonth", "minPerMonth", "partnerId",
                            "availability", "excludeIds", "onlySessionOccurrences",
                            "excludeSessionOccurrences", "minSessionsTogether",
                            "enforcedWeekDays", "traitIds",
                        ],
                    },
                    "description": "Extra fields to include beyond default (id, name, sessionGroupId, isAnchor).",
                },
            },
        },
        execute=list_participants,
    ),
    "get_participant": ToolDefinition(
        name="get_participant",
        description="Get full details of a specific participant.",
        parameters={
            "type": "object",
            "properties": {
                "participantId": {"type": "integer"},
            },
            "required": ["participantId"],
        },
        execute=get_participant,
    ),
    "create_participant": ToolDefinition(
        name="create_participant",
        description="Create a new participant in a session group.",
        parameters={
            "type": "object",
            "properties": {
                "sessionGroupId": {"type": "integer"},
                "name": {"type": "string"},
                "maxPerWeek": {"type": "integer", "description": "Max sessions per week"},
                "maxPerMonth": {"type": "integer", "description": "Max sessions per month"},
                "minPerMonth": {"type": "integer", "description": "Min sessions per month"},
                "availability": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Session IDs the participant is available for",
                },
                "excludeIds": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Participant IDs to avoid scheduling together",
                },
                "isAnchor": {"type": "boolean", "description": "Anchor participant (in most sessions)"},
            },
            "required": ["sessionGroupId", "name", "maxPerWeek", "maxPerMonth", "minPerMonth"],
        },
        execute=create_participant,
    ),
    "update_participant": ToolDefinition(
        name="update_participant",
        description="Update an existing participant's settings.",
        parameters={
            "type": "object",
            "properties": {
                "participantId": {"type": "integer"},
                "name": {"type": "string"},
                "maxPerWeek": {"type": "integer"},
                "maxPerMonth": {"type": "integer"},
                "minPerMonth": {"type": "integer"},
                "availability": {"type": "array", "items": {"type": "integer"}},
                "excludeIds": {"type": "array", "items": {"type": "integer"}},
                "isAnchor": {"type": "boolean"},
            },
            "required": ["participantId"],
        },
        execute=update_participant,
    ),
    "delete_participant": ToolDefinition(
        name="delete_participant",
        description="Delete a participant by ID.",
        parameters={
            "type": "object",
            "properties": {
                "participantId": {"type": "integer"},
            },
            "required": ["participantId"],
        },
        execute=delete_participant,
    ),
    "bulk_update_participants": ToolDefinition(
        name="bulk_update_participants",
        description="Update multiple participants at once. Use this when applying the same kind of change to many participants to avoid individual call overhead.",
        parameters={
            "type": "object",
            "properties": {
                "updates": {
                    "type": "array",
                    "description": "List of participant updates",
                    "items": {
                        "type": "object",
                        "properties": {
                            "participantId": {"type": "integer"},
                            "name": {"type": "string"},
                            "maxPerWeek": {"type": "integer"},
                            "maxPerMonth": {"type": "integer"},
                            "minPerMonth": {"type": "integer"},
                            "availability": {"type": "array", "items": {"type": "integer"}},
                            "excludeIds": {"type": "array", "items": {"type": "integer"}},
                            "isAnchor": {"type": "boolean"},
                        },
                        "required": ["participantId"],
                    },
                },
            },
            "required": ["updates"],
        },
        execute=bulk_update_participants,
    ),
    "generate_schedule": ToolDefinition(
        name="generate_schedule",
        description="Generate and cache a schedule. Returns statistics and summary. Use save_schedule to persist.",
        parameters={
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "sessionGroupId": {"type": "integer"},
                "excludeSessionOccurrences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sessionId": {"type": "integer"},
                            "date": {"type": "string", "description": "YYYY-MM-DD"},
                        },
                        "required": ["sessionId", "date"],
                    },
                    "description": "Session occurrences to exclude",
                },
            },
            "required": ["year", "month", "sessionGroupId"],
        },
        execute=generate_schedule,
    ),
    "save_schedule": ToolDefinition(
        name="save_schedule",
        description="Save a previously generated schedule to the database. Requires generate_schedule to have been called first for the same year/month/session group.",
        parameters={
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "sessionGroupId": {"type": "integer"},
            },
            "required": ["year", "month", "sessionGroupId"],
        },
        execute=save_schedule,
    ),
    "get_schedule": ToolDefinition(
        name="get_schedule",
        description="Get saved schedule statistics and summary for a year/month/session group.",
        parameters={
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "sessionGroupId": {"type": "integer"},
            },
            "required": ["year", "month", "sessionGroupId"],
        },
        execute=get_schedule,
    ),
    "list_schedules": ToolDefinition(
        name="list_schedules",
        description="List saved schedules metadata. Use fields parameter to include statistics or data.",
        parameters={
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["statistics", "scheduleData", "daysWithDetails"],
                    },
                    "description": "Extra fields to include beyond default (year, month, sessionGroupId).",
                },
            },
        },
        execute=list_schedules,
    ),
}


def get_all_tools() -> list[ToolDefinition]:
    return list(TOOL_REGISTRY.values())


def get_tool(name: str) -> ToolDefinition:
    return TOOL_REGISTRY.get(name)
