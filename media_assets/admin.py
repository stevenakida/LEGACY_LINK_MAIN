from django.contrib import admin

from .models import MediaAsset


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

    def has_add_permission(self, request):
        return False  # media assets are only ever created through the upload pipeline
