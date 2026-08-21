import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class ModerationHold(models.Model):
    """Phase 4 Step 3: generalizes the "content invisible until a human
    clears it" pattern first built as Post.approval_status (Public-audience
    posts only) into a reusable primitive any content type can point at, so
    Phase 4 Step 4 (report post / report media) has somewhere to land
    instead of inventing its own bespoke status field per content type.

    Deliberately NOT a replacement for the fast, indexed, heavily-tested
    per-object status fields that already exist (Post.approval_status,
    MediaAsset.moderation_hold) — those stay as the cheap read path that
    visibility/authorization checks filter on directly, and are unaffected
    by this model's presence. A ModerationHold row is the generic *record of
    why* a hold exists (opened for public-audience review vs. opened because
    of a user report) and who resolved it and when; callers that manage a
    hold are responsible for keeping the target's own fast-path field in
    sync via open_or_reopen()/resolve() — see posts/views.py:create_post and
    posts/admin.py:approve_posts/reject_posts for the first wiring.

    One row per (content_type, object_id) — reopening an already-resolved
    hold (e.g. an approved Public post gets reported) updates the existing
    row in place rather than appending a new one, since only "is this
    currently held, and why" is ever queried, not a full history log."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    class Reason(models.TextChoices):
        PUBLIC_AUDIENCE_REVIEW = 'public_audience_review', 'Public audience review'
        USER_REPORT = 'user_report', 'User report'  # first used by Phase 4 Step 4

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    target = GenericForeignKey('content_type', 'object_id')

    reason = models.CharField(max_length=30, choices=Reason.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        unique_together = ('content_type', 'object_id')
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return f"{self.reason} hold on {self.content_type.model} {self.object_id} ({self.status})"

    @classmethod
    def open_or_reopen(cls, target, reason):
        """Create a PENDING hold on `target`, or reset an existing hold back
        to PENDING under the new `reason` if one already exists (e.g. an
        approved post gets reported). Always returns the (single) hold row
        for this target."""
        content_type = ContentType.objects.get_for_model(target)
        hold, _ = cls.objects.update_or_create(
            content_type=content_type, object_id=target.pk,
            defaults={'reason': reason, 'status': cls.Status.PENDING, 'resolved_at': None, 'resolved_by': None},
        )
        return hold

    def resolve(self, status, by=None):
        """Mark this hold APPROVED/REJECTED. Callers are responsible for
        also updating the target's own fast-path status field to match —
        this method only manages the ModerationHold row itself."""
        self.status = status
        self.resolved_at = timezone.now()
        self.resolved_by = by
        self.save(update_fields=['status', 'resolved_at', 'resolved_by'])
