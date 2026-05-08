from rest_framework import serializers
from .models import Exhibitor, Participant, SessionGroup, Session, ParticipantTrait
from django.utils.text import camel_case_to_spaces


class ParticipantTraitSerializer(serializers.ModelSerializer):
    participant_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Participant.objects.all(),
        source="participants",
        required=False,
    )

    class Meta:
        model = ParticipantTrait
        fields = ["id", "name", "session_group", "session", "positions", "participant_ids", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "session_group": {"required": True},
            "session": {"required": True},
            "positions": {"required": True},
        }

    def to_internal_value(self, data):
        def camel_to_snake(name):
            return camel_case_to_spaces(name).replace(" ", "_")

        snake_case_data = {}
        field_mapping = {
            "sessionGroupId": "session_group",
            "participantIds": "participant_ids",
        }

        for key, value in data.items():
            if key in field_mapping:
                snake_key = field_mapping[key]
            else:
                snake_key = camel_to_snake(key)
            snake_case_data[snake_key] = value

        return super().to_internal_value(snake_case_data)

    def validate(self, attrs):
        session = attrs.get("session")
        session_group = attrs.get("session_group")
        if session and session_group and session.session_group_id != session_group.id:
            raise serializers.ValidationError(
                {"session": "Session must belong to the same session group"}
            )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)

        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        result = {}
        for key, value in data.items():
            if key == "session_group":
                result["sessionGroupId"] = value
            elif key == "session":
                result["session"] = value
            elif key == "participant_ids":
                result["participantIds"] = value
            elif key == "created_at":
                result["createdAt"] = value
            elif key == "updated_at":
                result["updatedAt"] = value
            else:
                result[camelize(key)] = value
        return result


