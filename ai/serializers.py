from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant", "system"])
    content = serializers.CharField(allow_blank=True, required=False, default="")


class ChatRequestSerializer(serializers.Serializer):
    messages = MessageSerializer(many=True)

    def validate_messages(self, value):
        if not value:
            raise serializers.ValidationError("Messages array cannot be empty")
        return value
