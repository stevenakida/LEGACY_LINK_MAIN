import re
import uuid

# Extensions we will ever write to the "ready" prefix, keyed by the MIME type
# our own content-sniffing detects (never the client-declared one). Anything
# not in this map cannot reach the ready prefix at all.
READY_EXTENSION_BY_MIME = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
    'video/mp4': 'mp4',
    'application/pdf': 'pdf',
}

# Executable / script-like extensions we refuse regardless of declared
# content-type, as a defense-in-depth check on the client-supplied filename
# (belt-and-suspenders alongside the real content-sniffing validation).
_BLOCKED_FILENAME_EXTENSIONS = {
    'exe', 'msi', 'bat', 'cmd', 'com', 'scr', 'ps1', 'sh', 'bash',
    'js', 'jse', 'vbs', 'vbe', 'wsf', 'wsh', 'jar', 'app', 'apk',
    'dll', 'so', 'dylib', 'php', 'py', 'rb', 'pl', 'cgi', 'htm', 'html',
    'svg',  # SVG can carry executable script content — pilot allows raster only anyway
}

_SAFE_FILENAME_CHARS = re.compile(r'[^A-Za-z0-9._-]+')


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Produce a display-only filename: strip any path component (prevents
    path traversal via '../' or absolute paths), collapse to a safe
    character set, and cap length. Never used to build a storage path —
    storage keys are always a fresh random token, see `new_storage_key`."""
    name = (name or 'file').strip()
    # Drop everything up to the last path separator from either OS style.
    name = name.replace('\\', '/').rsplit('/', 1)[-1]
    name = _SAFE_FILENAME_CHARS.sub('_', name)
    name = name.strip('._') or 'file'
    return name[:max_length]


def filename_has_blocked_extension(name: str) -> bool:
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return ext in _BLOCKED_FILENAME_EXTENSIONS


def new_storage_key(prefix: str, extension: str = '') -> str:
    """Unpredictable object key: a fresh random token under the given
    prefix, never derived from the user-supplied filename or the
    MediaAsset's own (client-visible) id."""
    token = uuid.uuid4().hex
    suffix = f'.{extension}' if extension else ''
    return f'{prefix}{token}{suffix}'


def ready_extension_for_mime(mime_type: str) -> str | None:
    return READY_EXTENSION_BY_MIME.get(mime_type)
