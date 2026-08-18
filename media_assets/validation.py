"""Content validation and processing for each media category. Every check
here inspects actual file bytes — never the client-declared extension or
Content-Type — per the fail-closed posture required for this pipeline."""
import json
import subprocess

from django.conf import settings

from .exceptions import MediaValidationError

ALLOWED_IMAGE_MIME = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_VIDEO_MIME = {'video/mp4'}
ALLOWED_DOCUMENT_MIME = {'application/pdf'}

_PIL_FORMAT_TO_MIME = {
    'JPEG': 'image/jpeg',
    'PNG': 'image/png',
    'WEBP': 'image/webp',
}


class ImageValidationResult:
    def __init__(self, mime_type, width, height, processed_path, thumbnail_path):
        self.mime_type = mime_type
        self.width = width
        self.height = height
        self.processed_path = processed_path
        self.thumbnail_path = thumbnail_path


def validate_and_process_image(input_path: str, processed_output_path: str,
                                thumbnail_output_path: str) -> ImageValidationResult:
    from PIL import Image, ImageOps, UnidentifiedImageError

    # Decompression-bomb guard: Pillow raises DecompressionBombError once a
    # decoded image would exceed this many pixels, before allocating memory
    # for it.
    Image.MAX_IMAGE_PIXELS = settings.MEDIA_ASSETS_IMAGE_MAX_PIXELS

    try:
        with Image.open(input_path) as probe:
            probe.verify()
    except Exception:
        raise MediaValidationError('corrupt or unreadable image file')

    try:
        with Image.open(input_path) as img:
            fmt = img.format
            mime_type = _PIL_FORMAT_TO_MIME.get(fmt)
            if mime_type not in ALLOWED_IMAGE_MIME:
                raise MediaValidationError(f'unsupported image format: {fmt or "unknown"}')

            # Bakes any EXIF orientation into the pixels, then dropping EXIF
            # entirely at save time (below) removes the now-redundant tag
            # along with everything else (GPS, device info, etc). Kept even
            # though the resize/quality drop below was removed — this isn't
            # about size, it's privacy (GPS/device metadata) and cross-client
            # correctness (unrotated pixels).
            img = ImageOps.exif_transpose(img)

            # Deliberately no dimension downscale here — the pipeline used to
            # cap the *stored* image at MEDIA_ASSETS_IMAGE_MAX_DIMENSION,
            # which visibly degraded quality for anyone viewing/downloading
            # the full-size image. MEDIA_ASSETS_IMAGE_MAX_PIXELS (the
            # decompression-bomb guard, set via Image.MAX_IMAGE_PIXELS above)
            # still bounds how large an input this will ever decode.
            save_kwargs = {'optimize': True}
            if fmt in ('JPEG', 'WEBP'):
                # 95 is visually lossless while still compressing meaningfully
                # (unlike quality=100, which mostly just inflates file size).
                save_kwargs['quality'] = 95
            if fmt == 'JPEG' and img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            img.save(processed_output_path, format=fmt, **save_kwargs)
            width, height = img.width, img.height

            thumb = img.copy()
            thumb.thumbnail((320, 320), Image.LANCZOS)
            if thumb.mode not in ('RGB', 'L'):
                thumb = thumb.convert('RGB')
            thumb.save(thumbnail_output_path, format='JPEG', quality=80, optimize=True)
    except MediaValidationError:
        raise
    except UnidentifiedImageError:
        raise MediaValidationError('corrupt or unreadable image file')
    except Exception:
        raise MediaValidationError('image processing failed')

    return ImageValidationResult(mime_type, width, height, processed_output_path, thumbnail_output_path)


class DocumentValidationResult:
    def __init__(self, mime_type):
        self.mime_type = mime_type


def validate_document(input_path: str) -> DocumentValidationResult:
    with open(input_path, 'rb') as f:
        header = f.read(5)
    if header != b'%PDF-':
        raise MediaValidationError('file is not a valid PDF')

    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        reader = PdfReader(input_path)
        if reader.is_encrypted:
            raise MediaValidationError('encrypted/password-protected PDFs are not supported')
        if len(reader.pages) < 1:
            raise MediaValidationError('PDF has no pages')
    except MediaValidationError:
        raise
    except PdfReadError:
        raise MediaValidationError('corrupt or unreadable PDF file')
    except Exception:
        raise MediaValidationError('corrupt or unreadable PDF file')

    return DocumentValidationResult('application/pdf')


class VideoValidationResult:
    def __init__(self, mime_type, duration_seconds, thumbnail_path):
        self.mime_type = mime_type
        self.duration_seconds = duration_seconds
        self.thumbnail_path = thumbnail_path


def validate_video(input_path: str, thumbnail_output_path: str) -> VideoValidationResult:
    """Requires ffprobe (container/duration inspection). If the binary isn't
    available on this host, video uploads fail closed rather than being
    accepted unchecked — see settings.MEDIA_ASSETS_FFPROBE_PATH and the
    Phase 0 decision to add ffprobe as new infra for exactly this check."""
    probe = _run_ffprobe(input_path)

    format_name = probe.get('format', {}).get('format_name', '')
    if 'mp4' not in format_name.split(','):
        raise MediaValidationError('video container is not MP4')

    video_streams = [s for s in probe.get('streams', []) if s.get('codec_type') == 'video']
    if not video_streams:
        raise MediaValidationError('no video stream found')

    duration_raw = probe.get('format', {}).get('duration')
    try:
        duration_seconds = float(duration_raw)
    except (TypeError, ValueError):
        raise MediaValidationError('could not determine video duration')

    if duration_seconds > settings.MEDIA_ASSETS_VIDEO_MAX_DURATION_SECONDS + 0.5:
        raise MediaValidationError(
            f'video exceeds the {settings.MEDIA_ASSETS_VIDEO_MAX_DURATION_SECONDS}s limit'
        )

    thumbnail_path = _extract_video_thumbnail(input_path, thumbnail_output_path)
    return VideoValidationResult('video/mp4', duration_seconds, thumbnail_path)


def _run_ffprobe(input_path: str) -> dict:
    try:
        proc = subprocess.run(
            [
                settings.MEDIA_ASSETS_FFPROBE_PATH, '-v', 'error',
                '-print_format', 'json', '-show_format', '-show_streams',
                input_path,
            ],
            capture_output=True, timeout=20, check=False,
        )
    except FileNotFoundError:
        raise MediaValidationError('server-side video inspection is not available on this host')
    except subprocess.TimeoutExpired:
        raise MediaValidationError('video inspection timed out')

    if proc.returncode != 0:
        raise MediaValidationError('malformed or unreadable video file')

    try:
        return json.loads(proc.stdout.decode('utf-8', errors='replace'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise MediaValidationError('malformed or unreadable video file')


def _extract_video_thumbnail(input_path: str, output_path: str) -> str | None:
    """Best-effort single-frame grab — not transcoding. If ffmpeg is
    missing or the grab fails, the video is still valid; it just ends up
    without a thumbnail."""
    try:
        proc = subprocess.run(
            [
                settings.MEDIA_ASSETS_FFMPEG_PATH, '-y', '-ss', '0.5',
                '-i', input_path, '-frames:v', '1', '-f', 'image2', output_path,
            ],
            capture_output=True, timeout=20, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    import os
    return output_path if os.path.isfile(output_path) else None
