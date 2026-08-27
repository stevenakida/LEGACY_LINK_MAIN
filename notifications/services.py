import threading

from django.contrib.contenttypes.models import ContentType

from .models import Notification
from .push import send_push_to_user


def notify(recipient, verb, actor=None, target=None, push_title=None, push_body=None):
    """Phase 4B's single entry point for raising a notification — bundles
    persisting the in-app Notification row with firing the push, the same
    way moderation.services.file_report() bundles logging a ContentReport
    with opening a ModerationHold, so call sites don't have to do both
    steps themselves and can't forget one.

    Push is fire-and-forget on a background thread (same pattern
    config.views.messages_send already used directly before this) — no
    task queue, matching the Phase 0 decision not to introduce Celery/Redis.
    Only fires when both push_title and push_body are given, so a caller
    that wants an in-app-only notification can simply omit them."""
    notification = Notification.objects.create(
        recipient=recipient,
        actor=actor,
        verb=verb,
        content_type=ContentType.objects.get_for_model(target) if target is not None else None,
        object_id=target.pk if target is not None else None,
    )

    if push_title and push_body:
        threading.Thread(
            target=send_push_to_user, args=(recipient, push_title, push_body), daemon=True,
        ).start()

    return notification
