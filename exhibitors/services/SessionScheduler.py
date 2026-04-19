import pandas as pd
from ortools.sat.python import cp_model
from datetime import datetime, timedelta
import calendar
import os
from jinja2 import Template
import imgkit
import argparse
from django.db.models import Case, When, Value, IntegerField
from exhibitors.models import Participant, Session, SessionGroup
import random


class SessionScheduler:
    def __init__(
        self,
        start_date,
        session_group_id,
        exclude_session_occurrences=None,
        weekday_group_size=4,
        weekend_group_size=3,
    ):
        self.start_date = start_date
        self.session_group_id = session_group_id
        self.exclude_session_occurrences = exclude_session_occurrences or []
        self.weekday_group_size = weekday_group_size
        self.weekend_group_size = weekend_group_size

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

        # Available sessions as (session_id, date) tuples
        self.available_sessions = []
        self.all_available_sessions = []

        self.initialize()

    def get_data(self):
        # Fetch participants filtered by session_group_id
        participants = Participant.objects.filter(
            session_group_id=self.session_group_id
        )

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

        print(f"Excluding session occurrences: {excluded_occurrences}")

        # For each session in the session group, generate occurrences
        for session_id, metadata in self.session_metadata.items():
            frequency = metadata["frequency"]
            session_day_of_week = metadata["day_of_week"]
            session_week = metadata["week"]
            session_month = metadata["month"]

            for day_offset in range(days_in_month):
                current_date = start_date + timedelta(days=day_offset)
                current_day_of_week = current_date.weekday()
                date_str = current_date.strftime("%Y-%m-%d")

                # Check if this date matches the session's frequency pattern
                should_include = False

                if frequency == "daily":
                    # Daily: include every day
                    should_include = True

                elif frequency == "weekly":
                    # Weekly: include if day_of_week matches
                    if (
                        session_day_of_week is not None
                        and current_day_of_week == session_day_of_week
                    ):
                        should_include = True

                elif frequency == "monthly":
                    # Monthly: include if day_of_week matches AND week of month matches
                    if (
                        session_day_of_week is not None
                        and current_day_of_week == session_day_of_week
                    ):
                        # Calculate week of month (1-based)
                        first_day_weekday = start_date.weekday()
                        week_of_month = (
                            (current_date.day + first_day_weekday - 1) // 7
                        ) + 1
                        if session_week is None or week_of_month == session_week:
                            should_include = True

                elif frequency == "yearly":
                    # Yearly: include if month matches AND day_of_week matches AND week matches
                    if (
                        session_month is not None
                        and current_date.month == session_month
                    ):
                        if (
                            session_day_of_week is not None
                            and current_day_of_week == session_day_of_week
                        ):
                            # Calculate week of month
                            first_day_weekday = start_date.weekday()
                            week_of_month = (
                                (current_date.day + first_day_weekday - 1) // 7
                            ) + 1
                            if session_week is None or week_of_month == session_week:
                                should_include = True

                if should_include:
                    occurrence = (session_id, date_str)
                    # Add to all_available_sessions (including excluded)
                    self.all_available_sessions.append(occurrence)
                    # Add to available_sessions only if not excluded
                    if occurrence not in excluded_occurrences:
                        self.available_sessions.append(occurrence)

        # Sort by date then session_id for consistent ordering
        self.available_sessions.sort(key=lambda x: (x[1], x[0]))
        self.all_available_sessions.sort(key=lambda x: (x[1], x[0]))

    def initialize(self):
        self.get_data()
        self.preprocess_available_sessions()

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

        # Initialize attendance variables with (session_id, date) keys
        for participant_id in self.people:
            self.attendance[participant_id] = {}
            for session_id, date in self.available_sessions:
                self.attendance[participant_id][(session_id, date)] = (
                    self.model.NewBoolVar(f"p{participant_id}_s{session_id}_{date}")
                )

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
                    print(f"{participant_id}: only_session_occurrences: {occ}")
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
        print(f"available sessions: {len(self.available_sessions)}")
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
                # Parse the date and calculate the ISO week number
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                week_number = date_obj.isocalendar()[1]

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
            # Calculate day of week from date
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            day_of_week = date_obj.weekday()  # 0 = Monday, 6 = Sunday
            group_size = (
                self.weekend_group_size if day_of_week >= 5 else self.weekday_group_size
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

    def add_diversity_objective(self):
        """
        A more lightweight diversity objective that encourages diverse pairings
        by minimizing repeated appearances of the same pairs.
        """
        # Track pair occurrences
        pair_counts = {}

        # For each participant pair, count how many times they're scheduled together
        for i, participant1 in enumerate(self.people):
            for j, participant2 in enumerate(self.people):
                if i < j:  # Avoid duplicate pairs
                    pair_key = f"p{participant1}_p{participant2}"
                    pair_counts[pair_key] = []

                    # Count occurrences across all sessions
                    for session_id, date in self.available_sessions:
                        # Create a variable for this pair at this session occurrence
                        pair_var = self.model.NewBoolVar(
                            f"pair_{pair_key}_s{session_id}_{date}"
                        )

                        # Link this variable to the attendance of both participants
                        # pair_var is 1 only if both are attending this session
                        self.model.AddBoolAnd(
                            [
                                self.attendance[participant1][(session_id, date)],
                                self.attendance[participant2][(session_id, date)],
                            ]
                        ).OnlyEnforceIf(pair_var)

                        # pair_var is 0 if either participant is not attending
                        self.model.AddBoolOr(
                            [
                                self.attendance[participant1][(session_id, date)].Not(),
                                self.attendance[participant2][(session_id, date)].Not(),
                            ]
                        ).OnlyEnforceIf(pair_var.Not())

                        pair_counts[pair_key].append(pair_var)

        # Create objective: minimize the maximum number of times any pair appears together
        max_appearances = self.model.NewIntVar(
            0, len(self.available_sessions), "max_pair_appearances"
        )

        # For each pair, create a variable representing their total appearances
        pair_totals = []
        for pair_key, vars_list in pair_counts.items():
            pair_total = self.model.NewIntVar(0, len(vars_list), f"total_{pair_key}")
            self.model.Add(pair_total == sum(vars_list))
            pair_totals.append(pair_total)

            # Constrain max_appearances to be >= each pair's count
            self.model.Add(max_appearances >= pair_total)

        # Minimize the maximum number of times any pair appears together
        self.model.Minimize(max_appearances)

    def add_session_separation_objective(self):
        """Add an objective to maximize the minimum separation between sessions for each participant."""
        min_gap_vars = []
        start_date = datetime.strptime(self.start_date, "%Y-%m-%d")

        for participant_id in self.people:
            # Collect all (session_id, date) pairs with their day offsets
            participant_sessions = []
            for session_id, date in self.available_sessions:
                date_obj = datetime.strptime(date, "%Y-%m-%d")
                day_offset = (date_obj - start_date).days
                participant_sessions.append((session_id, date, day_offset))

            # Skip participants who will only attend one session
            if len(participant_sessions) <= 1:
                continue

            # Create a variable for the minimum gap for this participant
            min_gap = self.model.NewIntVar(0, 31, f"min_gap_p{participant_id}")
            min_gap_vars.append(min_gap)

            # Add constraints to calculate the gaps between sessions
            gap_vars = []
            for i in range(len(participant_sessions)):
                for j in range(i + 1, len(participant_sessions)):
                    _, _, day_offset1 = participant_sessions[i]
                    _, _, day_offset2 = participant_sessions[j]

                    # Create a variable for the gap (in days)
                    gap_var = self.model.NewIntVar(
                        0, 31, f"gap_p{participant_id}_{i}_{j}"
                    )
                    self.model.AddAbsEquality(
                        gap_var,
                        day_offset2 - day_offset1,
                    )
                    gap_vars.append(gap_var)

            # Ensure the minimum gap is less than or equal to all gaps
            if gap_vars:
                self.model.AddMinEquality(min_gap, gap_vars)

        # Maximize the minimum gap across all participants
        if min_gap_vars:
            self.model.Maximize(sum(min_gap_vars))

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
            print(
                f"Adding min sessions together constraint for {participant_name} and {partner_name} "
                f"on session {target_session_id}: {min_sessions}"
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

    def initialize_solver(self):
        """Initialize the solver and set parameters."""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes time limit
        # solver.parameters.log_search_progress = True  # Enable detailed logging
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

        for session_id, date in sorted(
            self.all_available_sessions, key=lambda x: (x[1], x[0])
        ):
            # Parse the date
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            day_of_week = date_obj.weekday()
            day_name = day_names_es[day_of_week]

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
            if (session_id, date) not in self.available_sessions:
                # Add to schedule data with no members
                schedule_data.append(
                    {
                        "Date": f"{day_name} {date_obj.day}",
                        "Time": time_period,
                        "Time_Range": time_range,
                        "Location": location,
                        "Members": "No hay carritos",
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
                        members.append(name)

                # Add to schedule data
                schedule_data.append(
                    {
                        "Date": f"{day_name} {date_obj.day}",
                        "Time": time_period,
                        "Time_Range": time_range,
                        "Location": location,
                        "Members": ", ".join(members),
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
        """Calculate and print attendance statistics."""
        attendance_data = {}
        start_date = datetime.strptime(self.start_date, "%Y-%m-%d")

        for participant_id in self.people:
            participant_sessions = []
            for session_id, date in self.available_sessions:
                if (
                    solver.Value(self.attendance[participant_id][(session_id, date)])
                    == 1
                ):
                    date_obj = datetime.strptime(date, "%Y-%m-%d")
                    participant_sessions.append(str(date_obj.day))
            attendance_data[participant_id] = participant_sessions

        print("\nAttendance Summary:")
        attendance_summary = []
        for participant_id, sessions in attendance_data.items():
            session_count = len(sessions)
            name = self.participant_names.get(participant_id, str(participant_id))
            print(f"{name}: {session_count} sessions")
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

        # Get the first day of the month
        first_day = datetime.strptime(self.start_date, "%Y-%m-%d")

        for entry in schedule_data:
            # Extract the date from the entry
            date_obj = datetime.strptime(
                f"{entry['Date'].split(' ')[1]}-{self.start_date.split('-')[1]}-{self.start_date.split('-')[0]}",
                "%d-%m-%Y",
            )

            # Calculate week number based on days from start of month
            # Get the weekday of the first day of the month (0=Monday, 6=Sunday)
            first_day_weekday = first_day.weekday()
            # Calculate week of month (1-based)
            week_number = ((date_obj.day + first_day_weekday - 1) // 7) + 1

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
                    "date": date_obj.day,  # Day of the month (e.g., 1, 2, 3)
                    "members": entry["Members"].split(", ") if entry["Members"] else [],
                    "sessionId": entry["sessionId"],
                }
            )

        # Add the last week
        if week_data["week_number"] is not None:
            formatted_data.append(week_data)

        return formatted_data

    def solve_group_scheduling(self):
        """Solve the scheduling problem."""

        # Add constraints
        self.availability_constraints()
        self.add_weekly_constraints()
        self.add_monthly_constraints()
        self.add_group_size_constraints()
        self.add_partner_constraints()

        self.add_minimum_monthly_constraints()

        self.add_exclusion_constraints()
        self.add_only_session_occurrences_constraints()
        self.add_exclude_session_occurrences_constraints()
        self.add_min_sessions_together_constraints()
        self.add_enforced_sessions_constraints()

        # Set the objective
        self.add_diversity_objective()
        self.add_session_separation_objective()

        # Solve the model
        solver = self.initialize_solver()

        print("Solving the model...")
        status = solver.Solve(self.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(f"Solution found with status: {solver.StatusName(status)}")

            # Format schedule
            schedule_data = self.format_schedule(solver)
            schedule_df = pd.DataFrame(schedule_data)
            formatted_data = self.format_schedule_data(
                schedule_df.to_dict(orient="records")
            )

            # Calculate statistics
            statistics = self.calculate_statistics(solver)

            days_with_details = self.get_days_with_details()

            return formatted_data, statistics, days_with_details

        else:
            print(f"No solution found: {solver.StatusName(status)}")
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
        print(f"\nSchedule generated successfully!")
        print(f"Total sessions: {len(scheduler.available_sessions)}")
    else:
        print("Failed to generate schedule.")
