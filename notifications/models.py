import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class DeviceToken(models.Model):
    """An FCM registration token for one installed copy of the Android app.
    `token` is globally unique rather than unique-per-user: the Android app
    re-sends its current token on every page load, so if a device gets
    logged out and a different user logs in on it, the same token simply
    gets reassigned via update_or_create — the previous user stops
    receiving pushes to that device without needing an explicit unregister
    call."""

    PLATFORM_CHOICES = [
        ('android', 'Android'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='device_tokens'
    )
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='android')
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} ({self.platform})"


class Notification(models.Model):
    """Phase 4B: an in-app notification record, distinct from the push
    itself — notifications.services.notify() creates one of these AND
    fires a push via send_push_to_user() in the same call, but this row
    is what the /notifications/ feed and the topnav bell badge read from.
    Uses the same GenericForeignKey shape as moderation.ModerationHold /
    moderation.ContentReport so it can point at whatever triggered it
    (a Connection, a Post, a Message) without a bespoke FK per verb.

    Deliberately has no stored display string: this app's UI is bilingual
    (EN/SW via {% trans %}/{% blocktrans %} throughout), so the
    human-readable text is rendered per-verb in templates/notifications.html
    from `actor` + `verb`, not baked into the DB row in one language."""

    class Verb(models.TextChoices):
        CONNECTION_REQUEST = 'connection_request', 'Connection request received'
        CONNECTION_ACCEPTED = 'connection_accepted', 'Connection request accepted'
        POST_APPROVED = 'post_approved', 'Post approved'
        POST_REJECTED = 'post_rejected', 'Post rejected'
        NEW_MESSAGE = 'new_message', 'New message'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    # Who caused it. Null for the rare admin-action-with-no-request case
    # (posts.admin.approve_posts/reject_posts already support request=None
    # for existing tests) — SET_NULL rather than CASCADE so a deleted
    # actor doesn't wipe out the recipient's notification history.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    verb = models.CharField(max_length=30, choices=Verb.choices)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    object_id = models.UUIDField(null=True, blank=True)
    target = GenericForeignKey('content_type', 'object_id')

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'read_at']),
        ]

    def __str__(self):
        return f"{self.get_verb_display()} for {self.recipient.full_name}"
