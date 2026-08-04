"""Orchestrates the upload/validate/scan/process pipeline. Kept synchronous
(no task queue) per the Phase 0 decision — pilot file sizes make this fast
enough to run inline in the complete-upload request; see docs on
MediaAsset.Status for the state machine this walks through."""
import hashlib
import logging
import os
import shutil
import tempfile
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import utils
from .exceptions import MediaValidationError
from .models import MediaAsset
from .scanning import get_scanner
from .storage import ObjectNotFound, get_media_backend
from .validation import validate_and_process_image, validate_document, validate_video

logger = logging.getLogger(__name__)

CATEGORY_MAX_BYTES = {
    MediaAsset.Category.IMAGE: lambda: settings.MEDIA_ASSETS_IMAGE_MAX_BYTES,
    MediaAsset.Category.VIDEO: lambda: settings.MEDIA_ASSETS_VIDEO_MAX_BYTES,
    MediaAsset.Category.DOCUMENT: lambda: settings.MEDIA_ASSETS_DOCUMENT_MAX_BYTES,
}


class MediaFeatureDisabled(Exception):
    pass


def _category_enabled(category: str) -> bool:
    if not settings.FEATURE_MEDIA_UPLOADS_ENABLED:
        return False
    if category == MediaAsset.Category.VIDEO and not settings.FEATURE_VIDEO_MEDIA_ENABLED:
        return False
    if category == MediaAsset.Category.DOCUMENT and not settings.FEATURE_DOCUMENT_MEDIA_ENABLED:
        return False
    return True


def initiate_upload(user, category: str, filename: str, declared_mime_type: str, declared_size_bytes: int):
    if category not in MediaAsset.Category.values:
        raise MediaValidationError('unsupported media category')
    if not _category_enabled(category):
        raise MediaFeatureDisabled(f'{category} uploads are not currently enabled')

    max_bytes = CATEGORY_MAX_BYTES[category]()
    if not declared_size_bytes or declared_size_bytes <= 0 or declared_size_bytes > max_bytes:
        raise MediaValidationError(f'declared size exceeds the {max_bytes}-byte limit for {category}')

    if utils.filename_has_blocked_extension(filename or ''):
        raise MediaValidationError('file type not allowed')

    backend = get_media_backend()
    quarantine_key = utils.new_storage_key(settings.MEDIA_ASSETS_QUARANTINE_PREFIX)
    ttl = settings.MEDIA_ASSETS_UPLOAD_URL_TTL_SECONDS

    asset = MediaAsset.objects.create(
        owner=user,
        category=category,
        original_filename=filename or '',
        sanitized_filename=utils.sanitize_filename(filename or ''),
        declared_mime_type=declared_mime_type or '',
        declared_size_bytes=declared_size_bytes,
        quarantine_storage_key=quarantine_key,
        upload_url_expires_at=timezone.now() + timedelta(seconds=ttl),
        purge_at=timezone.now() + timedelta(hours=settings.MEDIA_ASSETS_RETENTION_HOURS),
        scan_status=(
            MediaAsset.ScanStatus.PENDING if category == MediaAsset.Category.DOCUMENT
            else MediaAsset.ScanStatus.NOT_REQUIRED
        ),
    )
    upload_url = backend.generate_upload_url(quarantine_key, declared_mime_type or 'application/octet-stream', ttl)
    return asset, upload_url


def _cleanup_tmp(tmp_dir: str) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _sha256_of_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(asset: MediaAsset, status: str, reason: str, extra_fields=None) -> MediaAsset:
    asset.status = status
    asset.failure_reason = reason
    fields = {'status', 'failure_reason', 'checksum_sha256', 'original_size_bytes', 'detected_mime_type'}
    if extra_fields:
        fields.update(extra_fields)
    asset.save(update_fields=list(fields))
    return asset


