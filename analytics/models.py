import uuid

from django.conf import settings
from django.db import models


class ProductEvent(models.Model):
    """Append-only product-analytics event.

    Deliberately tiny and privacy-conservative: only allowlisted event names
    and allowlisted, non-identifying properties are ever stored (enforced in
    analytics.services.record_event), so this table can never hold names,
    contact details or message text. `actor` is a FK so a user's events go
    with their account; it is null-safe for logged-out events.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=60)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='+'
    )
    properties = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['name', 'created_at']),
            models.Index(fields=['actor', 'name']),
        ]

    def __str__(self):
        return f"{self.name} at {self.created_at:%Y-%m-%d %H:%M:%S}"
