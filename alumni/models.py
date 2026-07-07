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
