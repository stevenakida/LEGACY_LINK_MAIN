import uuid
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
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
    # blank=True: a message can be image-only (see MessageAttachment) — the
    # "text or attachment" requirement is enforced in config.views.messages_send,
    # not here, same split posts.models.Post uses for body/media_asset.
    body = models.TextField(max_length=4000, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Soft delete so moderation actions are auditable — render as "message
    # removed" rather than losing the row.
    is_deleted = models.BooleanField(default=False)
    # Quoted reply — must belong to the same conversation, enforced in
    # config.views.messages_send, not here (same split as everything else
    # authorization-shaped in this app).
    reply_to = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies'
    )
    # Set when this message was created by config.views.messages_forward
    # from another message — drives the "Forwarded" label. Points at the
    # original message forwarded from, not a chain (forwarding a forward
    # still points at the immediate source, matching WhatsApp's own
    # behavior of not chaining "forwarded from a forward" labels).
    forwarded_from = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='forwards'
    )

    class Meta:
        ordering = ['sent_at']
        indexes = [models.Index(fields=['conversation', '-sent_at'])]

    def __str__(self):
        return f"{self.sender.full_name}: {self.body[:40]}"

    @property
    def has_attachment(self):
        """Safe to call even when `attachment` wasn't select_related — just
        costs a query in that case, same tradeoff as any reverse OneToOne
        access."""
        try:
            return self.attachment is not None
        except ObjectDoesNotExist:
            return False


class MessageAttachment(models.Model):
    """One image per message (pilot constraint), reusing the same private
    media_assets pipeline the posts composer uses. Named/shaped per the
    Phase 0 media/posts audit's plan for Phase 2. Authorization for viewing
    the image lives in config.views.message_attachment_image — "conversation
    participant", the same check messages_thread/poll/earlier already use —
    per MediaAsset's own documented owner-only-until-attached contract."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name='attachment')
    media_asset = models.ForeignKey(
        'media_assets.MediaAsset', on_delete=models.SET_NULL, null=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attachment on message {self.message_id}"


class MessageHiddenFor(models.Model):
    """Per-user 'delete for me' — deliberately separate from
    Message.is_deleted, which is a global moderation flag ("message
    removed" for everyone). Hiding a message here only affects what this
    one user sees; every other participant's view is untouched. Views
    that list messages (messages_thread/poll/earlier, and messages_inbox's
    last-message/unread-count) exclude rows referenced here for the
    requesting user."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='hidden_for')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hidden_messages')
    hidden_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
