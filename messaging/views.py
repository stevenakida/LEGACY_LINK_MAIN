from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer


class ConversationListView(generics.ListAPIView):
    """GET /api/messaging/conversations/ — for the Android app. Starting a
    conversation and posting web-side messages is handled by the
    session-authenticated views in config/views.py instead (same dual-stack
    split used by every other app here)."""
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(participants__user=self.request.user).distinct()

    def get_serializer_context(self):
        return {'request': self.request}


class ConversationMessagesView(generics.ListCreateAPIView):
    """GET/POST /api/messaging/conversations/<id>/messages/ — for the
    Android app to read/send within a conversation it's already a
    participant of."""
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_conversation(self):
        conversation = Conversation.objects.get(pk=self.kwargs['conversation_id'])
        if not conversation.participants.filter(user=self.request.user).exists():
            raise PermissionDenied("You're not a participant in this conversation.")
        return conversation

    def get_queryset(self):
        return Message.objects.filter(conversation=self.get_conversation())

    def perform_create(self, serializer):
        serializer.save(conversation=self.get_conversation(), sender=self.request.user)
