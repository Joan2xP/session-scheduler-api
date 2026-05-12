from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from exhibitors.models import SessionGroup, Session, Participant, ParticipantTrait


class Command(BaseCommand):
    help = "Load demo mock data for the 'demo' user"

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username="demo")
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR("User 'demo' does not exist. Create it first."))
            return

        # Remove existing demo data
        SessionGroup.objects.filter(user=user).delete()
        self.stdout.write(self.style.WARNING("Deleted existing demo data."))

        # Create SessionGroup
        sg = SessionGroup.objects.create(
            user=user,
            name="Demo Scheduler",
            scheduler_config={
                "constraints": {
                    "availability": True,
                    "max_weekly": True,
                    "max_monthly": True,
                    "group_size": True,
                    "partner": True,
                    "minimum_monthly": True,
                    "exclusion": True,
                    "only_session_occurrences": True,
                    "exclude_session_occurrences": True,
                    "min_sessions_together": True,
                    "enforced_sessions": True,
                    "one_session_per_day": True,
                },
                "objectives": {
                    "diversity": {"enabled": True, "weight": 6},
                    "session_separation": {"enabled": True, "weight": 3},
                    "consecutive_days_penalty": {"enabled": True, "weight": 8},
                },
                "weekday_group_size": 4,
                "weekend_group_size": 3,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Created SessionGroup: {sg.name}"))

        # Create Sessions
        sessions_data = [
            {"frequency": "weekly", "day": 0, "start_h": 9, "start_m": 0, "end_h": 11, "end_m": 0, "loc": "Central Park"},
            {"frequency": "weekly", "day": 1, "start_h": 10, "start_m": 0, "end_h": 12, "end_m": 0, "loc": "Community Center"},
            {"frequency": "weekly", "day": 2, "start_h": 14, "start_m": 0, "end_h": 16, "end_m": 0, "loc": "Riverside Plaza"},
            {"frequency": "weekly", "day": 3, "start_h": 9, "start_m": 0, "end_h": 11, "end_m": 0, "loc": "University Campus"},
            {"frequency": "weekly", "day": 4, "start_h": 11, "start_m": 0, "end_h": 13, "end_m": 0, "loc": "Town Hall"},
            {"frequency": "weekly", "day": 5, "start_h": 10, "start_m": 0, "end_h": 12, "end_m": 0, "loc": "Main Square"},
        ]

        sessions = []
        for sd in sessions_data:
            s = Session.objects.create(
                session_group=sg,
                frequency=sd["frequency"],
                day_of_week=sd["day"],
                start_hour=sd["start_h"],
                start_minute=sd["start_m"],
                end_hour=sd["end_h"],
                end_minute=sd["end_m"],
                location=sd["loc"],
            )
            sessions.append(s)
        self.stdout.write(self.style.SUCCESS(f"Created {len(sessions)} sessions"))

        # Create Participants
        # Availability indices: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat
        participants_data = [
            {"name": "Alice Johnson", "max_w": 3, "max_m": 16, "min_m": 4, "avail": [0, 1, 3, 4]},
            {"name": "Bob Martinez", "max_w": 3, "max_m": 16, "min_m": 4, "avail": [0, 1, 2, 5]},
            {"name": "Clara Rossi", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [2, 3, 4]},
            {"name": "David Chen", "max_w": 4, "max_m": 18, "min_m": 5, "avail": [0, 1, 2, 3]},
            {"name": "Eva Muller", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [1, 3, 5]},
            {"name": "Frank Dubois", "max_w": 3, "max_m": 16, "min_m": 4, "avail": [0, 2, 4, 5]},
            {"name": "Grace Kim", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [1, 2, 3]},
            {"name": "Hassan Ali", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [0, 4, 5]},
            {"name": "Irene Novak", "max_w": 3, "max_m": 12, "min_m": 2, "avail": [2, 3, 5]},
            {"name": "James Wright", "max_w": 4, "max_m": 18, "min_m": 5, "avail": [0, 1, 3, 4]},
            {"name": "Karen White", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [0, 1, 2, 4]},
            {"name": "Leo Fernandez", "max_w": 3, "max_m": 16, "min_m": 4, "avail": [0, 2, 3, 5]},
            {"name": "Maria Santos", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [1, 2, 4, 5]},
            {"name": "Noah Patel", "max_w": 4, "max_m": 18, "min_m": 5, "avail": [0, 1, 2, 3, 4]},
            {"name": "Olivia Brown", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [0, 3, 4, 5]},
            {"name": "Pablo Garcia", "max_w": 3, "max_m": 16, "min_m": 4, "avail": [1, 2, 3, 5]},
            {"name": "Quinn Taylor", "max_w": 3, "max_m": 12, "min_m": 2, "avail": [0, 2, 3, 4]},
            {"name": "Rosa Nguyen", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [1, 3, 4, 5]},
            {"name": "Sam Cooper", "max_w": 3, "max_m": 16, "min_m": 4, "avail": [0, 1, 2, 5]},
            {"name": "Tina Lopez", "max_w": 3, "max_m": 14, "min_m": 3, "avail": [0, 2, 4, 5]},
        ]

        participants = []
        for pd in participants_data:
            avail = [sessions[i].id for i in pd["avail"]]
            p = Participant.objects.create(
                name=pd["name"],
                session_group=sg,
                max_per_week=pd["max_w"],
                max_per_month=pd["max_m"],
                min_per_month=pd["min_m"],
                availability=avail,
            )
            participants.append(p)
        self.stdout.write(self.style.SUCCESS(f"Created {len(participants)} participants"))

        # Set partner: Frank Dubois -> Alice Johnson
        participants[5].partner = participants[0]
        participants[5].save()
        self.stdout.write(self.style.SUCCESS("Set partner: Frank Dubois -> Alice Johnson"))

        # Create Traits
        t1 = ParticipantTrait.objects.create(
            name="Skip first Monday",
            session_group=sg,
            session=sessions[0],
            positions=[1],
        )
        t1.participants.set([participants[0], participants[3], participants[5]])

        t2 = ParticipantTrait.objects.create(
            name="Skip last Saturday",
            session_group=sg,
            session=sessions[5],
            positions=[-1],
        )
        t2.participants.set([participants[1], participants[4]])
        self.stdout.write(self.style.SUCCESS("Created 2 traits"))

        self.stdout.write(self.style.SUCCESS("Demo data loaded successfully!"))
