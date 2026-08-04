import uuid

from django.conf import settings
from django.db import models


class MediaAsset(models.Model):
    """Shared private-media pipeline record (Phase 1 foundation) for both
    message attachments and homepage posts, added in later phases.

    This model intentionally has no FK to Message/Post yet — neither exists
    for attachments today. `is_attached`/`mark_attached()` are the hand-off
    point: whichever app attaches a MediaAsset in a later phase is
    responsible for calling `mark_attached()` (clears `purge_at` so the
    orphan-cleanup command stops treating it as unreferenced) and for
    layering its own authorization (conversation participant / post
    audience) on top of the owner-only check this phase provides. Until
    attached, only the owner may ever see or download a given asset — a
    UUID alone is never sufficient (see media_assets/permissions.py).
    """

    class Category(models.TextChoices):
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'
        DOCUMENT = 'document', 'Document'

    class Status(models.TextChoices):
        INITIALIZED = 'initialized', 'Initialized'
        UPLOADED = 'uploaded', 'Uploaded'
        VALIDATING = 'validating', 'Validating'
        SCANNING = 'scanning', 'Scanning'
        PROCESSING = 'processing', 'Processing'
        READY = 'ready', 'Ready'
        REJECTED = 'rejected', 'Rejected'
        FAILED = 'failed', 'Failed'
        DELETED = 'deleted', 'Deleted'

    # Terminal states from which no further pipeline transition happens.
    TERMINAL_STATUSES = {Status.READY, Status.REJECTED, Status.FAILED, Status.DELETED}

    class ScanStatus(models.TextChoices):
        NOT_REQUIRED = 'not_required', 'Not required'
        PENDING = 'pending', 'Pending'
        SCANNING = 'scanning', 'Scanning'
        CLEAN = 'clean', 'Clean'
        INFECTED = 'infected', 'Infected'
        ERROR = 'error', 'Error'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='media_assets'
    )
    category = models.CharField(max_length=10, choices=Category.choices)

    # Filenames: `original_filename` is what the client sent, kept only for
    # display/audit — never used to build a storage path. `sanitized_filename`
    # is the stripped, safe-for-display version (see media_assets/utils.py).
    original_filename = models.CharField(max_length=255)
    sanitized_filename = models.CharField(max_length=255)
    declared_mime_type = models.CharField(max_length=100, blank=True)
    detected_mime_type = models.CharField(max_length=100, blank=True)

    declared_size_bytes = models.PositiveBigIntegerField()
    original_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    processed_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)

    # Storage keys are random tokens, independent of this row's own id, and
    # are never serialized to clients — see media_assets/serializers.py.
    quarantine_storage_key = models.CharField(max_length=512, unique=True)
    storage_key = models.CharField(max_length=512, null=True, blank=True, unique=True)
    thumbnail_storage_key = models.CharField(max_length=512, null=True, blank=True, unique=True)

    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INITIALIZED)
    scan_status = models.CharField(max_length=20, choices=ScanStatus.choices, default=ScanStatus.NOT_REQUIRED)
    failure_reason = models.CharField(max_length=255, blank=True)

    # Admin-initiated hold, independent of the pipeline's own status —
    # e.g. a human review flag on an otherwise READY/CLEAN asset.
    moderation_hold = models.BooleanField(default=False)
    moderation_note = models.TextField(blank=True)

    is_attached = models.BooleanField(default=False)

    upload_url_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # When this unattached asset becomes eligible for the cleanup command to
    # purge. Cleared by mark_attached() once something references it.
    purge_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['purge_at']),
        ]

    def __str__(self):
        return f"{self.get_category_display()} [{self.status}] — {self.owner.full_name}"

    def mark_attached(self):
        self.is_attached = True
        self.purge_at = None
        self.save(update_fields=['is_attached', 'purge_at'])

    @property
    def is_downloadable(self):
        """READY is necessary but not sufficient: documents must also have
        cleared AV scanning, and nothing under moderation hold is servable."""
        if self.moderation_hold or self.deleted_at is not None:
            return False
        if self.status != self.Status.READY:
            return False
        if self.category == self.Category.DOCUMENT:
            return self.scan_status == self.ScanStatus.CLEAN
        return True
