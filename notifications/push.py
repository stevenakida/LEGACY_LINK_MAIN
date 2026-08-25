import json
import logging

import firebase_admin
from decouple import config
from firebase_admin import credentials, messaging

from .models import DeviceToken

logger = logging.getLogger(__name__)

_app = None
_app_init_attempted = False


def _get_app():
    """Lazily initializes the firebase_admin app from the service account
    JSON in FIREBASE_SERVICE_ACCOUNT_JSON. Returns None (rather than
    raising) when it isn't configured, e.g. local dev — callers no-op in
    that case instead of failing the request that triggered a push."""
    global _app, _app_init_attempted
    if _app is not None or _app_init_attempted:
        return _app
    _app_init_attempted = True

    raw = config('FIREBASE_SERVICE_ACCOUNT_JSON', default='')
    if not raw:
        return None
    try:
        cred = credentials.Certificate(json.loads(raw))
        _app = firebase_admin.initialize_app(cred)
    except Exception:
        logger.exception("Failed to initialize firebase_admin from FIREBASE_SERVICE_ACCOUNT_JSON")
    return _app


def send_push_to_user(user, title, body, data=None):
    """Sends an FCM push to every device registered for `user`. No-ops
    silently if Firebase credentials aren't configured. Prunes tokens FCM
    reports as no-longer-registered so DeviceToken doesn't accumulate dead
    rows for uninstalled apps."""
    app = _get_app()
    if app is None:
        return

    tokens = list(DeviceToken.objects.filter(user=user).values_list('token', flat=True))
    if not tokens:
        return

    stale_tokens = []
    for token in tokens:
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data={str(k): str(v) for k, v in (data or {}).items()},
        )
        try:
            messaging.send(message, app=app)
        except messaging.UnregisteredError:
            stale_tokens.append(token)
        except Exception:
            logger.exception("FCM send failed for a device token")

    if stale_tokens:
        DeviceToken.objects.filter(token__in=stale_tokens).delete()
