import uuid

from django.conf import settings
from django.db import models


class Post(models.Model):
    """Home feed post (Phase 3 of the media/posts initiative). Text + at
    most one image, three audiences per the Phase 0 pilot spec: My
    Connections / School-or-Cohort / Public. Public posts require admin
    approval before anyone but the author can see them — see
    ApprovalStatus and posts.views._visible_posts_queryset, which is the
    single source of truth for "who can see this post" (feed listing and
    the post_image authorization check both go through it, so they can
    never drift apart)."""

    class Audience(models.TextChoices):
        CONNECTIONS = 'connections', 'My Connections'
        COHORT = 'cohort', 'School / Cohort'
        PUBLIC = 'public', 'Public'

    class ApprovalStatus(models.TextChoices):
        NOT_REQUIRED = 'not_required', 'Not required'
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts'
    )
    body = models.TextField(blank=True, max_length=2000)
    media_asset = models.ForeignKey(
        'media_assets.MediaAsset', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )
    audience = models.CharField(
        max_length=20, choices=Audience.choices, default=Audience.CONNECTIONS
    )
    # Only meaningful for audience=PUBLIC (see posts.views.create_post,
    # which sets PENDING there and NOT_REQUIRED for the other two audiences
    # — connections/cohort posts are visible immediately, matching the
    # pilot spec: only Public needs a human review step).
    approval_status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.NOT_REQUIRED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Null until the author actually edits the post — drives the "Edited"
    # label the same way WhatsApp/Facebook only show it once a real edit
    # has happened, not from creation onward.
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['author', '-created_at']),
        ]

    def __str__(self):
        return f"Post by {self.author.full_name} at {self.created_at:%Y-%m-%d %H:%M}"


class PostHiddenFor(models.Model):
    """Per-user 'hide from my feed' — same shape as
    messaging.models.MessageHiddenFor: hiding a post here only affects what
    this one user sees in their own feed; every other viewer (including the
    author) is untouched. posts.views._visible_posts_queryset excludes rows
    referenced here for the requesting viewer, so feed listing and any
    per-post authorization check can't drift apart."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='hidden_for')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hidden_posts')
    hidden_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')