def complete_upload(media_asset_id) -> MediaAsset:
    with transaction.atomic():
        asset = MediaAsset.objects.select_for_update().get(pk=media_asset_id)
        if asset.status not in (MediaAsset.Status.INITIALIZED, MediaAsset.Status.UPLOADED):
            return asset  # already processed or in flight — idempotent no-op
        asset.status = MediaAsset.Status.VALIDATING
        asset.save(update_fields=['status'])

    backend = get_media_backend()
    max_bytes = CATEGORY_MAX_BYTES[asset.category]()

    meta = backend.head_object(asset.quarantine_storage_key)
    if meta is None:
        return _fail(asset, MediaAsset.Status.FAILED, 'uploaded object not found in storage')

    if meta.size > max_bytes:
        backend.delete_object(asset.quarantine_storage_key)
        return _fail(asset, MediaAsset.Status.REJECTED, 'uploaded file exceeds the allowed size')

    asset.original_size_bytes = meta.size

    tmp_dir = tempfile.mkdtemp(prefix='media_asset_')
    tmp_in = os.path.join(tmp_dir, 'input')
    try:
        backend.download_to_path(asset.quarantine_storage_key, tmp_in)
    except ObjectNotFound:
        _cleanup_tmp(tmp_dir)
        return _fail(asset, MediaAsset.Status.FAILED, 'uploaded object not found in storage')
    except Exception:
        logger.exception('media_assets: failed to download quarantine object for %s', asset.id)
        _cleanup_tmp(tmp_dir)
        return _fail(asset, MediaAsset.Status.FAILED, 'storage error while retrieving upload')

    asset.checksum_sha256 = _sha256_of_file(tmp_in)
    final_thumb_path = None

    try:
        if asset.category == MediaAsset.Category.IMAGE:
            asset.status = MediaAsset.Status.PROCESSING
            processed_path = os.path.join(tmp_dir, 'processed')
            thumb_path = os.path.join(tmp_dir, 'thumb.jpg')
            result = validate_and_process_image(tmp_in, processed_path, thumb_path)
            asset.detected_mime_type = result.mime_type
            asset.width, asset.height = result.width, result.height
            final_local_path, final_thumb_path = result.processed_path, result.thumbnail_path

        elif asset.category == MediaAsset.Category.DOCUMENT:
            result = validate_document(tmp_in)
            asset.detected_mime_type = result.mime_type
            asset.status = MediaAsset.Status.SCANNING
            asset.scan_status = MediaAsset.ScanStatus.SCANNING
            asset.save(update_fields=[
                'status', 'scan_status', 'detected_mime_type', 'checksum_sha256', 'original_size_bytes',
            ])
            outcome = get_scanner().scan_file(tmp_in)
            asset.scan_status = outcome.status
            if outcome.status == MediaAsset.ScanStatus.INFECTED:
                backend.delete_object(asset.quarantine_storage_key)
                _cleanup_tmp(tmp_dir)
                return _fail(asset, MediaAsset.Status.REJECTED, 'file failed antivirus scanning', {'scan_status'})
            if outcome.status != MediaAsset.ScanStatus.CLEAN:
                _cleanup_tmp(tmp_dir)
                return _fail(
                    asset, MediaAsset.Status.FAILED,
                    outcome.reason or 'antivirus scanning unavailable', {'scan_status'},
                )
            final_local_path = tmp_in

        elif asset.category == MediaAsset.Category.VIDEO:
            asset.status = MediaAsset.Status.PROCESSING
            thumb_path = os.path.join(tmp_dir, 'thumb.jpg')
            result = validate_video(tmp_in, thumb_path)
            asset.detected_mime_type = result.mime_type
            asset.duration_seconds = result.duration_seconds
            final_local_path = tmp_in
            final_thumb_path = result.thumbnail_path

        else:
            _cleanup_tmp(tmp_dir)
            return _fail(asset, MediaAsset.Status.FAILED, 'unsupported media category')

    except MediaValidationError as e:
        backend.delete_object(asset.quarantine_storage_key)
        _cleanup_tmp(tmp_dir)
        return _fail(asset, MediaAsset.Status.REJECTED, e.reason)
    except Exception:
        logger.exception('media_assets: processing failed for %s', asset.id)
        _cleanup_tmp(tmp_dir)
        return _fail(asset, MediaAsset.Status.FAILED, 'processing failed unexpectedly')

    ext = utils.ready_extension_for_mime(asset.detected_mime_type)
    if not ext:
        backend.delete_object(asset.quarantine_storage_key)
        _cleanup_tmp(tmp_dir)
        return _fail(asset, MediaAsset.Status.REJECTED, 'detected file type is not supported')

    processed_size = os.path.getsize(final_local_path)
    ready_key = utils.new_storage_key(settings.MEDIA_ASSETS_READY_PREFIX, ext)
    thumb_key = None
    try:
        backend.upload_from_path(final_local_path, ready_key, asset.detected_mime_type)
        if final_thumb_path:
            thumb_key = utils.new_storage_key(settings.MEDIA_ASSETS_THUMBNAIL_PREFIX, 'jpg')
            backend.upload_from_path(final_thumb_path, thumb_key, 'image/jpeg')
    except Exception:
        logger.exception('media_assets: failed to store processed file for %s', asset.id)
        _cleanup_tmp(tmp_dir)
        return _fail(asset, MediaAsset.Status.FAILED, 'storage error while saving processed file')

    backend.delete_object(asset.quarantine_storage_key)
    _cleanup_tmp(tmp_dir)

    asset.storage_key = ready_key
    asset.thumbnail_storage_key = thumb_key
    asset.processed_size_bytes = processed_size
    asset.status = MediaAsset.Status.READY
    asset.ready_at = timezone.now()
    asset.failure_reason = ''
    asset.save()
    return asset


def purge_storage_and_mark_deleted(asset: MediaAsset) -> MediaAsset:
    backend = get_media_backend()
    for key in (asset.quarantine_storage_key, asset.storage_key, asset.thumbnail_storage_key):
        if key:
            try:
                backend.delete_object(key)
            except Exception:
                logger.exception('media_assets: failed to delete object %s for asset %s', key, asset.id)
    asset.status = MediaAsset.Status.DELETED
    asset.deleted_at = timezone.now()
    asset.save(update_fields=['status', 'deleted_at'])
    return asset


def cancel_upload(asset: MediaAsset) -> MediaAsset:
    if asset.status in MediaAsset.TERMINAL_STATUSES:
        raise MediaValidationError('upload has already finished and cannot be cancelled')
    return purge_storage_and_mark_deleted(asset)


def delete_orphan(asset: MediaAsset) -> MediaAsset:
    if asset.status == MediaAsset.Status.DELETED:
        return asset  # idempotent
    if asset.is_attached:
        raise MediaValidationError('media is attached and cannot be deleted directly')
    return purge_storage_and_mark_deleted(asset)


def get_download_url(asset: MediaAsset):
    if not asset.is_downloadable:
        return None
    backend = get_media_backend()
    return backend.generate_download_url(
        asset.storage_key,
        settings.MEDIA_ASSETS_SIGNED_URL_TTL_SECONDS,
        filename=asset.sanitized_filename,
        content_type=asset.detected_mime_type,
    )


def get_preview_url(asset: MediaAsset):
    if not asset.is_downloadable:
        return None
    backend = get_media_backend()
    key = asset.thumbnail_storage_key or asset.storage_key
    return backend.generate_download_url(key, settings.MEDIA_ASSETS_SIGNED_URL_TTL_SECONDS)
