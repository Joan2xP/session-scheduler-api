import pandas as pd
from ortools.sat.python import cp_model
from datetime import datetime, timedelta
import calendar
import os
from jinja2 import Template
import imgkit
import argparse


class SessionScheduler:
    def __init__(
        self,
        excel_path,
        start_date,
        exclude_days=[],
        weekday_group_size=4,
        weekend_group_size=3,
        selected_days_sessions=None,
        output_path=None,
    ):
        self.exclude_days = exclude_days
        self.excel_path = excel_path
        self.start_date = start_date
        self.weekday_group_size = weekday_group_size
        self.weekend_group_size = weekend_group_size
        self.selected_days_sessions = selected_days_sessions or {
            "mon": [1],  # Monday afternoon
            "wed": [0],  # Wednesday morning
            "thu": [1],  # Thursday afternoon
            "fri": [0],  # Friday morning
            "sat": [0],  # Saturday morning
        }
        self.output_path = output_path
        self.df = pd.read_excel(excel_path)
        self.people = self.df["Name"].sample(frac=1).tolist()
        self.rows = self.df.sample(frac=1).to_dict(orient="records")
        self.n_people = len(self.people)
        self.day_mapping = {
            "mon": 0,
            "tue": 1,
            "wed": 2,
            "thu": 3,
            "fri": 4,
            "sat": 5,
            "sun": 6,
        }
        self.location_mapping = {
            0: "Estación Autobuses",
            2: "Estación autobuses",
            3: "Plaza de la Creu",
            4: "Mercadona / Universidad",
            5: "BBVA / PAS. PERE III",
        }
        self.time_slots = {
            0: {
                0: ("MAÑANA", "10:00 a 12:00"),
                1: ("TARDE", "17:30 a 19:30"),
            },
        }
        self.availability = {}
        self.partners = {}
        self.max_weekly = {}
        self.max_monthly = {}
        self.min_monthly = {}
        self.model = cp_model.CpModel()
        self.attendance = {}
        self.only_days_of_month = {}
        self.exclude_days_of_month = {}

        # Preprocess available days and sessions
        self.available_days_and_sessions = []
        self.all_available_days_and_sessions = []

        self.initialize()

    def preprocess_available_days_and_sessions(self):
        """Preprocess the selected days and sessions into a list of (day, session) tuples."""
        start_date = datetime.strptime(
            self.start_date, "%Y-%m-%d"
        )  # Parse the start date
        print(f"Excluding days: {self.exclude_days}")

        # Get the number of days in the month
        _, days_in_month = calendar.monthrange(start_date.year, start_date.month)

        for day_name, sessions in self.selected_days_sessions.items():
            # Get the day index (0 = Monday, 6 = Sunday) for the given day name
            day_index = self.day_mapping[day_name]

            for day_offset in range(
                days_in_month
            ):  # Iterate through all days in the month
                current_date = start_date + timedelta(days=day_offset)
                current_day_of_week = current_date.weekday()  # 0 = Monday, 6 = Sunday

                is_excluded = current_date.day in self.exclude_days
                # If the current day matches the desired day of the week
                if current_day_of_week == day_index:
                    day = day_offset  # Use the offset as the day index
                    for session in sessions:
                        if not is_excluded:
                            self.available_days_and_sessions.append((day, session))
                        self.all_available_days_and_sessions.append((day, session))

    def initialize(self):
        self.preprocess_available_days_and_sessions()
        # Convert availability strings to lists of day indices
        for row in self.rows:
            person = row["Name"]
            avail_days = str(row["Availability"]).split(",")
            self.availability[person] = [
                self.day_mapping[day.strip()] for day in avail_days
            ]
            self.min_monthly[person] = int(row["Min per Month"])

            # Parse Only Days of Month
            only_days = row.get("Only Days of Month", "")
            if pd.notna(only_days):
                print(
                    f"Only Days of Month for {person}: {only_days} : {type(only_days)}"
                )
                if isinstance(only_days, str):
                    self.only_days_of_month[person] = [
                        int(day.strip()) for day in only_days.split(",")
                    ]
                else:
                    self.only_days_of_month[person] = [only_days]
            else:
                self.only_days_of_month[person] = []

            # Parse Exclude Days of Month
            exclude_days = row.get("Exclude Days of Month", "")
            if pd.notna(exclude_days):
                self.exclude_days_of_month[person] = (
                    [
                        int(day.strip())
                        for day in exclude_days.split(",")
                        if day.strip().isdigit()
                    ]
                    if exclude_days
                    else []
                )

        # Extract partner constraints
        for row in self.rows:
            person = row["Name"]
            if pd.notna(row.get("Partner", None)):
                self.partners[person] = row["Partner"]

        # Extract max attendance constraints
        for row in self.rows:
            person = row["Name"]
            self.max_weekly[person] = int(row["Max per Week"])
            self.max_monthly[person] = int(row["Max per Month"])

        # Initialize attendance variables
        for person in self.people:
            self.attendance[person] = {}
            for day, session in self.available_days_and_sessions:
                if day not in self.attendance[person]:
                    self.attendance[person][day] = {}
                self.attendance[person][day][session] = self.model.NewBoolVar(
                    f"{person}_day{day}_session{session}"
                )

    def add_only_days_of_month_constraints(self):
        """Ensure each person is only scheduled on their specified days of the month."""
        for person, only_days in self.only_days_of_month.items():
            if only_days:  # If the person has specified days
                for day, session in self.available_days_and_sessions:
                    current_date = datetime.strptime(
                        self.start_date, "%Y-%m-%d"
                    ) + timedelta(days=day)
                    if current_date.day not in only_days:
                        self.model.Add(self.attendance[person][day][session] == 0)

    def add_exclude_days_of_month_constraints(self):
        """Ensure each person is not scheduled on their excluded days of the month."""
        for person, exclude_days in self.exclude_days_of_month.items():
            if exclude_days:  # If the person has excluded days
                for day, session in self.available_days_and_sessions:
                    current_date = datetime.strptime(
                        self.start_date, "%Y-%m-%d"
                    ) + timedelta(days=day)
                    if current_date.day in exclude_days:
                        self.model.Add(self.attendance[person][day][session] == 0)

    def add_minimum_monthly_constraints(self):
        """Ensure each person attends at least the minimum number of sessions per month."""
        print(f"available days:{len(self.available_days_and_sessions)}")
        for person in self.people:
            min_per_month = self.min_monthly[
                person
            ]  # Get the minimum sessions per month
            if len(self.available_days_and_sessions) <= 20:
                if min_per_month > 4:
                    min_per_month = 4
            month_vars = [
                self.attendance[person][day][session]
                for day, session in self.available_days_and_sessions
            ]
            # Add the constraint for the minimum number of sessions
            self.model.Add(sum(month_vars) >= min_per_month)

    def availability_constraints(self):
        """Ensure people only attend sessions on days they are available."""
        for person in self.people:
            avail_days_of_week = self.availability[person]
            for day, session in self.available_days_and_sessions:
                # Calculate the actual date for the current day
                current_date = datetime.strptime(
                    self.start_date, "%Y-%m-%d"
                ) + timedelta(days=day)
                day_of_week = current_date.weekday()  # 0 = Monday, 6 = Sunday

                # If the day of the week is not in the person's availability, add a constraint
                if day_of_week not in avail_days_of_week:
                    self.model.Add(self.attendance[person][day][session] == 0)

    def add_weekly_constraints(self):
        """Add weekly attendance constraints for each person."""
        for person in self.people:
            max_per_week = self.max_weekly[person]
            week_vars = []
            current_week = None

            for day, session in self.available_days_and_sessions:
                # Calculate the ISO week number for the current day
                day_date = datetime.strptime(self.start_date, "%Y-%m-%d") + timedelta(
                    days=day
                )
                week_number = day_date.isocalendar()[1]

                # If the week changes, add the constraint for the previous week
                if current_week is not None and week_number != current_week:
                    self.model.Add(sum(week_vars) <= max_per_week)
                    week_vars = []  # Reset for the new week

                # Update the current week and append the attendance variable
                current_week = week_number
                week_vars.append(self.attendance[person][day][session])

            # Add the constraint for the last week
            if week_vars:
                self.model.Add(sum(week_vars) <= max_per_week)

    def add_monthly_constraints(self):
        """Add monthly attendance constraints for each person."""
        for person in self.people:
            max_per_month = self.max_monthly[person]
            month_vars = [
                self.attendance[person][day][session]
                for day, session in self.available_days_and_sessions
            ]
            self.model.Add(sum(month_vars) <= max_per_month)

    def add_group_size_constraints(self):
        """Ensure group size constraints are respected."""
        for day, session in self.available_days_and_sessions:
            start_date = datetime.strptime(self.start_date, "%Y-%m-%d")
            current_date = start_date + timedelta(days=day)
            day_of_week = current_date.weekday()  # 0 = Monday, 6 = Sunday
            group_size = (
                self.weekend_group_size if day_of_week >= 5 else self.weekday_group_size
            )
            group_members = [
                self.attendance[person][day][session] for person in self.people
            ]
            self.model.Add(sum(group_members) == group_size)

    def add_partner_constraints(self):
        """Ensure partners are in the same group when both attend."""
        for person, partner in self.partners.items():
            for day, session in self.available_days_and_sessions:
                # Ensure the partner is also attending if the person is attending
                self.model.Add(
                    self.attendance[person][day][session]
                    <= self.attendance[partner][day][session]
                )

    def add_exclusion_constraints(self):
        """Ensure people listed in the 'Exclude' column are not scheduled together."""
        for _, row in self.df.iterrows():
            person = row["Name"]
            if pd.notna(row.get("Exclude", None)):
                excluded_people = [name.strip() for name in row["Exclude"].split(",")]
                for excluded_person in excluded_people:
                    if excluded_person in self.people:
                        for day, session in self.available_days_and_sessions:
                            # Ensure the person and excluded person are not both attending the same session
                            self.model.Add(
                                self.attendance[person][day][session]
                                + self.attendance[excluded_person][day][session]
                                <= 1
                            )

    def add_diversity_objective(self):
        """
        A more lightweight diversity objective that encourages diverse pairings
        by minimizing repeated appearances of the same pairs.
        """
        # Track pair occurrences
        pair_counts = {}

        # For each person pair, count how many times they're scheduled together
        for i, person1 in enumerate(self.people):
            for j, person2 in enumerate(self.people):
                if i < j:  # Avoid duplicate pairs
                    pair_key = f"{person1}_{person2}"
                    pair_counts[pair_key] = []

                    # Count occurrences across all sessions
                    for day, session in self.available_days_and_sessions:
                        # Create a variable for this pair at this day/session
                        pair_var = self.model.NewBoolVar(
                            f"pair_{pair_key}_day{day}_session{session}"
                        )

                        # Link this variable to the attendance of both people
                        # pair_var is 1 only if both are attending this session
                        self.model.AddBoolAnd(
                            [
                                self.attendance[person1][day][session],
                                self.attendance[person2][day][session],
                            ]
                        ).OnlyEnforceIf(pair_var)

                        # pair_var is 0 if either person is not attending
                        self.model.AddBoolOr(
                            [
                                self.attendance[person1][day][session].Not(),
                                self.attendance[person2][day][session].Not(),
                            ]
                        ).OnlyEnforceIf(pair_var.Not())

                        pair_counts[pair_key].append(pair_var)

        # Create objective: minimize the maximum number of times any pair appears together
        max_appearances = self.model.NewIntVar(
            0, len(self.available_days_and_sessions), "max_pair_appearances"
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
        """Add an objective to maximize the minimum separation between sessions for each person."""
        min_gap_vars = []

        for person in self.people:
            # Collect all (day, session) pairs for the person
            person_sessions = [
                (day, session) for day, session in self.available_days_and_sessions
            ]

            # Skip persons who will only attend one session
            if len(person_sessions) <= 1:
                continue

            # Create a variable for the minimum gap for this person
            min_gap = self.model.NewIntVar(0, 31, f"min_gap_{person}")
            min_gap_vars.append(min_gap)

            # Add constraints to calculate the gaps between sessions
            gap_vars = []
            for i in range(len(person_sessions)):
                for j in range(i + 1, len(person_sessions)):
                    day1, session1 = person_sessions[i]
                    day2, session2 = person_sessions[j]

                    # Create a variable for the gap
                    gap_var = self.model.NewIntVar(
                        0, 31, f"gap_{person}_{i}_{j}"  # 31 is the max days in a month
                    )
                    self.model.AddAbsEquality(
                        gap_var,
                        (day2 - day1) + (session2 - session1),
                    )
                    gap_vars.append(gap_var)

            # Ensure the minimum gap is less than or equal to all gaps
            if gap_vars:
                self.model.AddMinEquality(min_gap, gap_vars)

        # Maximize the minimum gap across all people
        if min_gap_vars:
            self.model.Maximize(sum(min_gap_vars))

    def add_min_days_together_constraints(self):
        """Ensure partners are scheduled together for at least the specified number of sessions on specific weekdays."""
        for _, row in self.df.iterrows():
            person = row["Name"]

            # Parse the Min Days Together column
            min_days_together = row.get("Min Days Together", "")
            if pd.notna(min_days_together) and isinstance(min_days_together, str):
                # Example format: "mon-2, wed-1"
                day_constraints = [
                    constraint.strip().split("-")
                    for constraint in min_days_together.split(",")
                ]

                for constraint in day_constraints:
                    # Validate the format (must have exactly 2 parts: day_name and min_sessions)
                    if len(constraint) != 3:
                        continue

                    day_name, min_sessions, partner = constraint
                    day_index = self.day_mapping.get(day_name.strip().lower())
                    if day_index is None:
                        continue  # Skip invalid day names

                    print(
                        f"Adding min days together constraint for {person} and {partner} on {day_name}: {min_sessions}"
                    )

                    # Collect attendance variables for the person and their partner on the specified day
                    together_vars = []
                    for day, session in self.available_days_and_sessions:
                        current_date = datetime.strptime(
                            self.start_date, "%Y-%m-%d"
                        ) + timedelta(days=day)
                        if current_date.weekday() == day_index:
                            # Both person and partner must attend the same session
                            together_var = self.model.NewBoolVar(
                                f"{person}_{partner}_together_day{day}_session{session}"
                            )
                            self.model.AddBoolAnd(
                                [
                                    self.attendance[person][day][session],
                                    self.attendance[partner][day][session],
                                ]
                            ).OnlyEnforceIf(together_var)
                            together_vars.append(together_var)

                    # Add the constraint for the minimum number of sessions together
                    if together_vars:
                        self.model.Add(sum(together_vars) >= int(min_sessions))

    def initialize_solver(self):
        """Initialize the solver and set parameters."""
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 300  # 5 minutes time limit
        # solver.parameters.log_search_progress = True  # Enable detailed logging
        return solver

    def format_schedule(self, solver):
        """Format the schedule into a structured list."""
        schedule_data = []
        start_date = datetime.strptime(
            self.start_date, "%Y-%m-%d"
        )  # Parse the start date

        for day, session in sorted(self.all_available_days_and_sessions):
            # Calculate the actual date for the current day
            current_date = start_date + timedelta(days=day)
            day_of_week = current_date.weekday()  # 0 = Monday, 6 = Sunday

            # Get location and time slot
            location = self.location_mapping[day_of_week]
            time_period, time_range = self.time_slots[0][session]

            # Get day name in Spanish
            day_names_es = [
                "Lunes",
                "Martes",
                "Miércoles",
                "Jueves",
                "Viernes",
                "Sábado",
                "Domingo",
            ]
            day_name = day_names_es[day_of_week]

            # Check if the day and session are in available days
            if (day, session) not in self.available_days_and_sessions:
                # Add to schedule data with no members
                schedule_data.append(
                    {
                        "Date": f"{day_name} {current_date.day}",
                        "Time": time_period,
                        "Time_Range": time_range,
                        "Location": location,
                        "Members": "No hay carritos",
                    }
                )
            else:
                # Get group members
                members = []
                for person in self.people:
                    if solver.Value(self.attendance[person][day][session]) == 1:
                        members.append(person)

                # Add to schedule data
                schedule_data.append(
                    {
                        "Date": f"{day_name} {current_date.day}",
                        "Time": time_period,
                        "Time_Range": time_range,
                        "Location": location,
                        "Members": ", ".join(members),
                    }
                )

        return schedule_data

    def get_days_with_details(self):
        days_with_details = []
        for day_name in ["Lunes", "Miércoles", "Jueves", "Viernes", "Sábado"]:
            # Map Spanish day names to their corresponding indices
            day_index = [
                "Lunes",
                "Martes",
                "Miércoles",
                "Jueves",
                "Viernes",
                "Sábado",
                "Domingo",
            ].index(day_name)

            selected_sessions = self.selected_days_sessions.get(
                list(self.day_mapping.keys())[
                    list(self.day_mapping.values()).index(day_index)
                ],
                [],
            )
            location = self.location_mapping.get(day_index, "Unknown Location")
            time_period, time_range = self.time_slots[0][
                selected_sessions[0]
            ]  # Assuming morning session for header
            days_with_details.append(
                {"day": day_name, "location": location, "time": time_range}
            )

        return days_with_details

    def export_to_excel(self, schedule_data, output_path):
        """Export the schedule to an Excel file."""
        schedule_df = pd.DataFrame(schedule_data)
        with pd.ExcelWriter(output_path, engine="xlsxwriter") as excel_writer:
            schedule_df.to_excel(excel_writer, sheet_name="Schedule", index=False)
            print(f"Schedule saved to Excel: {output_path}")

    def calculate_statistics(self, solver):
        """Calculate and print attendance statistics."""
        attendance_data = {}

        for person in self.people:
            person_sessions = []
            for day, session in self.available_days_and_sessions:
                if solver.Value(self.attendance[person][day][session]) == 1:
                    person_sessions.append(f"{day+1}")
            attendance_data[person] = person_sessions

        print("\nAttendance Summary:")
        attendance_summary = []
        for person, sessions in attendance_data.items():
            session_count = len(sessions)
            print(f"{person}: {session_count} sessions")
            sessions.sort(key=lambda x: int(x))
            attendance_summary.append(
                {
                    "person": person,
                    "sessionCount": session_count,
                    "days": ", ".join(sessions),
                }
            )

        # Sort by session count in descending order
        attendance_summary = sorted(
            attendance_summary, key=lambda x: x["sessionCount"], reverse=True
        )

        return attendance_summary

    def generate_html_table(self, schedule_data, output_html_path="schedule.html"):
        """Generate an HTML table using the provided structure and styles."""
        # Define the HTML template based on the provided TSX structure
        schedule_df = pd.DataFrame(schedule_data)
        formatted_data = self.format_schedule_data(
            schedule_df.to_dict(orient="records")
        )
        print(f"Formatted data: {formatted_data}")
        html_template = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Weekly Schedule</title>
            <style>
            {{ css_styles }}
            </style>
        </head>
        <body>
            <div class="schedule-container">
            <h2 class="schedule-title">
                Exhibidores {{ month }} {{ year }}
            </h2>
            
            <div class="table-wrapper">
                <table class="schedule-table">
                <thead>
                    <tr>
                    <th class="header-date">Día</th>
                    {% for day, location, time in days_with_details %}
                    <th class="header-date header-{{ day.lower() }}">
                        <div class="day-header">
                        <strong>{{ day }}</strong>
                        <div class="day-details">
                        {{ location }}<br>
                        {{ time }}
                        </div>
                        </div>
                    </th>
                    {% endfor %}
                    </tr>
                </thead>
                <tbody>
                    {% for week in schedule_data %}
                    <tr>
                    <td colspan="6" class="week-separator">Semana {{ week.week_number }}</td>
                    </tr>
                    {% for day in week.days %}
                    <tr>
                    <td class="cell cell-date"><p>{{ day.name }}</p> <p>{{ day.date }}</p></td>
                    {% for column_day, location, time in days_with_details  %}
                    <td class="cell {% if column_day == day.name %}cell-{{ day.name.lower() }} {% if day.members[0] == "No hay carritos" %}no-hay-carritos{% endif %}{% endif %} ">
                        {% if column_day == day.name %}
                        <div class="names-container">
                        {% for name in day.members %}
                        <div class="name">{{ name }}</div>
                        {% endfor %}
                        </div>
                        {% endif %}
                    </td>
                    {% endfor %}
                    </tr>
                    {% endfor %}
                    {% endfor %}
                </tbody>
                </table>
            </div>
            </div>
        </body>
        </html>
        """

        # Prepare the days with their respective details (localization and time)
        days_with_details = []
        for day_name in ["Lunes", "Miércoles", "Jueves", "Viernes", "Sábado"]:
            # Map Spanish day names to their corresponding indices
            day_index = [
                "Lunes",
                "Martes",
                "Miércoles",
                "Jueves",
                "Viernes",
                "Sábado",
                "Domingo",
            ].index(day_name)

            selected_sessions = self.selected_days_sessions.get(
                list(self.day_mapping.keys())[
                    list(self.day_mapping.values()).index(day_index)
                ],
                [],
            )
            location = self.location_mapping.get(day_index, "Unknown Location")
            time_period, time_range = self.time_slots[0][
                selected_sessions[0]
            ]  # Assuming morning session for header
            days_with_details.append((day_name, location, time_range))

        # Render the HTML with the schedule data
        template = Template(html_template)
        css_styles = open("schedule.css").read()  # Load the provided CSS file
        # Extract the month and year dynamically from the start_date
        start_date_obj = datetime.strptime(self.start_date, "%Y-%m-%d")
        month = start_date_obj.strftime("%B")
        month_translation = {
            "January": "Enero",
            "February": "Febrero",
            "March": "Marzo",
            "April": "Abril",
            "May": "Mayo",
            "June": "Junio",
            "July": "Julio",
            "August": "Agosto",
            "September": "Septiembre",
            "October": "Octubre",
            "November": "Noviembre",
            "December": "Diciembre",
        }
        month = month_translation.get(month, month)  # Translate to Spanish
        year = start_date_obj.year

        html_content = template.render(
            css_styles=css_styles,
            month=month,  # Use dynamic month
            year=year,  # Use dynamic year
            days_with_details=days_with_details,
            schedule_data=formatted_data,
        )

        # Save the HTML to a file
        with open(output_html_path, "w") as f:
            f.write(html_content)

        print(f"HTML table saved to {output_html_path}")

    def format_schedule_data(self, schedule_data):
        """Format the schedule data into the structure required for rendering."""
        formatted_data = []
        current_week_number = None
        week_data = {"week_number": None, "days": []}

        for entry in schedule_data:
            # Extract the week number from the date
            date_obj = datetime.strptime(
                f"{entry['Date'].split(' ')[1]}-{self.start_date.split('-')[1]}-{self.start_date.split('-')[0]}",
                "%d-%m-%Y",
            )
            week_number = date_obj.isocalendar()[1]

            # If the week changes, start a new week
            if current_week_number != week_number:
                if week_data["week_number"] is not None:
                    formatted_data.append(week_data)
                week_data = {
                    "week_number": week_number
                    - (date_obj.replace(day=1).isocalendar()[1] - 1),
                    "days": [],
                }
                current_week_number = week_number

            # Add the day to the current week
            week_data["days"].append(
                {
                    "name": entry["Date"].split(" ")[0],  # Day name (e.g., "Monday")
                    "date": date_obj.day,  # Day of the month (e.g., 1, 2, 3)
                    "members": entry["Members"].split(", ") if entry["Members"] else [],
                }
            )

        # Add the last week
        if week_data["week_number"] is not None:
            formatted_data.append(week_data)

        return formatted_data

    def convert_html_to_image(
        self, input_html_path="schedule.html", output_image_path="schedule.png"
    ):
        """Convert an HTML file to an image."""
        # Options for wkhtmltoimage
        options = {
            "format": "png",  # Output format
            "quality": "100",  # Image quality
            "encoding": "UTF-8",  # Encoding
            "width": 1250,  # Set a fixed width for the image
            # "height": 0,  # Set a fixed height for the image
            "disable-smart-width": "",  # Disable smart width to capture full content width
            "zoom": 1.0,  # Adjust zoom level to preserve proportions
        }

        # Convert the HTML file to an image
        try:
            imgkit.from_file(input_html_path, output_image_path, options=options)
            print(f"Image saved to {output_image_path}")
        except Exception as e:
            print(f"Error converting HTML to image: {e}")

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
        self.add_only_days_of_month_constraints()
        self.add_exclude_days_of_month_constraints()
        self.add_min_days_together_constraints()

        # Set the objective
        self.add_diversity_objective()
        self.add_session_separation_objective()

        # Solve the model
        solver = self.initialize_solver()

        print("Solving the model...")
        status = solver.Solve(self.model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(f"Solution found with status: {solver.StatusName(status)}")
            # Get active days
            # active_days = self.get_active_days(solver)

            # Format schedule
            schedule_data = self.format_schedule(solver)
            schedule_df = pd.DataFrame(schedule_data)
            formatted_data = self.format_schedule_data(
                schedule_df.to_dict(orient="records")
            )

            # Export to Excel

            # Calculate statistics
            statistics = self.calculate_statistics(solver)

            days_with_details = self.get_days_with_details()

            return formatted_data, statistics, days_with_details

        else:
            print(f"No solution found: {solver.StatusName(status)}")
            return False


if __name__ == "__main__":
    # Example usage
    excel_path = "people_availability.xlsx"

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Generate a session schedule.")
    parser.add_argument("--year", type=int, help="Year in format yyyy")
    parser.add_argument("--month", type=int, help="Month in format mm")
    parser.add_argument(
        "--exclude_days",
        type=str,
        default="",
        help="Comma-separated list of days to exclude (e.g., 1,15,30) or leave empty",
    )
    args = parser.parse_args()

    # Prompt the user for missing arguments
    if not args.year or not args.month:
        args.exclude_days = input(
            "Enter comma-separated list of days to exclude (e.g., 1,15,30) or leave empty: "
        )
    if not args.year:
        args.year = int(input("Please enter the year (yyyy): "))
    if not args.month:
        args.month = int(input("Please enter the month (mm): "))

    # Convert exclude_days to a list of integers
    exclude_days = (
        [int(day.strip()) for day in args.exclude_days.split(",") if day.strip()]
        if args.exclude_days
        else []
    )
    # Format start_date
    start_date = f"{args.year}-{args.month:02d}-01"

    list_generator = SessionScheduler(
        excel_path=excel_path,
        start_date=start_date,
        weekday_group_size=4,
        weekend_group_size=3,
        exclude_days=exclude_days,
    )

    # Create empty template if file doesn't exist
    if not os.path.exists(excel_path):
        print(f"Please fill in the template ({excel_path}) and run this script again.")
    else:
        success = list_generator.solve_group_scheduling(
            start_date=start_date,
        )
