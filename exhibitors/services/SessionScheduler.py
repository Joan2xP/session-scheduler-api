import argparse
import calendar
import logging
import os
import random
import time
from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from django.db.models import Case, When, Value, IntegerField
from exhibitors.models import (
    Participant,
    Session,
    SessionGroup,
    ParticipantTrait,
    DEFAULT_SCHEDULER_CONFIG,
)

logger = logging.getLogger(__name__)


class SessionScheduler:
    def __init__(
        self,
        start_date,
        session_group_id,
        exclude_session_occurrences=None,
        scheduler_config=None,
        weekday_group_size=None,
        weekend_group_size=None,
    ):
        self.start_date = start_date
        self.session_group_id = session_group_id
        self.exclude_session_occurrences = exclude_session_occurrences or []

        # Merge scheduler config with defaults
        self.scheduler_config = DEFAULT_SCHEDULER_CONFIG.copy()
        if scheduler_config:
            if "constraints" in scheduler_config:
                self.scheduler_config["constraints"].update(
                    scheduler_config["constraints"]
                )
            if "objectives" in scheduler_config:
                for key, val in scheduler_config["objectives"].items():
                    if key in self.scheduler_config["objectives"]:
                        self.scheduler_config["objectives"][key].update(val)
                    else:
                        self.scheduler_config["objectives"][key] = val
            if "weekday_group_size" in scheduler_config:
                self.scheduler_config["weekday_group_size"] = scheduler_config[
                    "weekday_group_size"
                ]
            if "weekend_group_size" in scheduler_config:
                self.scheduler_config["weekend_group_size"] = scheduler_config[
                    "weekend_group_size"
                ]
            if "solver" in scheduler_config:
                self.scheduler_config.setdefault("solver", {}).update(
                    scheduler_config["solver"]
                )

        # Group sizes: explicit params override config
        self.weekday_group_size = (
            weekday_group_size or self.scheduler_config["weekday_group_size"]
        )
        self.weekend_group_size = (
            weekend_group_size or self.scheduler_config["weekend_group_size"]
        )

        self.data = []
        self.people = []  # List of participant IDs
        self.participant_names = {}  # Mapping of participant ID to name
        self.rows = []
        self.n_people = 0

        # Session metadata cache
        self.sessions_cache = {}  # session_id -> Session object
        self.session_metadata = {}  # session_id -> {location, start_hour, etc.}

        self.availability = {}  # participant_id -> list of session IDs
        self.partners = {}  # participant_id -> partner participant ID
        self.exclude_ids = {}  # participant_id -> list of participant IDs to exclude
        self.max_weekly = {}
        self.max_monthly = {}
        self.min_monthly = {}
        self.model = cp_model.CpModel()
        self.attendance = {}  # participant_id -> {(session_id, date): BoolVar}
        self.only_session_occurrences = (
            {}
        )  # participant_id -> list of {sessionId, date}
        self.exclude_session_occurrences_per_participant = (
            {}
        )  # participant_id -> list of {sessionId, date}
        self.min_sessions_together = (
            {}
        )  # participant_id -> {sessionId, partnerId, amount}
        self.enforced_sessions = {}  # participant_id -> list of session IDs
        self.traits = {}  # participant_id -> list of ParticipantTrait objects
        self.anchor_participants = set()  # set of participant IDs with is_anchor=True

        # Available sessions as (session_id, date) tuples
        self.available_sessions = []
        self.all_available_sessions = []

        # Date info cache: date_str -> (date_obj, iso_week, day_offset, weekday)
        self.date_info = {}

        self.initialize()

    def get_data(self):
        # Fetch participants filtered by session_group_id
        participants = Participant.objects.filter(
            session_group_id=self.session_group_id
        ).prefetch_related("traits")

        # Use participant IDs instead of names
        self.people = [p.id for p in participants]
        random.shuffle(self.people)

        # Build participant ID to name mapping
        for p in participants:
            self.participant_names[p.id] = p.name

        self.rows = []
        for p in participants:
            row = {
                "id": p.id,
                "name": p.name,
                "availability": p.availability or [],  # Array of session IDs
                "min_per_month": p.min_per_month,
                "max_per_week": p.max_per_week,
                "max_per_month": p.max_per_month,
                "only_session_occurrences": p.only_session_occurrences
                or [],  # Array of {sessionId, date}
                "exclude_session_occurrences": p.exclude_session_occurrences
                or [],  # Array of {sessionId, date}
                "partner_id": p.partner_id,  # Participant ID or None
                "exclude_ids": p.exclude_ids or [],  # Array of participant IDs
                "min_sessions_together": p.min_sessions_together,  # {sessionId, partnerId, amount} or None
                "enforced_sessions": p.enforced_week_days
                or [],  # Array of session IDs (from enforced_week_days field)
                "is_anchor": p.is_anchor,
                "traits": list(p.traits.all()),  # List of ParticipantTrait objects
            }
            self.rows.append(row)

        random.shuffle(self.rows)  # Shuffle the rows to randomize the order
        self.n_people = len(self.people)

        # Fetch and cache sessions for this session group, sorted by frequency and time
        sessions = Session.objects.filter(
            session_group_id=self.session_group_id
        ).order_by(
            Case(
                When(frequency="daily", then=Value(0)),
                When(frequency="weekly", then=Value(1)),
                When(frequency="monthly", then=Value(2)),
                When(frequency="yearly", then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            ),
            "day_of_week",
            "week",
            "month",
            "start_hour",
            "start_minute",
        )
        for session in sessions:
            self.sessions_cache[session.id] = session
            self.session_metadata[session.id] = {
                "location": session.location or "",
                "start_hour": session.start_hour,
                "start_minute": session.start_minute,
                "end_hour": session.end_hour,
                "end_minute": session.end_minute,
                "frequency": session.frequency,
                "day_of_week": session.day_of_week,
                "week": session.week,
                "month": session.month,
            }

    def preprocess_available_sessions(self):
        """Generate available sessions as list of (session_id, date) tuples from Session model."""
        start_date = datetime.strptime(self.start_date, "%Y-%m-%d")
        _, days_in_month = calendar.monthrange(start_date.year, start_date.month)

        # Build a set of excluded (session_id, date) for quick lookup
        excluded_occurrences = set()
        for occ in self.exclude_session_occurrences:
            session_id = occ.get("sessionId")
            date_str = occ.get("date")
            if session_id is not None and date_str:
                excluded_occurrences.add((session_id, date_str))

        # Precompute date info for every day in the month
        first_day_weekday = start_date.weekday()
        for day_offset in range(days_in_month):
            current_date = start_date + timedelta(days=day_offset)
            date_str = current_date.strftime("%Y-%m-%d")
            week_of_month = ((current_date.day + first_day_weekday - 1) // 7) + 1
            self.date_info[date_str] = (
                current_date,
                current_date.isocalendar()[1],
                day_offset,
                current_date.weekday(),
                week_of_month,
            )

        # For each session in the session group, generate occurrences
        for session_id, metadata in self.session_metadata.items():
            frequency = metadata["frequency"]
            session_day_of_week = metadata["day_of_week"]
            session_week = metadata["week"]
            session_month = metadata["month"]

            for day_offset in range(days_in_month):
                current_date = start_date + timedelta(days=day_offset)
                date_str = current_date.strftime("%Y-%m-%d")
                _, _, _, current_day_of_week, week_of_month = self.date_info[date_str]

                # Check if this date matches the session's frequency pattern
                should_include = False

                if frequency == "daily":
                    should_include = True

                elif frequency == "weekly":
                    if (
                        session_day_of_week is not None
                        and current_day_of_week == session_day_of_week
                    ):
                        should_include = True

                elif frequency == "monthly":
                    if (
                        session_day_of_week is not None
                        and current_day_of_week == session_day_of_week
                    ):
                        if session_week is None or week_of_month == session_week:
                            should_include = True

                elif frequency == "yearly":
                    if (
                        session_month is not None
                        and current_date.month == session_month
                    ):
                        if (
                            session_day_of_week is not None
                            and current_day_of_week == session_day_of_week
                        ):
                            if session_week is None or week_of_month == session_week:
                                should_include = True

                if should_include:
                    occurrence = (session_id, date_str)
                    self.all_available_sessions.append(occurrence)
                    if occurrence not in excluded_occurrences:
                        self.available_sessions.append(occurrence)

        # Sort by date then session_id for consistent ordering
        self.available_sessions.sort(key=lambda x: (x[1], x[0]))
        self.all_available_sessions.sort(key=lambda x: (x[1], x[0]))

    def initialize(self):
        t0 = time.perf_counter()
        self.get_data()
        logger.info(
            "data loaded: %d participants, %d sessions",
            len(self.people),
            len(self.sessions_cache),
        )

        t1 = time.perf_counter()
        self.preprocess_available_sessions()
        logger.info(
            "preprocessed: %d available occurrences (%d total, %d excluded)",
            len(self.available_sessions),
            len(self.all_available_sessions),
            len(self.all_available_sessions) - len(self.available_sessions),
        )

        # Process participant data using IDs as keys
        for row in self.rows:
            participant_id = row["id"]

            # Availability is already a list of session IDs
            self.availability[participant_id] = row["availability"]
            self.min_monthly[participant_id] = int(row["min_per_month"])
            self.max_weekly[participant_id] = int(row["max_per_week"])
            self.max_monthly[participant_id] = int(row["max_per_month"])

            # Store only_session_occurrences (list of {sessionId, date})
            only_occurrences = row.get("only_session_occurrences", [])
            if (
                only_occurrences
                and isinstance(only_occurrences, list)
                and len(only_occurrences) > 0
            ):
                self.only_session_occurrences[participant_id] = only_occurrences

            # Store exclude_session_occurrences (list of {sessionId, date})
            exclude_occurrences = row.get("exclude_session_occurrences", [])
            if (
                exclude_occurrences
                and isinstance(exclude_occurrences, list)
                and len(exclude_occurrences) > 0
            ):
                self.exclude_session_occurrences_per_participant[participant_id] = (
                    exclude_occurrences
                )

            # Store partner_id (participant ID)
            partner_id = row.get("partner_id")
            if partner_id is not None:
                self.partners[participant_id] = partner_id

            # Store exclude_ids (list of participant IDs)
            exclude_ids = row.get("exclude_ids", [])
            if exclude_ids and isinstance(exclude_ids, list) and len(exclude_ids) > 0:
                self.exclude_ids[participant_id] = exclude_ids

            # Store min_sessions_together ({sessionId, partnerId, amount})
            min_together = row.get("min_sessions_together")
            if min_together and isinstance(min_together, dict):
                self.min_sessions_together[participant_id] = min_together

            # Store enforced_sessions (list of session IDs)
            enforced = row.get("enforced_sessions", [])
            if enforced and isinstance(enforced, list) and len(enforced) > 0:
                self.enforced_sessions[participant_id] = enforced

            # Store traits (list of ParticipantTrait objects)
            traits = row.get("traits", [])
            if traits:
                self.traits[participant_id] = traits

            # Store anchor participants
            if row.get("is_anchor", False):
                self.anchor_participants.add(participant_id)

        # Initialize attendance variables with (session_id, date) keys
        for participant_id in self.people:
            self.attendance[participant_id] = {}
            for session_id, date in self.available_sessions:
                self.attendance[participant_id][(session_id, date)] = (
                    self.model.NewBoolVar(f"p{participant_id}_s{session_id}_{date}")
                )

        # Resolve trait-based exclusions
        self.resolve_trait_exclusions()

        t2 = time.perf_counter()
        n_vars = len(self.people) * len(self.available_sessions)
        logger.info(
            "model initialized: %d attendance variables (%.1fs total)",
            n_vars,
            t2 - t0,
        )

    def resolve_trait_exclusions(self):
        """Convert trait position-based exclusions to (sessionId, date) exclusions."""
        for participant_id, traits in self.traits.items():
            for trait in traits:
                session_id = trait.session_id
                positions = trait.positions

                # Get all occurrences of this session, sorted by date
                session_occurrences = sorted(
                    [
                        (sid, d)
                        for sid, d in self.all_available_sessions
                        if sid == session_id
                    ],
                    key=lambda x: x[1],
                )

                if not session_occurrences:
                    continue

                total = len(session_occurrences)
                resolved = []
                for pos in positions:
                    if pos > 0:
                        # Positive: from start (1-based)
                        idx = pos - 1
                        if 0 <= idx < total:
                            resolved.append(session_occurrences[idx])
                    elif pos < 0:
                        # Negative: from end (-1 = last)
                        idx = total + pos
                        if 0 <= idx < total:
                            resolved.append(session_occurrences[idx])

                if resolved:
                    if (
                        participant_id
                        not in self.exclude_session_occurrences_per_participant
                    ):
                        self.exclude_session_occurrences_per_participant[
                            participant_id
                        ] = []
                    existing = self.exclude_session_occurrences_per_participant[
                        participant_id
                    ]
                    existing_set = {
                        (e.get("sessionId"), e.get("date"))
                        for e in existing
                        if isinstance(e, dict)
                    }
                    for sid, date_str in resolved:
                        if (sid, date_str) not in existing_set:
                            existing.append({"sessionId": sid, "date": date_str})

    def validate(self):
        """Pre-flight checks for common infeasibility causes. Returns list of warnings."""
        warnings = []
        availability_enabled = self.scheduler_config["constraints"]["availability"]

        # Check: participants with min_per_month > 0 but no available sessions
        if availability_enabled:
            for pid in self.people:
                avail = self.availability.get(pid, [])
                min_month = self.min_monthly.get(pid, 0)
                if min_month > 0 and not avail:
                    name = self.participant_names.get(pid, str(pid))
                    warnings.append(
                        f"Participant '{name}' has min_per_month={min_month} but no available sessions"
                    )

        # Check: partners with zero overlapping sessions
        if self.scheduler_config["constraints"]["partner"]:
            for pid, partner_id in self.partners.items():
                if partner_id not in self.people:
                    continue
                if availability_enabled:
                    p_sessions = set(self.availability.get(pid, []))
                    partner_sessions = set(self.availability.get(partner_id, []))
                    overlap = p_sessions & partner_sessions
                    if not overlap:
                        p_name = self.participant_names.get(pid, str(pid))
                        partner_name = self.participant_names.get(
                            partner_id, str(partner_id)
                        )
                        warnings.append(
                            f"Partners '{p_name}' and '{partner_name}' have no overlapping sessions — "
                            f"they can never attend together"
                        )

        # Check: group size vs available participants per session
        if self.scheduler_config["constraints"]["group_size"]:
            for session_id, date in self.available_sessions:
                date_obj, _, _, weekday, _ = self.date_info[date]
                required = (
                    self.weekend_group_size
                    if weekday >= 5
                    else self.weekday_group_size
                )
                if availability_enabled:
                    available_count = sum(
                        1
                        for pid in self.people
                        if session_id in self.availability.get(pid, [])
                    )
                    if available_count < required:
                        metadata = self.session_metadata.get(session_id, {})
                        warnings.append(
                            f"Session {session_id} on {date} needs {required} participants "
                            f"but only {available_count} are available"
                        )

        return warnings

    def add_only_session_occurrences_constraints(self):
        """Ensure each participant is only scheduled on their specified session occurrences."""
        all_sessions_set = set(self.all_available_sessions)

        for participant_id, only_occurrences in self.only_session_occurrences.items():
            if only_occurrences:
                # Validate format: must be list of {sessionId, date} objects
                if not isinstance(only_occurrences, list):
                    import logging

                    logging.warning(
                        f"Participant {participant_id}: only_session_occurrences is not a list, "
                        f"got {type(only_occurrences)}. Treating as null."
                    )
                    continue

                # Build a set of allowed (sessionId, date) for quick lookup
                allowed_occurrences = set()
                invalid_format = False

                for occ in only_occurrences:
                    if not isinstance(occ, dict):
                        invalid_format = True
                        break
                    logger.debug("%d: only_session_occurrences: %s", participant_id, occ)
                    session_id = occ.get("sessionId")
                    date_str = occ.get("date")
                    if session_id is not None and date_str:
                        allowed_occurrences.add((session_id, date_str))

                if invalid_format:
                    import logging

                    logging.warning(
                        f"Participant {participant_id}: only_session_occurrences contains invalid format "
                        f"(expected list of {{sessionId, date}} objects). Treating as null."
                    )
                    continue

                # Validate that each allowed occurrence actually exists in the month
                valid_allowed = set()
                for occ in allowed_occurrences:
                    if occ in all_sessions_set:
                        valid_allowed.add(occ)
                    else:
                        import logging

                        logging.warning(
                            f"Participant {participant_id}: only_session_occurrences contains "
                            f"invalid occurrence {occ} (not a valid session in this month). Skipping."
                        )

                if not valid_allowed:
                    continue

                # For each available session, if not in allowed list, prevent attendance
                for session_id, date in self.available_sessions:
                    if (session_id, date) not in valid_allowed:
                        self.model.Add(
                            self.attendance[participant_id][(session_id, date)] == 0
                        )

    def add_exclude_session_occurrences_constraints(self):
        """Ensure each participant is not scheduled on their excluded session occurrences."""
        all_sessions_set = set(self.all_available_sessions)

        for (
            participant_id,
            exclude_occurrences,
        ) in self.exclude_session_occurrences_per_participant.items():
            if exclude_occurrences:
                # Validate format: must be list of {sessionId, date} objects
                if not isinstance(exclude_occurrences, list):
                    import logging

                    logging.warning(
                        f"Participant {participant_id}: exclude_session_occurrences is not a list, "
                        f"got {type(exclude_occurrences)}. Treating as null."
                    )
                    continue

                # Build a set of excluded (sessionId, date) for quick lookup
                excluded_set = set()
                invalid_format = False

                for occ in exclude_occurrences:
                    if not isinstance(occ, dict):
                        invalid_format = True
                        break
                    session_id = occ.get("sessionId")
                    date_str = occ.get("date")
                    if session_id is not None and date_str:
                        excluded_set.add((session_id, date_str))

                if invalid_format:
                    import logging

                    logging.warning(
                        f"Participant {participant_id}: exclude_session_occurrences contains invalid format "
                        f"(expected list of {{sessionId, date}} objects). Treating as null."
                    )
                    continue

                # Validate that each excluded occurrence actually exists in the month
                valid_excluded = set()
                for occ in excluded_set:
                    if occ in all_sessions_set:
                        valid_excluded.add(occ)
                    else:
                        import logging

                        logging.warning(
                            f"Participant {participant_id}: exclude_session_occurrences contains "
                            f"invalid occurrence {occ} (not a valid session in this month). Skipping."
                        )

                if not valid_excluded:
                    continue

                # For each available session, if in excluded list, prevent attendance
                for session_id, date in self.available_sessions:
                    if (session_id, date) in valid_excluded:
                        self.model.Add(
                            self.attendance[participant_id][(session_id, date)] == 0
                        )

    def add_minimum_monthly_constraints(self):
        """Ensure each participant attends at least the minimum number of sessions per month."""
        for participant_id in self.people:
            min_per_month = self.min_monthly[participant_id]
            # Adjust minimum based on available sessions
            if len(self.available_sessions) <= 20:
                min_per_month -= 3
                if min_per_month < 0:
                    min_per_month = 0
            month_vars = [
                self.attendance[participant_id][(session_id, date)]
                for session_id, date in self.available_sessions
            ]
            # Add the constraint for the minimum number of sessions
            self.model.Add(sum(month_vars) >= min_per_month)

    def availability_constraints(self):
        """Ensure participants only attend sessions they are available for."""
        for participant_id in self.people:
            available_session_ids = self.availability.get(participant_id, [])
            for session_id, date in self.available_sessions:
                # If the session_id is not in the participant's availability list, prevent attendance
                if session_id not in available_session_ids:
                    self.model.Add(
                        self.attendance[participant_id][(session_id, date)] == 0
                    )

    def add_weekly_constraints(self):
        """Add weekly attendance constraints for each participant."""
        for participant_id in self.people:
            max_per_week = self.max_weekly[participant_id]
            week_vars = []
            current_week = None

            for session_id, date in self.available_sessions:
                _, week_number, _, _, _ = self.date_info[date]

                # If the week changes, add the constraint for the previous week
                if current_week is not None and week_number != current_week:
                    self.model.Add(sum(week_vars) <= max_per_week)
                    week_vars = []  # Reset for the new week

                # Update the current week and append the attendance variable
                current_week = week_number
                week_vars.append(self.attendance[participant_id][(session_id, date)])

            # Add the constraint for the last week
            if week_vars:
                self.model.Add(sum(week_vars) <= max_per_week)

    def add_monthly_constraints(self):
        """Add monthly attendance constraints for each participant."""
        for participant_id in self.people:
            max_per_month = self.max_monthly[participant_id]
            month_vars = [
                self.attendance[participant_id][(session_id, date)]
                for session_id, date in self.available_sessions
            ]
            self.model.Add(sum(month_vars) <= max_per_month)

    def add_group_size_constraints(self):
        """Ensure group size constraints are respected."""
        for session_id, date in self.available_sessions:
            _, _, _, weekday, _ = self.date_info[date]
            group_size = (
                self.weekend_group_size if weekday >= 5 else self.weekday_group_size
            )
            group_members = [
                self.attendance[participant_id][(session_id, date)]
                for participant_id in self.people
            ]
            self.model.Add(sum(group_members) == group_size)

    def add_partner_constraints(self):
        """Ensure partners are in the same group when both attend."""
        for participant_id, partner_id in self.partners.items():
            # Check if partner is in the list of participants
            if partner_id not in self.people:
                continue
            for session_id, date in self.available_sessions:
                # Ensure the partner is also attending if the participant is attending
                self.model.Add(
                    self.attendance[participant_id][(session_id, date)]
                    <= self.attendance[partner_id][(session_id, date)]
                )

    def add_exclusion_constraints(self):
        """Ensure participants listed in exclude_ids are not scheduled together."""
        for participant_id, excluded_ids in self.exclude_ids.items():
            if not excluded_ids:
                continue
            for excluded_id in excluded_ids:
                if excluded_id in self.people:
                    for session_id, date in self.available_sessions:
                        # Ensure the participant and excluded participant are not both attending
                        self.model.Add(
                            self.attendance[participant_id][(session_id, date)]
                            + self.attendance[excluded_id][(session_id, date)]
                            <= 1
                        )

    def add_anchor_objective(self):
        """
        Encourage at least one anchor participant per session occurrence.
        Returns the count of sessions without an anchor (to minimize).
        Having more than one anchor in a session provides no extra benefit.
        """
        if not self.anchor_participants:
            return None

        not_covered_vars = []

        for session_id, date in self.available_sessions:
            # covered_s = 1 if at least one anchor attends this session
            covered_s = self.model.NewBoolVar(
                f"anchor_covered_s{session_id}_{date}"
            )

            # Sum of anchor attendances for this session occurrence
            anchor_attendance = [
                self.attendance[pid][(session_id, date)]
                for pid in self.anchor_participants
                if pid in self.attendance
            ]

            if not anchor_attendance:
                continue

            # covered_s = 1 iff sum >= 1 (at least one anchor attends)
            self.model.Add(sum(anchor_attendance) >= 1).OnlyEnforceIf(covered_s)
            self.model.Add(sum(anchor_attendance) == 0).OnlyEnforceIf(covered_s.Not())

            # not_covered = 1 - covered_s (we want to minimize this)
            not_covered = self.model.NewBoolVar(
                f"anchor_not_covered_s{session_id}_{date}"
            )
            self.model.Add(not_covered == 1 - covered_s)
            not_covered_vars.append(not_covered)

        if not not_covered_vars:
            return None

        return sum(not_covered_vars)

    def add_diversity_objective(self):
        """
        Minimize the maximum number of times any participant pair is scheduled together.
        Returns the max_appearances variable for combined objective.
        """
        # Precompute feasible occurrences per participant (availability pruning)
        availability_enabled = self.scheduler_config["constraints"]["availability"]
        feasible = {}
        for pid in self.people:
            if availability_enabled and pid in self.availability:
                avail_set = set(self.availability[pid])
                feasible[pid] = [
                    (sid, d)
                    for sid, d in self.available_sessions
                    if sid in avail_set
                ]
            else:
                feasible[pid] = self.available_sessions

        # Track pair occurrences — only where both participants can attend
        pair_counts = {}
        for i, p1 in enumerate(self.people):
            for j, p2 in enumerate(self.people):
                if i >= j:
                    continue
                # Intersect feasible occurrences
                f1 = set(feasible[p1])
                shared = [(sid, d) for sid, d in feasible[p2] if (sid, d) in f1]
                if not shared:
                    continue

                pair_key = f"p{p1}_p{p2}"
                pair_vars = []

                for session_id, date in shared:
                    pair_var = self.model.NewBoolVar(
                        f"pair_{pair_key}_s{session_id}_{date}"
                    )
                    # pair_var >= a + b - 1  (forces pair_var=1 when both attend;
                    # solver minimizes so pair_var=0 otherwise)
                    self.model.Add(
                        pair_var
                        >= self.attendance[p1][(session_id, date)]
                        + self.attendance[p2][(session_id, date)]
                        - 1
                    )
                    pair_vars.append(pair_var)

                pair_counts[pair_key] = pair_vars

        if not pair_counts:
            return None

        # Minimize the maximum pair count
        max_appearances = self.model.NewIntVar(
            0, len(self.available_sessions), "max_pair_appearances"
        )

        for pair_key, vars_list in pair_counts.items():
            pair_total = self.model.NewIntVar(0, len(vars_list), f"total_{pair_key}")
            self.model.Add(pair_total == sum(vars_list))
            self.model.Add(max_appearances >= pair_total)

        return max_appearances

    def add_consecutive_days_penalty_objective(self):
        """
        Add an objective to penalize participants attending sessions on consecutive days.
        Returns the total consecutive days count for combined objective.
        """
        consecutive_day_vars = []

        # Group sessions by date
        sessions_by_date = {}
        for session_id, date in self.available_sessions:
            if date not in sessions_by_date:
                sessions_by_date[date] = []
            sessions_by_date[date].append(session_id)

        # Get sorted unique dates
        sorted_dates = sorted(sessions_by_date.keys())

        for participant_id in self.people:
            # Create attendance indicators per day (1 if attending any session that day)
            day_attendance = {}
            for date in sorted_dates:
                day_var = self.model.NewBoolVar(f"day_attend_p{participant_id}_{date}")
                session_vars = [
                    self.attendance[participant_id][(session_id, date)]
                    for session_id in sessions_by_date[date]
                ]
                # day_var = 1 if attending any session on this day
                self.model.AddMaxEquality(day_var, session_vars)
                day_attendance[date] = day_var

            # Check consecutive day pairs
            for i in range(len(sorted_dates) - 1):
                date1 = sorted_dates[i]
                date2 = sorted_dates[i + 1]

                # Check if dates are consecutive using cached day offsets
                _, _, offset1, _, _ = self.date_info[date1]
                _, _, offset2, _, _ = self.date_info[date2]
                if offset2 - offset1 == 1:
                    # Create indicator: 1 if attending both consecutive days
                    consecutive_var = self.model.NewBoolVar(
                        f"consecutive_p{participant_id}_{date1}_{date2}"
                    )
                    self.model.AddBoolAnd(
                        [day_attendance[date1], day_attendance[date2]]
                    ).OnlyEnforceIf(consecutive_var)
                    self.model.AddBoolOr(
                        [day_attendance[date1].Not(), day_attendance[date2].Not()]
                    ).OnlyEnforceIf(consecutive_var.Not())
                    consecutive_day_vars.append(consecutive_var)

        return sum(consecutive_day_vars) if consecutive_day_vars else None

    def set_combined_objective(
        self, diversity_var, consecutive_var, anchor_var=None
    ):
        """
        Set a single combined objective with weights for all objectives.
        Weights are read from scheduler_config.
        """
        objectives_config = self.scheduler_config["objectives"]

        objective_terms = []

        if diversity_var is not None and objectives_config["diversity"]["enabled"]:
            weight = objectives_config["diversity"]["weight"]
            objective_terms.append(weight * diversity_var)

        if (
            consecutive_var is not None
            and objectives_config["consecutive_days_penalty"]["enabled"]
        ):
            weight = objectives_config["consecutive_days_penalty"]["weight"]
            objective_terms.append(weight * consecutive_var)

        if anchor_var is not None and objectives_config["anchor"]["enabled"]:
            weight = objectives_config["anchor"]["weight"]
            objective_terms.append(weight * anchor_var)

        if objective_terms:
            self.model.Minimize(sum(objective_terms))

    def add_min_sessions_together_constraints(self):
        """Ensure participants are scheduled together for at least the specified number of sessions."""
        for participant_id, min_together in self.min_sessions_together.items():
            if not min_together:
                continue

            target_session_id = min_together.get("sessionId")
            partner_id = min_together.get("partnerId")
            min_sessions = min_together.get("amount", 0)

            if target_session_id is None or partner_id is None or min_sessions < 1:
                continue

            # Check if partner is in the list of participants
            if partner_id not in self.people:
                continue

            participant_name = self.participant_names.get(
                participant_id, str(participant_id)
            )
            partner_name = self.participant_names.get(partner_id, str(partner_id))
            logger.debug(
                "min_sessions_together: %s + %s on session %d: %d",
                participant_name,
                partner_name,
                target_session_id,
                min_sessions,
            )

            # Collect attendance variables for both participants on the specified session
            together_vars = []
            for session_id, date in self.available_sessions:
                if session_id == target_session_id:
                    # Both participant and partner must attend the same session occurrence
                    together_var = self.model.NewBoolVar(
                        f"p{participant_id}_p{partner_id}_together_s{session_id}_{date}"
                    )
                    self.model.AddBoolAnd(
                        [
                            self.attendance[participant_id][(session_id, date)],
                            self.attendance[partner_id][(session_id, date)],
                        ]
                    ).OnlyEnforceIf(together_var)
                    together_vars.append(together_var)

            # Add the constraint for the minimum number of sessions together
            if together_vars:
                self.model.Add(sum(together_vars) >= int(min_sessions))

    def add_enforced_sessions_constraints(self):
        """Ensure participants are scheduled on their enforced sessions."""
        for participant_id, enforced_session_ids in self.enforced_sessions.items():
            if enforced_session_ids:
                for session_id, date in self.available_sessions:
                    # Check if this session_id is in the enforced sessions list
                    if session_id in enforced_session_ids:
                        # Force the participant to attend this session occurrence
                        self.model.Add(
                            self.attendance[participant_id][(session_id, date)] == 1
                        )

    def add_one_session_per_day_constraints(self):
        """Ensure participants attend at most one session per day."""
        # Group sessions by date
        sessions_by_date = {}
        for session_id, date in self.available_sessions:
            if date not in sessions_by_date:
                sessions_by_date[date] = []
            sessions_by_date[date].append(session_id)

        # For each participant and each date, add constraint that sum <= 1
        for participant_id in self.people:
            for date, session_ids in sessions_by_date.items():
                if len(session_ids) > 1:
                    day_vars = [
                        self.attendance[participant_id][(session_id, date)]
                        for session_id in session_ids
                    ]
                    self.model.Add(sum(day_vars) <= 1)

    def initialize_solver(self):
        """Initialize the solver and set parameters from config/env."""
        solver = cp_model.CpSolver()
        solver_config = self.scheduler_config.get("solver", {})

        max_time = solver_config.get(
            "max_time_in_seconds",
            int(os.environ.get("SCHEDULER_MAX_TIME_SECONDS", "30")),
        )
        num_workers = solver_config.get(
            "num_search_workers",
            int(os.environ.get("SCHEDULER_NUM_WORKERS", "2")),
        )
        log_progress = solver_config.get(
            "log_search_progress",
            os.environ.get("SCHEDULER_LOG_PROGRESS", "").lower() == "true",
        )

        solver.parameters.max_time_in_seconds = max_time
        solver.parameters.num_search_workers = num_workers
        solver.parameters.log_search_progress = log_progress

        logger.info(
            "solving (workers=%d, max_time=%ds, log_progress=%s)",
            num_workers,
            max_time,
            log_progress,
        )
        return solver

    def format_schedule(self, solver):
        """Format the schedule into a structured list."""
        schedule_data = []

        # Day names in Spanish
        day_names_es = [
            "Lunes",
            "Martes",
            "Miércoles",
            "Jueves",
            "Viernes",
            "Sábado",
            "Domingo",
        ]

        available_set = set(self.available_sessions)

        for session_id, date in sorted(
            self.all_available_sessions, key=lambda x: (x[1], x[0])
        ):
            date_obj, _, _, weekday, _ = self.date_info[date]
            day_name = day_names_es[weekday]

            # Get session metadata
            metadata = self.session_metadata.get(session_id, {})
            location = metadata.get("location", "")
            start_hour = metadata.get("start_hour", 0)
            start_minute = metadata.get("start_minute", 0)
            end_hour = metadata.get("end_hour", 0)
            end_minute = metadata.get("end_minute", 0)

            # Format time
            time_range = (
                f"{start_hour:02d}:{start_minute:02d} a {end_hour:02d}:{end_minute:02d}"
            )
            time_period = "MAÑANA" if start_hour < 12 else "TARDE"

            # Check if this occurrence is in available_sessions (not excluded)
            if (session_id, date) not in available_set:
                # Add to schedule data with no members
                schedule_data.append(
                    {
                        "Date": f"{day_name} {date_obj.day}",
                        "Time": time_period,
                        "Time_Range": time_range,
                        "Location": location,
                        "Members": [],
                        "sessionId": session_id,
                    }
                )
            else:
                # Get group members (convert IDs to names)
                members = []
                for participant_id in self.people:
                    if (
                        solver.Value(
                            self.attendance[participant_id][(session_id, date)]
                        )
                        == 1
                    ):
                        name = self.participant_names.get(
                            participant_id, str(participant_id)
                        )
                        members.append({"name": name, "participantId": participant_id})

                # Add to schedule data
                schedule_data.append(
                    {
                        "Date": f"{day_name} {date_obj.day}",
                        "Time": time_period,
                        "Time_Range": time_range,
                        "Location": location,
                        "Members": members,
                        "sessionId": session_id,
                    }
                )

        return schedule_data

    def get_days_with_details(self):
        """Get unique session details for display."""
        days_with_details = []
        seen_sessions = set()

        day_names_es = [
            "Lunes",
            "Martes",
            "Miércoles",
            "Jueves",
            "Viernes",
            "Sábado",
            "Domingo",
        ]

        for session_id, metadata in self.session_metadata.items():
            # Skip if we've already added this session
            if session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)

            # Get day of week from the first occurrence of this session
            day_of_week = metadata.get("day_of_week")
            if day_of_week is None:
                continue

            day_name = day_names_es[day_of_week]
            location = metadata.get("location", "")
            start_hour = metadata.get("start_hour", 0)
            start_minute = metadata.get("start_minute", 0)
            end_hour = metadata.get("end_hour", 0)
            end_minute = metadata.get("end_minute", 0)
            time_range = (
                f"{start_hour:02d}:{start_minute:02d} a {end_hour:02d}:{end_minute:02d}"
            )

            days_with_details.append(
                {
                    "day": day_name,
                    "location": location,
                    "time": time_range,
                    "sessionId": session_id,
                }
            )

        return days_with_details

    def calculate_statistics(self, solver):
        """Calculate attendance statistics."""
        attendance_data = {}

        for participant_id in self.people:
            participant_sessions = []
            for session_id, date in self.available_sessions:
                if (
                    solver.Value(self.attendance[participant_id][(session_id, date)])
                    == 1
                ):
                    date_obj, _, _, _, _ = self.date_info[date]
                    participant_sessions.append(str(date_obj.day))
            attendance_data[participant_id] = participant_sessions

        attendance_summary = []
        for participant_id, sessions in attendance_data.items():
            session_count = len(sessions)
            name = self.participant_names.get(participant_id, str(participant_id))
            sessions.sort(key=lambda x: int(x))
            attendance_summary.append(
                {
                    "person": name,
                    "sessionCount": session_count,
                    "days": ", ".join(sessions),
                }
            )

        # Sort by session count in descending order
        attendance_summary = sorted(
            attendance_summary, key=lambda x: x["sessionCount"], reverse=True
        )

        return attendance_summary

    def format_schedule_data(self, schedule_data):
        """Format the schedule data into the structure required for rendering."""
        formatted_data = []
        current_week_number = None
        week_data = {"week_number": None, "days": []}

        year_month = self.start_date[:7]  # "YYYY-MM"

        for entry in schedule_data:
            day_num = int(entry["Date"].split(" ")[1])
            date_str = f"{year_month}-{day_num:02d}"
            _, _, _, _, week_number = self.date_info[date_str]

            # If the week changes, start a new week
            if current_week_number != week_number:
                if week_data["week_number"] is not None:
                    formatted_data.append(week_data)
                week_data = {
                    "week_number": week_number,
                    "sessions": [],
                }
                current_week_number = week_number

            # Add the day to the current week
            week_data["sessions"].append(
                {
                    "name": entry["Date"].split(" ")[0],  # Day name (e.g., "Monday")
                    "date": day_num,  # Day of the month (e.g., 1, 2, 3)
                    "members": entry["Members"] if entry["Members"] else [],
                    "sessionId": entry["sessionId"],
                }
            )

        # Add the last week
        if week_data["week_number"] is not None:
            formatted_data.append(week_data)

        return formatted_data

    def solve_group_scheduling(self):
        """Solve the scheduling problem."""
        t_total = time.perf_counter()
        constraints = self.scheduler_config["constraints"]
        enabled = [k for k, v in constraints.items() if v]
        logger.info("applying constraints: %s", ", ".join(enabled))

        # Pre-flight validation
        warnings = self.validate()
        for w in warnings:
            logger.warning("validation: %s", w)

        # Add constraints based on config
        if constraints["availability"]:
            self.availability_constraints()
        if constraints["max_weekly"]:
            self.add_weekly_constraints()
        if constraints["max_monthly"]:
            self.add_monthly_constraints()
        if constraints["group_size"]:
            self.add_group_size_constraints()
        if constraints["partner"]:
            self.add_partner_constraints()
        if constraints["minimum_monthly"]:
            self.add_minimum_monthly_constraints()
        if constraints["exclusion"]:
            self.add_exclusion_constraints()
        if constraints["only_session_occurrences"]:
            self.add_only_session_occurrences_constraints()
        if constraints["exclude_session_occurrences"]:
            self.add_exclude_session_occurrences_constraints()
        if constraints["min_sessions_together"]:
            self.add_min_sessions_together_constraints()
        if constraints["enforced_sessions"]:
            self.add_enforced_sessions_constraints()
        if constraints["one_session_per_day"]:
            self.add_one_session_per_day_constraints()

        t_constraints = time.perf_counter()
        proto = self.model.Proto()
        logger.info(
            "constraints built: %d variables, %d constraints (%.1fs)",
            len(proto.variables),
            len(proto.constraints),
            t_constraints - t_total,
        )

        # Feasibility check: solve constraints only (no objectives) with short timeout
        feasibility_solver = cp_model.CpSolver()
        feasibility_solver.parameters.max_time_in_seconds = 5
        feasibility_solver.parameters.num_search_workers = int(
            os.environ.get("SCHEDULER_NUM_WORKERS", "2")
        )
        logger.info("checking feasibility (5s timeout)...")
        t_feas = time.perf_counter()
        feasibility_status = feasibility_solver.Solve(self.model)
        feas_time = time.perf_counter() - t_feas

        if feasibility_status == cp_model.INFEASIBLE:
            logger.warning(
                "problem is INFEASIBLE — constraints conflict (%.1fs)", feas_time
            )
            if warnings:
                logger.warning(
                    "likely cause: see validation warnings above"
                )
            return False

        logger.info(
            "feasibility confirmed: %s in %.1fs",
            feasibility_solver.StatusName(feasibility_status),
            feas_time,
        )

        # Build objective components
        diversity_var = self.add_diversity_objective()
        consecutive_var = self.add_consecutive_days_penalty_objective()
        anchor_var = self.add_anchor_objective()

        # Set combined weighted objective
        self.set_combined_objective(diversity_var, consecutive_var, anchor_var)

        t_model = time.perf_counter()
        proto = self.model.Proto()
        logger.info(
            "model built: %d variables, %d constraints (%.1fs)",
            len(proto.variables),
            len(proto.constraints),
            t_model - t_total,
        )

        # Solve the model with objectives
        solver = self.initialize_solver()

        t_solve = time.perf_counter()
        status = solver.Solve(self.model)
        solve_time = time.perf_counter() - t_solve

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            logger.info(
                "solved: %s in %.1fs (objective=%.0f, branches=%d, conflicts=%d)",
                solver.StatusName(status),
                solve_time,
                solver.ObjectiveValue(),
                solver.NumBranches(),
                solver.NumConflicts(),
            )

            # Format schedule
            schedule_data = self.format_schedule(solver)
            formatted_data = self.format_schedule_data(schedule_data)

            # Calculate statistics
            statistics = self.calculate_statistics(solver)

            days_with_details = self.get_days_with_details()

            total_time = time.perf_counter() - t_total
            logger.info("generation complete (%.1fs total)", total_time)

            return formatted_data, statistics, days_with_details

        else:
            logger.warning(
                "no solution found: %s (%.1fs, branches=%d, conflicts=%d)",
                solver.StatusName(status),
                solve_time,
                solver.NumBranches(),
                solver.NumConflicts(),
            )
            return False


if __name__ == "__main__":
    # Example usage

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Generate a session schedule.")
    parser.add_argument("--year", type=int, help="Year in format yyyy")
    parser.add_argument("--month", type=int, help="Month in format mm")
    parser.add_argument(
        "--session_group_id",
        type=int,
        required=True,
        help="Session group ID to schedule",
    )
    args = parser.parse_args()

    # Prompt the user for missing arguments
    if not args.year:
        args.year = int(input("Please enter the year (yyyy): "))
    if not args.month:
        args.month = int(input("Please enter the month (mm): "))

    # Format start_date
    start_date = f"{args.year}-{args.month:02d}-01"

    scheduler = SessionScheduler(
        start_date=start_date,
        session_group_id=args.session_group_id,
        weekday_group_size=4,
        weekend_group_size=3,
    )

    result = scheduler.solve_group_scheduling()
    if result:
        formatted_data, statistics, days_with_details = result
        logger.info(
            "schedule generated: %d sessions", len(scheduler.available_sessions)
        )
    else:
        logger.error("failed to generate schedule")
