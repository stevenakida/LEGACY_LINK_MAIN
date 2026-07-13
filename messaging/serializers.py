from rest_framework import serializers
from accounts.serializers import UserProfileSerializer
from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'body', 'sent_at']
        read_only_fields = ['id', 'sender', 'sent_at']


class ConversationSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'created_at', 'other_user', 'last_message']

    def get_other_user(self, obj):
        request_user = self.context['request'].user
        other = obj.other_participant(request_user)
        return UserProfileSerializer(other).data if other else None

    def get_last_message(self, obj):
        last = obj.messages.order_by('-sent_at').first()
        return MessageSerializer(last).data if last else None
