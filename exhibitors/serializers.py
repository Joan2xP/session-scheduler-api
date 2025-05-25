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
