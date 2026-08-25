import uuid

from django.conf import settings
from django.db import models


class DeviceToken(models.Model):
    """An FCM registration token for one installed copy of the Android app.
    `token` is globally unique rather than unique-per-user: the Android app
    re-sends its current token on every page load, so if a device gets
    logged out and a different user logs in on it, the same token simply
    gets reassigned via update_or_create — the previous user stops
    receiving pushes to that device without needing an explicit unregister
    call."""

    PLATFORM_CHOICES = [
        ('android', 'Android'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='device_tokens'
    )
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='android')
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} ({self.platform})"
