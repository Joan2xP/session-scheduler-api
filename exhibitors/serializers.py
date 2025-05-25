from rest_framework import serializers
from .models import Exhibitor, Participant


class ExhibitorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exhibitor
        fields = "__all__"  # Include all fields in the model


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = "__all__"  # Include all fields in the model

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Convert keys from snake_case to camelCase
        def camelize(s):
            parts = s.split("_")
            return parts[0] + "".join(word.capitalize() for word in parts[1:])

        return {camelize(key): value for key, value in data.items()}
