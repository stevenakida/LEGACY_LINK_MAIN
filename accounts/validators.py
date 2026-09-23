from django.core.exceptions import ValidationError

# Avatars are served publicly, unauthenticated, straight from storage (see
# config.urls' catch-all /media/ route and the public-read R2 bucket in
# settings) with a Content-Type inferred from the file's own extension. Since
# User.avatar previously accepted literally any uploaded file, any signed-up
# user could host an arbitrary file — e.g. a phishing HTML page — on our own
# domain by naming it avatar.html. This is the fix for that hole: decode the
# actual pixel data with Pillow and reject anything that isn't a genuine
# JPEG/PNG/WEBP, never trusting the client-supplied filename or Content-Type.
_ALLOWED_AVATAR_FORMATS = {'JPEG', 'PNG', 'WEBP'}
_MAX_AVATAR_BYTES = 8 * 1024 * 1024


def validate_avatar_image(file):
    from PIL import Image, UnidentifiedImageError

    if file.size > _MAX_AVATAR_BYTES:
        raise ValidationError('Image must be smaller than 8MB.')

    try:
        file.seek(0)
        with Image.open(file) as probe:
            probe.verify()
        file.seek(0)
        with Image.open(file) as img:
            fmt = img.format
    except (UnidentifiedImageError, OSError):
        raise ValidationError('Please upload a valid JPEG, PNG or WEBP image.')
    finally:
        file.seek(0)

    if fmt not in _ALLOWED_AVATAR_FORMATS:
        raise ValidationError('Please upload a JPEG, PNG or WEBP image.')
