from django.db import models
from django.utils.text import slugify


class School(models.Model):
    TYPE_CHOICES = [
        ('secondary', 'Secondary School'),
        ('primary', 'Primary School'),
        ('university', 'University'),
    ]

    name = models.CharField(max_length=300)
    slug = models.SlugField(unique=True, blank=True)
    region = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=100, default='Tanzania')
    school_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='secondary')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
