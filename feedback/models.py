import uuid
from django.conf import settings
from django.db import models


class Feedback(models.Model):
    CATEGORY_CHOICES = [
        ('bug', 'Bug report'),
        ('suggestion', 'Suggestion'),
        ('praise', 'Praise'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('new', 'New'),
        ('reviewed', 'Reviewed'),
        ('resolved', 'Resolved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='feedback_entries'
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    message = models.TextField(max_length=2000)
    page_path = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_category_display()} from {self.user.full_name} ({self.created_at:%Y-%m-%d})"
