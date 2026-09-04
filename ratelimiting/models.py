import uuid

from django.conf import settings
from django.db import models


class RateLimitHit(models.Model):
    """Phase 6 rate-limiting primitive: one row per rate-limited action
    attempt that was actually allowed through. `scope` names which action
    this hit is for (e.g. "create_post") so a single table can serve every
    rate-limited action this project adds, matching moderation.ModerationHold's
    "one generic primitive, many call sites" shape rather than a bespoke
    table per action.

    An append-only hit log rather than a fixed-window counter — checking
    "how many hits in the last N seconds" is a simple indexed range query,
    and a rolling window like this can't let 2x the limit through across a
    window boundary the way a fixed calendar window can."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=50)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['scope', 'actor', 'created_at'])]

    def __str__(self):
        return f"{self.scope} hit by {self.actor.full_name} at {self.created_at:%Y-%m-%d %H:%M:%S}"