class ExhibitorSerializer(serializers.ModelSerializer):
    session_group = serializers.PrimaryKeyRelatedField(
        queryset=SessionGroup.objects.all(), required=False
    )

    class Meta:
        model = Exhibitor
        fields = [
            "year",
            "month",
            "session_group",
            "schedule_data",
            "schedule_statistics",
            "days_with_details",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Convert keys from snake_case to camelCase
        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        return {camelize(key): value for key, value in data.items()}


class ParticipantSerializer(serializers.ModelSerializer):
    traits = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ParticipantTrait.objects.all(),
        required=False,
    )

    class Meta:
        model = Participant
        fields = "__all__"
        extra_kwargs = {
            "session_group": {
                "required": False
            },  # Will be set to required only on create
            "partner": {"required": False, "allow_null": True},
            "exclude_ids": {"required": False, "allow_null": True},
            "availability": {"required": False, "allow_null": True},
            "only_session_occurrences": {"required": False, "allow_null": True},
            "exclude_session_occurrences": {"required": False, "allow_null": True},
            "min_sessions_together": {"required": False, "allow_null": True},
            "enforced_week_days": {"required": False, "allow_null": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make session_group required only on create (when instance is None)
        if self.instance is None:
            self.fields["session_group"].required = True
        else:
            self.fields["session_group"].required = False

        # Explicitly set nullable JSON fields to allow null and not require them
        nullable_json_fields = [
            "exclude_ids",
            "availability",
            "only_session_occurrences",
            "exclude_session_occurrences",
            "min_sessions_together",
            "enforced_week_days",
        ]
        for field_name in nullable_json_fields:
            if field_name in self.fields:
                field = self.fields[field_name]
                field.required = False
                field.allow_null = True
                # Remove any blank validation
                if hasattr(field, "allow_blank"):
                    field.allow_blank = True

    def to_internal_value(self, data):
        """Convert camelCase keys to snake_case for internal processing"""

        def camel_to_snake(name):
            return camel_case_to_spaces(name).replace(" ", "_")

        # Convert camelCase keys to snake_case
        snake_case_data = {}

        # Handle special field mappings
        field_mapping = {
            "sessionGroupId": "session_group",
            "partnerId": "partner",
            "excludeIds": "exclude_ids",
            "onlySessionOccurrences": "only_session_occurrences",
            "excludeSessionOccurrences": "exclude_session_occurrences",
            "minSessionsTogether": "min_sessions_together",
            "maxPerWeek": "max_per_week",
            "maxPerMonth": "max_per_month",
            "minPerMonth": "min_per_month",
            "enforcedWeekDays": "enforced_week_days",
            "traitIds": "traits",
        }

        for key, value in data.items():
            # Check if it's a mapped field
            if key in field_mapping:
                snake_key = field_mapping[key]
            else:
                snake_key = camel_to_snake(key)

            # Handle sessionGroupId - keep as integer ID, DRF will convert to ForeignKey
            if snake_key == "session_group" and isinstance(value, int):
                # Just pass the integer ID - DRF's ForeignKey field will handle the conversion
                snake_case_data["session_group"] = value
                continue

            # Handle partnerId - keep as integer ID or None, DRF will convert to ForeignKey
            if snake_key == "partner":
                # Just pass the value (integer ID or None) - DRF's ForeignKey field will handle the conversion
                snake_case_data["partner"] = value
                continue

            # Handle null/empty values for nullable JSON fields - set to None explicitly
            nullable_json_fields = [
                "exclude_ids",
                "availability",
                "only_session_occurrences",
                "exclude_session_occurrences",
                "min_sessions_together",
                "enforced_week_days",
            ]
            if snake_key in nullable_json_fields:
                # Convert None, empty string, or empty list to None
                if value is None or value == "" or value == []:
                    snake_case_data[snake_key] = None
                else:
                    snake_case_data[snake_key] = value
                continue

            # Handle null/empty for M2M traits field
            if snake_key == "traits":
                if value is None or value == "" or value == []:
                    snake_case_data[snake_key] = []
                else:
                    snake_case_data[snake_key] = value
                continue

            # Handle nested camelCase in JSON structures (keep camelCase in JSON)
            if snake_key == "only_session_occurrences" and isinstance(value, list):
                # Keep camelCase keys in occurrence objects (sessionId, date)
                snake_case_data[snake_key] = value
            elif snake_key == "exclude_session_occurrences" and isinstance(value, list):
                # Keep camelCase keys in occurrence objects (sessionId, date)
                snake_case_data[snake_key] = value
            elif snake_key == "min_sessions_together" and isinstance(value, dict):
                # Keep camelCase keys in min_sessions_together object (sessionId, partnerId, amount)
                snake_case_data[snake_key] = value
            else:
                snake_case_data[snake_key] = value

        validated_data = super().to_internal_value(snake_case_data)

        # Ensure nullable JSON fields are set to None if not provided, null, or empty
        nullable_json_fields = [
            "exclude_ids",
            "availability",
            "only_session_occurrences",
            "exclude_session_occurrences",
            "min_sessions_together",
            "enforced_week_days",
        ]
        for field_name in nullable_json_fields:
            if field_name not in validated_data:
                validated_data[field_name] = None
            elif (
                validated_data.get(field_name) == ""
                or validated_data.get(field_name) == []
            ):
                validated_data[field_name] = None

        return validated_data

    def validate(self, attrs):
        """Validate sessionGroupId immutability and same session group constraints"""
        # Check if this is an update
        if self.instance:
            # If session_group is not provided, use the existing one
            if "session_group" not in attrs:
                attrs["session_group"] = self.instance.session_group
            # Prevent session_group_id changes on update
            elif attrs["session_group"].id != self.instance.session_group_id:
                raise serializers.ValidationError(
                    {
                        "sessionGroupId": "sessionGroupId cannot be changed after creation"
                    }
                )

        # Validate min_sessions_together amount
        if "min_sessions_together" in attrs and attrs["min_sessions_together"]:
            if not isinstance(attrs["min_sessions_together"], dict):
                raise serializers.ValidationError(
                    {"minSessionsTogether": "must be an object"}
                )
            amount = attrs["min_sessions_together"].get("amount")
            if amount is None or not isinstance(amount, int) or amount < 1:
                raise serializers.ValidationError(
                    {"minSessionsTogether": "amount must be >= 1"}
                )

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Convert keys from snake_case to camelCase
        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        # Ensure null values stay as null (not empty strings)
        result = {}
        for key, value in data.items():
            # Handle special field mappings
            if key == "session_group":
                # Convert ForeignKey to ID
                camel_key = "sessionGroupId"
                result[camel_key] = (
                    value if isinstance(value, int) else (value.id if value else None)
                )
            elif key == "partner":
                # Convert ForeignKey to ID
                camel_key = "partnerId"
                result[camel_key] = (
                    value if isinstance(value, int) else (value.id if value else None)
                )
            elif key == "exclude_ids":
                camel_key = "excludeIds"
                result[camel_key] = value
            elif key == "only_session_occurrences":
                camel_key = "onlySessionOccurrences"
                # Keep camelCase keys in JSON (sessionId, date)
                result[camel_key] = value
            elif key == "exclude_session_occurrences":
                camel_key = "excludeSessionOccurrences"
                # Keep camelCase keys in JSON (sessionId, date)
                result[camel_key] = value
            elif key == "min_sessions_together":
                camel_key = "minSessionsTogether"
                # Keep camelCase keys in JSON (sessionId, partnerId, amount)
                result[camel_key] = value
            elif key == "max_per_week":
                camel_key = "maxPerWeek"
                result[camel_key] = value
            elif key == "max_per_month":
                camel_key = "maxPerMonth"
                result[camel_key] = value
            elif key == "min_per_month":
                camel_key = "minPerMonth"
                result[camel_key] = value
            elif key == "enforced_week_days":
                camel_key = "enforcedWeekDays"
                result[camel_key] = value
            elif key == "traits":
                camel_key = "traitIds"
                result[camel_key] = value
            else:
                camel_key = camelize(key)
                # Keep null values as null, not convert to empty string
                result[camel_key] = value

        return result


class SessionSerializer(serializers.ModelSerializer):
    sessionGroupId = serializers.IntegerField(source="session_group_id", read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            "id",
            "sessionGroupId",
            "name",
            "frequency",
            "start_hour",
            "start_minute",
            "end_hour",
            "end_minute",
            "week",
            "day_of_week",
            "month",
            "location",
        ]
        extra_kwargs = {
            "week": {"required": False, "allow_null": True},
            "day_of_week": {"required": False, "allow_null": True},
            "month": {"required": False, "allow_null": True},
            "location": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def to_internal_value(self, data):
        """Convert camelCase keys to snake_case for internal processing"""

        def camel_to_snake(name):
            return camel_case_to_spaces(name).replace(" ", "_")

        # Convert camelCase keys to snake_case
        snake_case_data = {}
        nullable_string_fields = ["location"]

        for key, value in data.items():
            snake_key = camel_to_snake(key)
            # Handle sessionGroupId -> session_group
            if snake_key == "session_group_id":
                snake_key = "session_group"
            # Convert empty strings to None for nullable string fields
            if snake_key in nullable_string_fields and value == "":
                snake_case_data[snake_key] = None
            else:
                snake_case_data[snake_key] = value

        return super().to_internal_value(snake_case_data)

    def get_name(self, obj):
        """Generate session code: frequency-day-time"""
        # Frequency codes
        freq_map = {
            "daily": "D",
            "weekly": "W",
            "monthly": "M",
            "yearly": "Y",
        }

        # Day of week codes
        day_map = {
            0: "mo",
            1: "tu",
            2: "we",
            3: "th",
            4: "fr",
            5: "sa",
            6: "su",
        }

        freq_code = freq_map.get(obj.frequency, "")
        time_str = f"{obj.start_hour:02d}:{obj.start_minute:02d}"

        parts = [freq_code]

        # Add day if present
        if obj.day_of_week is not None:
            day_code = day_map.get(obj.day_of_week, "")
            parts.append(f"{day_code}")

        # Add week if present (for monthly/yearly)
        if obj.week is not None:
            parts.append(f"w{obj.week}")

        # Add month if present (for yearly)
        if obj.month is not None:
            parts.append(f"m{obj.month}")

        # Add time
        parts.append(time_str)

        return "".join(parts)

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Convert keys from snake_case to camelCase
        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        result = {}
        for key, value in data.items():
            if key == "day_of_week":
                camel_key = "dayOfWeek"
            elif key == "start_hour":
                camel_key = "startHour"
            elif key == "start_minute":
                camel_key = "startMinute"
            elif key == "end_hour":
                camel_key = "endHour"
            elif key == "end_minute":
                camel_key = "endMinute"
            else:
                camel_key = camelize(key)
            result[camel_key] = value

        return result


class SessionGroupSerializer(serializers.ModelSerializer):
    sessions = SessionSerializer(many=True, read_only=True)

    class Meta:
        model = SessionGroup
        fields = ["id", "name", "sessions"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Data is already in camelCase from nested SessionSerializer
        return data

    def to_internal_value(self, data):
        """Handle nested sessions if provided"""
        # Create a copy to avoid mutating the original data
        data_copy = data.copy() if hasattr(data, "copy") else dict(data)
        sessions_data = data_copy.pop("sessions", None)
        validated_data = super().to_internal_value(data_copy)
        validated_data["sessions_data"] = sessions_data
        return validated_data
