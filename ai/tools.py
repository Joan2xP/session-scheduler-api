import json
import logging
from datetime import datetime

from exhibitors.services import (
    SchedulerService,
    ParticipantService,
    SessionGroupService,
    ExhibitorService,
)
from .provider import ToolDefinition

logger = logging.getLogger(__name__)


def _serialize_participant(p):
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


def _serialize_session_group(g):
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


def _serialize_exhibitor(e):
    return {
        "year": e.year,
        "month": e.month,
        "sessionGroupId": e.session_group_id,
        "scheduleData": e.schedule_data,
        "statistics": e.schedule_statistics,
        "daysWithDetails": e.days_with_details,
    }


def list_session_groups(params, user):
    groups = SessionGroupService.list(user)
    return [_serialize_session_group(g) for g in groups]


def get_session_group(params, user):
    group_id = params.get("sessionGroupId")
    group = SessionGroupService.get(group_id, user)
    return _serialize_session_group(group)


def list_participants(params, user):
    session_group_id = params.get("sessionGroupId")
    participants = ParticipantService.list(user, session_group_id)
    return [_serialize_participant(p) for p in participants]


def get_participant(params, user):
    participant_id = params.get("participantId")
    participant = ParticipantService.get(participant_id, user)
    return _serialize_participant(participant)


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
    return _serialize_participant(participant)


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
    return _serialize_participant(participant)


def delete_participant(params, user):
    participant_id = params.get("participantId")
    ParticipantService.delete(participant_id, user)
    return {"success": True, "message": f"Participant {participant_id} deleted"}


def generate_schedule(params, user):
    year = params.get("year")
    month = params.get("month")
    session_group_id = params.get("sessionGroupId")
    exclude_session_occurrences = params.get("excludeSessionOccurrences", [])

    result = SchedulerService.generate(year, month, session_group_id, user, exclude_session_occurrences)
    return {
        "scheduleData": result["schedule_data"],
        "statistics": result["statistics"],
        "daysWithDetails": result["days_with_details"],
    }


def save_schedule(params, user):
    year = params.get("year")
    month = params.get("month")
    session_group_id = params.get("sessionGroupId")
    schedule_data = params.get("scheduleData")
    statistics = params.get("statistics")
    days_with_details = params.get("daysWithDetails")

    exhibitor, created = SchedulerService.save_schedule(
        year, month, session_group_id, user, schedule_data, statistics, days_with_details
    )
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
    return _serialize_exhibitor(exhibitor)


