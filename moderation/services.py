from django.contrib.contenttypes.models import ContentType

from .models import ContentReport, ModerationHold


class InvalidReportCategory(Exception):
    pass


def file_report(reporter, target, category, description=''):
    """Record `reporter`'s report against `target` (a Post or MediaAsset
    instance) and open/reopen the generalized ModerationHold on it.

    Deliberately does NOT touch the target's own fast-path gating field
    (Post.approval_status / MediaAsset.moderation_hold) — that stays the
    caller's job, same split ModerationHold.open_or_reopen already
    documents for the Public-audience-review case, because what "held"
    means differs per content type (a held post disappears entirely; a
    held media asset just stops being servable while the rest of its post
    or message stays visible). This function only handles the two things
    every report has in common: logging who reported what and why, and
    making sure a hold exists for a moderator to act on."""
    if category not in ContentReport.Category.values:
        raise InvalidReportCategory(category)

    content_type = ContentType.objects.get_for_model(target)
    report, _ = ContentReport.objects.update_or_create(
        reporter=reporter, content_type=content_type, object_id=target.pk,
        defaults={'category': category, 'description': (description or '').strip()[:1000]},
    )
    ModerationHold.open_or_reopen(target, ModerationHold.Reason.USER_REPORT)
    return report
