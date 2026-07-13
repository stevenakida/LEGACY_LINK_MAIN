import uuid
from django.conf import settings
from django.db import models


class Opportunity(models.Model):
    TYPE_CHOICES = [
        ('job', 'Job'),
        ('mentorship', 'Mentorship'),
        ('event', 'Event'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField()
    organization = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    event_date = models.DateTimeField(null=True, blank=True)
    external_link = models.URLField(blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='posted_opportunities'
    )
    # Scopes an opportunity to alumni of one school (powers the "My school"
    # filter and the "Posted by an X alum" attribution); null means open to
    # everyone regardless of school.
    school_scope = models.ForeignKey(
        'alumni.School', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scoped_opportunities'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_type_display()}] {self.title}"


class OpportunityInterest(models.Model):
    """A lightweight 'Apply' (job) / 'Join' (mentorship) / 'RSVP' (event)
    record — who expressed interest in an Opportunity, and when. Not a full
    application workflow (resumes, review states) — that's a later phase."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='interests')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('opportunity', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.full_name} → {self.opportunity.title}"
