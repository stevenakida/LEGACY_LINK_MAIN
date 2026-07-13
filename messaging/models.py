import uuid
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """A conversation with members — built this way (not a flat sender/
    recipient pair) so a future cohort group chat is the same object as a
    1:1 thread, per the messaging build spec. Only `type='direct'` is
    actually used today; creation is gated in the view layer
    (config/views.py::messages_start) on an accepted Connection existing
    between the two users — not enforced here, since 'accepted Connection'
    is a connections-app concept, not something this model should import."""

    class ConversationType(models.TextChoices):
        DIRECT = 'direct', 'Direct'
        GROUP = 'group', 'Group'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=10, choices=ConversationType.choices, default=ConversationType.DIRECT)
    # Direct only: canonical "minUserId:maxUserId" key so a pair can only
    # ever have one direct conversation, enforced at the DB level (not just
    # by a lookup-then-create in the view, which had a race-condition risk
    # under simultaneous requests). Null for group conversations.
    direct_key = models.CharField(max_length=80, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def other_participant(self, user):
        participant = self.participants.exclude(user=user).select_related('user').first()
        return participant.user if participant else None

    @staticmethod
    def direct_key_for(user_a, user_b):
        ids = sorted([str(user_a.id), str(user_b.id)])
        return f"{ids[0]}:{ids[1]}"


class ConversationMember(models.Model):
    class Role(models.TextChoices):
        MEMBER = 'member', 'Member'
        ADMIN = 'admin', 'Admin'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversation_memberships')
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    # Drives unread badges: unread = messages sent after this, excluding the
    # member's own. Replaces the old per-message `read_at` — one column per
    # membership instead of a write per message on every thread visit.
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('conversation', 'user')


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    body = models.TextField(max_length=4000)
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Soft delete so moderation actions are auditable — render as "message
    # removed" rather than losing the row.
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['sent_at']
        indexes = [models.Index(fields=['conversation', '-sent_at'])]

    def __str__(self):
        return f"{self.sender.full_name}: {self.body[:40]}"
