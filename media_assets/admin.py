from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from moderation.models import ModerationHold

from .models import MediaAsset


def _resolve_holds(queryset, status, resolved_by):
    """Mirrors posts.admin._resolve_holds — keeps moderation.ModerationHold
    in sync with the moderation_hold bulk-update below for assets reported
    via Phase 4 Step 4 (posts.views.report_post_media /
    config.views.report_message_attachment)."""
    content_type = ContentType.objects.get_for_model(MediaAsset)
    ModerationHold.objects.filter(
        content_type=content_type, object_id__in=queryset.values_list('pk', flat=True)
    ).update(status=status, resolved_at=timezone.now(), resolved_by=resolved_by)


@admin.action(description='Clear moderation hold on selected media')
def clear_moderation_hold(modeladmin, request, queryset):
    _resolve_holds(queryset, ModerationHold.Status.APPROVED, request.user if request else None)
    queryset.update(moderation_hold=False)


@admin.action(description='Confirm moderation hold on selected media (keeps it hidden)')
def confirm_moderation_hold(modeladmin, request, queryset):
    _resolve_holds(queryset, ModerationHold.Status.REJECTED, request.user if request else None)
    queryset.update(moderation_hold=True)


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'category', 'owner', 'status', 'scan_status', 'moderation_hold',
        'is_attached', 'created_at', 'ready_at',
    )
    list_filter = ('category', 'status', 'scan_status', 'moderation_hold', 'is_attached')
    search_fields = ('owner__full_name', 'original_filename', 'id')
    autocomplete_fields = ('owner',)
    readonly_fields = (
        'id', 'quarantine_storage_key', 'storage_key', 'thumbnail_storage_key',
        'checksum_sha256', 'created_at', 'ready_at', 'deleted_at',
    )
    fieldsets = (
        (None, {'fields': ('id', 'owner', 'category', 'original_filename', 'sanitized_filename')}),
        ('Pipeline state', {'fields': ('status', 'scan_status', 'failure_reason')}),
        ('Moderation', {'fields': ('moderation_hold', 'moderation_note')}),
        ('File metadata', {'fields': (
            'detected_mime_type', 'declared_size_bytes', 'original_size_bytes',
            'processed_size_bytes', 'width', 'height', 'duration_seconds', 'checksum_sha256',
        )}),
        ('Storage', {'fields': ('quarantine_storage_key', 'storage_key', 'thumbnail_storage_key')}),
        ('Lifecycle', {'fields': ('is_attached', 'upload_url_expires_at', 'created_at', 'ready_at', 'deleted_at', 'purge_at')}),
    )
    actions = [clear_moderation_hold, confirm_moderation_hold]

    def has_add_permission(self, request):
        return False  # media assets are only ever created through the upload pipeline