def list_schedules(params, user):
    exhibitors = ExhibitorService.list(user)
    return [_serialize_exhibitor(e) for e in exhibitors]


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "list_session_groups": ToolDefinition(
        name="list_session_groups",
        description="List all session groups for the current user. Returns groups with their sessions and configuration.",
        parameters={
            "type": "object",
            "properties": {},
        },
        execute=list_session_groups,
    ),
    "get_session_group": ToolDefinition(
        name="get_session_group",
        description="Get details of a specific session group including its sessions and scheduler configuration.",
        parameters={
            "type": "object",
            "properties": {
                "sessionGroupId": {
                    "type": "integer",
                    "description": "The ID of the session group",
                },
            },
            "required": ["sessionGroupId"],
        },
        execute=get_session_group,
    ),
    "list_participants": ToolDefinition(
        name="list_participants",
        description="List all participants, optionally filtered by session group. Returns participant details including availability, constraints, and traits.",
        parameters={
            "type": "object",
            "properties": {
                "sessionGroupId": {
                    "type": "integer",
                    "description": "Optional. Filter participants by session group ID",
                },
            },
        },
        execute=list_participants,
    ),
    "get_participant": ToolDefinition(
        name="get_participant",
        description="Get details of a specific participant including all their constraints and settings.",
        parameters={
            "type": "object",
            "properties": {
                "participantId": {
                    "type": "integer",
                    "description": "The ID of the participant",
                },
            },
            "required": ["participantId"],
        },
        execute=get_participant,
    ),
    "create_participant": ToolDefinition(
        name="create_participant",
        description="Create a new participant in a session group. Requires name, session group, and scheduling constraints.",
        parameters={
            "type": "object",
            "properties": {
                "sessionGroupId": {
                    "type": "integer",
                    "description": "The session group to add the participant to",
                },
                "name": {
                    "type": "string",
                    "description": "The participant's name",
                },
                "maxPerWeek": {
                    "type": "integer",
                    "description": "Maximum sessions per week",
                },
                "maxPerMonth": {
                    "type": "integer",
                    "description": "Maximum sessions per month",
                },
                "minPerMonth": {
                    "type": "integer",
                    "description": "Minimum sessions per month",
                },
                "availability": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Array of session IDs the participant is available for",
                },
                "excludeIds": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Array of participant IDs to avoid scheduling together",
                },
                "isAnchor": {
                    "type": "boolean",
                    "description": "Whether this participant is an anchor (should be in most sessions)",
                },
            },
            "required": ["sessionGroupId", "name", "maxPerWeek", "maxPerMonth", "minPerMonth"],
        },
        execute=create_participant,
    ),
    "update_participant": ToolDefinition(
        name="update_participant",
        description="Update an existing participant's settings and constraints.",
        parameters={
            "type": "object",
            "properties": {
                "participantId": {
                    "type": "integer",
                    "description": "The ID of the participant to update",
                },
                "name": {"type": "string", "description": "New name"},
                "maxPerWeek": {"type": "integer", "description": "New max sessions per week"},
                "maxPerMonth": {"type": "integer", "description": "New max sessions per month"},
                "minPerMonth": {"type": "integer", "description": "New min sessions per month"},
                "availability": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "New availability (array of session IDs)",
                },
                "excludeIds": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "New exclude IDs",
                },
                "isAnchor": {"type": "boolean", "description": "New anchor status"},
            },
            "required": ["participantId"],
        },
        execute=update_participant,
    ),
    "delete_participant": ToolDefinition(
        name="delete_participant",
        description="Delete a participant from the system.",
        parameters={
            "type": "object",
            "properties": {
                "participantId": {
                    "type": "integer",
                    "description": "The ID of the participant to delete",
                },
            },
            "required": ["participantId"],
        },
        execute=delete_participant,
    ),
    "generate_schedule": ToolDefinition(
        name="generate_schedule",
        description="Generate a new schedule for a given year, month, and session group. This runs the scheduling algorithm and returns the optimized schedule.",
        parameters={
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "The year for the schedule (e.g., 2026)",
                },
                "month": {
                    "type": "integer",
                    "description": "The month for the schedule (1-12)",
                },
                "sessionGroupId": {
                    "type": "integer",
                    "description": "The session group to generate the schedule for",
                },
                "excludeSessionOccurrences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sessionId": {"type": "integer"},
                            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                        },
                    },
                    "description": "Optional. Session occurrences to exclude from scheduling",
                },
            },
            "required": ["year", "month", "sessionGroupId"],
        },
        execute=generate_schedule,
    ),
    "save_schedule": ToolDefinition(
        name="save_schedule",
        description="Save a generated schedule to the database. Use this after generate_schedule to persist the results.",
        parameters={
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Year"},
                "month": {"type": "integer", "description": "Month (1-12)"},
                "sessionGroupId": {"type": "integer", "description": "Session group ID"},
                "scheduleData": {"type": "array", "items": {"type": "object"}, "description": "The schedule data from generate_schedule"},
                "statistics": {"type": "array", "items": {"type": "object"}, "description": "The statistics from generate_schedule"},
                "daysWithDetails": {"type": "array", "items": {"type": "object"}, "description": "The days with details from generate_schedule"},
            },
            "required": ["year", "month", "sessionGroupId", "scheduleData", "statistics", "daysWithDetails"],
        },
        execute=save_schedule,
    ),
    "get_schedule": ToolDefinition(
        name="get_schedule",
        description="Retrieve a previously saved schedule for a specific year, month, and session group.",
        parameters={
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Year"},
                "month": {"type": "integer", "description": "Month (1-12)"},
                "sessionGroupId": {"type": "integer", "description": "Session group ID"},
            },
            "required": ["year", "month", "sessionGroupId"],
        },
        execute=get_schedule,
    ),
    "list_schedules": ToolDefinition(
        name="list_schedules",
        description="List all saved schedules for the current user.",
        parameters={
            "type": "object",
            "properties": {},
        },
        execute=list_schedules,
    ),
}


def get_all_tools() -> list[ToolDefinition]:
    return list(TOOL_REGISTRY.values())


def get_tool(name: str) -> ToolDefinition:
    return TOOL_REGISTRY.get(name)
