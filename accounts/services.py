"""Email-verification sending, shared between the web profile-edit flow
(config.views.profile_edit) and the mobile API (accounts.views.MeView) so
both trigger verification identically — see User.apply_email_update /
User.eligible_reset_email for the matching "why" on the model side."""
import logging
import threading

from django.conf import settings
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token

logger = logging.getLogger(__name__)


def mask_email(email):
    """Redact an address for logging — enough to correlate log lines with a
    support ticket without writing the full address into the logs."""
    if not email or '@' not in email:
        return '***'
    local, _, domain = email.partition('@')
    masked_local = f'{local[0]}***' if local else '***'
    return f'{masked_local}@{domain}'


def _send_email_verification_email(to_email, full_name, verify_url):
    """Runs on a background thread — never let a slow Gmail SMTP call block
    the HTTP response (same reasoning as config.views._send_password_reset_email)."""
    try:
        send_mail(
            subject='Verify your LegacyLink Africa email address',
            message=(
                f'Hi {full_name},\n\n'
                f'Confirm this email address on your LegacyLink Africa account by '
                f'clicking the link below. Once verified, you can use it to reset '
                f'your password if you ever forget it:\n\n'
                f'{verify_url}\n\n'
                f"If you didn't add this email address, you can safely ignore this email."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Failed to send email verification email to %s', mask_email(to_email))


def dispatch_email_verification(request, user):
    """Sends (in the background) the link a user must click before their
    profile `email` counts as verified. `request` just needs
    `build_absolute_uri` — both a plain Django request (web) and a DRF
    Request (mobile API) support it identically, which is what makes this
    safely shared between the two entry points."""
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verify_url = request.build_absolute_uri(f'/verify-email/{uidb64}/{token}/')
    logger.info('Email verification dispatched for account %s', user.id)
    threading.Thread(
        target=_send_email_verification_email,
        kwargs=dict(to_email=user.email, full_name=user.full_name, verify_url=verify_url),
        daemon=True,
    ).start()


def delete_account(user):
    """Permanently delete `user` and everything tied to them. Every foreign key
    to User cascades, so the row delete removes their posts, comments, likes,
    connections, messages, notifications and media records; this also drops
    what cascading can't reach: their one-to-one chats (which would otherwise
    linger with a single member), notifications they triggered for others,
    and the uploaded files in storage. Files are only deleted once the
    database transaction has committed, so a failed delete never leaves an
    account pointing at missing photos."""
    from django.db import transaction

    from media_assets.models import MediaAsset
    from media_assets.storage import get_media_backend
    from messaging.models import Conversation
    from notifications.models import Notification

    user_id = user.id
    # Collected up front: the MediaAsset rows are cascade-deleted with the user.
    media_keys = [
        key
        for keys in MediaAsset.objects.filter(owner=user).exclude(status=MediaAsset.Status.DELETED)
        .values_list('quarantine_storage_key', 'storage_key', 'thumbnail_storage_key')
        for key in keys if key
    ]
    avatar_storage = user.avatar.storage if user.avatar else None
    avatar_name = user.avatar.name if user.avatar else None

    with transaction.atomic():
        Conversation.objects.filter(
            type=Conversation.ConversationType.DIRECT, participants__user=user,
        ).delete()
        Notification.objects.filter(actor=user).delete()
        user.delete()

    def purge_files():
        backend = get_media_backend()
        for key in media_keys:
            try:
                backend.delete_object(key)
            except Exception:
                logger.exception('delete_account: could not delete stored object %s', key)
        if avatar_name:
            try:
                avatar_storage.delete(avatar_name)
            except Exception:
                logger.exception('delete_account: could not delete avatar for user %s', user_id)

    transaction.on_commit(purge_files)
    logger.info('Account deleted: user %s', user_id)
