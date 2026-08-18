from django.db import models
from django.conf import settings
import uuid


class Connection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_connections'
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_connections'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('requester', 'receiver')  # No duplicate requests
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.requester.full_name} → {self.receiver.full_name} ({self.status})"

    @classmethod
    def accepted_between(cls, user):
        """All accepted Connection rows involving `user`, in either
        direction. Centralizes the (Q(requester=user) | Q(receiver=user)) &
        Q(status='accepted') shape that was previously duplicated ad hoc
        across views (dashboard, posts feed, etc.) — flagged in the Phase 0
        media/posts audit as a prerequisite refactor for anything that needs
        to reason about "who is user connected to" (like Home feed
        visibility). Only new call sites (posts app) adopt this so far;
        existing duplicated queries elsewhere are left as-is to avoid
        touching unrelated, already-working connection code."""
        return cls.objects.filter(
            (models.Q(requester=user) | models.Q(receiver=user)) & models.Q(status='accepted')
        )
