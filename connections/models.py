from django.db import models
from django.conf import settings
import uuid


class Connection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_connections'
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_connections'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('requester', 'receiver')  # No duplicate requests
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requester.full_name} → {self.receiver.full_name} ({self.status})"

    @classmethod
    def accepted_between(cls, user):
        """All accepted Connection rows involving `user`, in either
        direction. Centralizes the (Q(requester=user) | Q(receiver=user)) &
        Q(status='accepted') shape that was previously duplicated ad hoc
        across views (dashboard, posts feed, etc.) — flagged in the Phase 0
        media/posts audit as a prerequisite refactor for anything that needs
        to reason about "who is user connected to" (like Home feed
        visibility). Only new call sites (posts app) adopt this so far;
        existing duplicated queries elsewhere are left as-is to avoid
        touching unrelated, already-working connection code."""
        return cls.objects.filter(
            (models.Q(requester=user) | models.Q(receiver=user)) & models.Q(status='accepted')
        )


class UserRelationshipOverride(models.Model):
    """Phase 4 Step 2 trust primitive: Block and Mute share this one table
    (a directional override one user places on another) rather than two
    separate models, since they're structurally identical even though their
    effects differ — Block is enforced as authorization (excluded from
    posts._visible_posts_queryset so it also blocks post_image access, any
    existing Connection between the two is severed, new messages are
    rejected), while Mute is purely a feed display preference (excluded
    only from posts.get_feed_for_user, invisible to the muted user, no
    other effect — same "declutter, not access control" shape as
    posts.PostHiddenFor/messaging.MessageHiddenFor)."""

    class Type(models.TextChoices):
        BLOCK = 'block', 'Block'
        MUTE = 'mute', 'Mute'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='relationship_overrides_made'
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='relationship_overrides_received'
    )
    type = models.CharField(max_length=10, choices=Type.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('actor', 'target', 'type')

    def __str__(self):
        return f"{self.actor.full_name} {self.type} {self.target.full_name}"

    @classmethod
    def is_blocked(cls, user_a, user_b):
        """True if either side has blocked the other. Block's effects are
        symmetric (neither can see/message/connect with the other) even
        though only one row is stored, naming who initiated it."""
        return cls.objects.filter(type=cls.Type.BLOCK).filter(
            models.Q(actor=user_a, target=user_b) | models.Q(actor=user_b, target=user_a)
        ).exists()

    @classmethod
    def blocked_partner_ids(cls, user):
        """IDs of everyone `user` is blocked with, in either direction —
        used to exclude their content/requests regardless of who blocked
        whom."""
        pairs = cls.objects.filter(type=cls.Type.BLOCK).filter(
            models.Q(actor=user) | models.Q(target=user)
        ).values_list('actor_id', 'target_id')
        return {uid for pair in pairs for uid in pair if uid != user.id}

    @classmethod
    def muted_author_ids(cls, user):
        """IDs of users `user` has muted. One-directional — the muted user
        is never notified and is otherwise unaffected."""
        return set(cls.objects.filter(actor=user, type=cls.Type.MUTE).values_list('target_id', flat=True))
