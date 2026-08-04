from rest_framework import serializers

from .models import MediaAsset


class InitiateUploadSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=MediaAsset.Category.choices)
    filename = serializers.CharField(max_length=255)
    declared_mime_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    declared_size_bytes = serializers.IntegerField(min_value=1)


class MediaAssetSerializer(serializers.ModelSerializer):
    """Never exposes quarantine_storage_key/storage_key/thumbnail_storage_key
    — those are internal object-storage paths, not client-facing (per the
    "do not expose raw object-storage keys" requirement). Clients get URLs
    from the preview/download endpoints instead, only once authorized."""

    class Meta:
        model = MediaAsset
        fields = [
            'id', 'category', 'original_filename', 'sanitized_filename',
            'detected_mime_type', 'declared_size_bytes', 'original_size_bytes',
            'processed_size_bytes', 'width', 'height', 'duration_seconds',
            'status', 'scan_status', 'failure_reason', 'moderation_hold',
            'created_at', 'ready_at',
        ]
        read_only_fields = fields
