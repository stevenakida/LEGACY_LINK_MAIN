import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class School(models.Model):
    TYPE_CHOICES = [
        ('secondary', 'Secondary School (O-Level)'),
        ('primary', 'Primary School'),
        ('high_school', 'High School (A-Level)'),
        ('university', 'University'),
    ]

    name = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    region = models.CharField(max_length=200, blank=True)
    district = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=100, default='Tanzania')
    school_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='secondary')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Source record ID from the education master database (e.g. "PRI00001").
    # Lets the import command upsert instead of duplicating on re-run.
    external_id = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class SchoolAlias(models.Model):
    """An alternative name people search a school by -- an acronym ("IFM"), a
    Swahili name ("Chuo Kikuu cha Dodoma"), a spelling variant ("Co-operative"),
    or an old name. Search matches it exactly like the school's own name, but
    the school is always shown and stored under its canonical name, so an
    alias never creates a second school (that is what keeps two alumni from
    the same institution findable by each other)."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['alias']
        unique_together = ('school', 'alias')

    def __str__(self):
        return f'{self.alias} -> {self.school.name}'


class SchoolRequest(models.Model):
    """A "my school isn't listed" request. Reviewed in the Django admin, which
    either creates the school, points the request at an existing school (and
    records the requested spelling as an alias), or rejects it -- see
    alumni.services. UUID primary key because notifications.Notification's
    generic target only supports UUID object ids."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='school_requests')
    school_type = models.CharField(max_length=20, choices=School.TYPE_CHOICES)
    name = models.CharField(max_length=200)
    region = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # The school this request ended up as (new row, or an existing one the
    # admin chose). SET_NULL so deleting a school never deletes the history.
    resolved_school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f'{self.name} ({self.get_school_type_display()}) - {self.status}'
