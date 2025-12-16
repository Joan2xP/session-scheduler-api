from rest_framework import serializers
from .models import Exhibitor, Participant, SessionGroup, Session
from django.utils.text import camel_case_to_spaces


class ExhibitorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exhibitor
        fields = [
            "year",
            "month",
            "schedule_data",
            "schedule_statistics",
            "days_with_details",
        ]  # Include all fields in the model

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Convert keys from snake_case to camelCase
        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        return {camelize(key): value for key, value in data.items()}


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = "__all__"
        extra_kwargs = {
            # Allow blank strings for nullable CharField fields
            "partner": {"allow_blank": True, "required": False},
        }

    def to_internal_value(self, data):
        """Convert camelCase keys to snake_case for internal processing"""

        def camel_to_snake(name):
            return camel_case_to_spaces(name).replace(" ", "_")

        # Convert camelCase keys to snake_case
        snake_case_data = {}
        nullable_string_fields = [
            "partner"
        ]  # Add other nullable string fields here if needed

        for key, value in data.items():
            snake_key = camel_to_snake(key)
            # Convert empty strings to None for nullable string fields
            if snake_key in nullable_string_fields and value == "":
                snake_case_data[snake_key] = None
            else:
                snake_case_data[snake_key] = value

        return super().to_internal_value(snake_case_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Convert keys from snake_case to camelCase
        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        # Ensure null values stay as null (not empty strings)
        result = {}
        for key, value in data.items():
            camel_key = camelize(key)
            # Keep null values as null, not convert to empty string
            result[camel_key] = value

        return result


class SessionSerializer(serializers.ModelSerializer):
    sessionGroupId = serializers.IntegerField(source="session_group_id", read_only=True)

    class Meta:
        model = Session
        fields = [
            "id",
            "sessionGroupId",
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
