from django.utils import timezone

from .models import RateLimitHit


def is_rate_limited(actor, scope, limit, window_seconds):
    """True if `actor` has already hit `limit` recorded RateLimitHits for
    `scope` within the trailing `window_seconds` — in that case, does NOT
    record this attempt, so a blocked request can't itself extend the
    window. Otherwise records this attempt and returns False (allowed).

    Not atomic against a genuine race (two near-simultaneous requests from
    the same user could both pass the count check before either's INSERT
    commits) — acceptable here since this is an abuse deterrent, not a hard
    security boundary, and avoiding SELECT ... FOR UPDATE keeps this cheap
    enough to call on every write it guards."""
    window_start = timezone.now() - timezone.timedelta(seconds=window_seconds)
    recent_count = RateLimitHit.objects.filter(
        scope=scope, actor=actor, created_at__gte=window_start
    ).count()
    if recent_count >= limit:
        return True
    RateLimitHit.objects.create(scope=scope, actor=actor)
    return False
