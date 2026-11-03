import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from accounts.models import User
from ingestion.models import SourceCheck

logger = logging.getLogger(__name__)

SYSTEM_ACCOUNT_IDENTIFIER = 'system+content@legacylinkafrica.local'

# With a daily job: first alert on day 3 of an outage, then weekly reminders.
ALERT_AFTER_FAILURES = 3
ALERT_REPEAT_EVERY = 7


def get_system_author():
    """The account external-content ingestion (NECTA news, ReliefWeb jobs,
    any future source) posts/lists as — 'LegacyLink Africa' rather than a
    real user. Unusable password: this account can never log in, it only
    ever appears as a Post.author / Opportunity.posted_by. get_or_create
    keeps every ingestion command idempotent without needing a
    migration-time data fixture."""
    user, created = User.objects.get_or_create(
        phone_or_email=SYSTEM_ACCOUNT_IDENTIFIER,
        defaults={'full_name': 'LegacyLink Africa', 'onboarding_complete': True},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


def record_source_check(source, error=''):
    """Records one check of a scraped source and emails the team if it has now
    been failing long enough to need a look. Pass error='' for a success."""
    check, _ = SourceCheck.objects.get_or_create(source=source)
    if error:
        check.consecutive_failures += 1
        check.last_error = error[:2000]
    else:
        check.consecutive_failures = 0
        check.last_error = ''
        check.last_success_at = timezone.now()
    check.save()

    if error and _alert_due(check.consecutive_failures):
        _send_source_alert(check)
    return check


def _alert_due(failures):
    if failures < ALERT_AFTER_FAILURES:
        return False
    return (failures - ALERT_AFTER_FAILURES) % ALERT_REPEAT_EVERY == 0


def _send_source_alert(check):
    """Same recipient setting and failure handling as feedback notifications:
    a mail problem is logged and must never fail the ingestion run itself."""
    if not settings.FEEDBACK_NOTIFY_EMAIL:
        logger.warning('Source %s is failing but FEEDBACK_NOTIFY_EMAIL is not set', check.source)
        return
    try:
        send_mail(
            subject=f'LegacyLink news check failing: {check.source}',
            message=(
                f'The scheduled check of {check.source} has failed '
                f'{check.consecutive_failures} times in a row, so new '
                f'announcements from it are not reaching the feed.\n\n'
                f'Last success: {check.last_success_at or "never recorded"}\n'
                f'Last error: {check.last_error}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.FEEDBACK_NOTIFY_EMAIL],
        )
    except Exception:
        logger.exception('Failed to send the source-check alert for %s', check.source)
