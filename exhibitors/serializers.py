from rest_framework import serializers
from .models import Exhibitor, Participant
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
        fields = "__all__"  # Include all fields in the model

    def to_internal_value(self, data):
        """Convert camelCase keys to snake_case for internal processing"""
        def camel_to_snake(name):
            return camel_case_to_spaces(name).replace(" ", "_")
        
        # Convert camelCase keys to snake_case
        snake_case_data = {}
        for key, value in data.items():
            snake_key = camel_to_snake(key)
            # Fix the value conversion bug: preserve 0 and other falsy values properly
            snake_case_data[snake_key] = value
        
        return super().to_internal_value(snake_case_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Convert keys from snake_case to camelCase
        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        return {camelize(key): value for key, value in data.items()}
