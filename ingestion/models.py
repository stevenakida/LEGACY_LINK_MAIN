import uuid

from django.db import models


class IngestedItem(models.Model):
    """One row per external item a scraper/API-fetch command has already
    turned into a Post or Opportunity — the dedup ledger that keeps a
    periodic run from reposting the same NECTA announcement or ReliefWeb
    job every time it runs. `external_id` is whatever stable identifier
    the source itself provides (NECTA's /news/read/<id> path segment,
    ReliefWeb's numeric job id) — never a hash of the content, since a
    source lightly editing an already-posted item (typo fix, etc.)
    shouldn't cause a duplicate repost."""

    class Source(models.TextChoices):
        NECTA_NEWS = 'necta_news', 'NECTA news'
        RELIEFWEB_JOB = 'reliefweb_job', 'ReliefWeb job'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=30, choices=Source.choices)
    external_id = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('source', 'external_id')
        indexes = [models.Index(fields=['source', 'external_id'])]

    def __str__(self):
        return f"{self.get_source_display()}:{self.external_id}"


class SourceCheck(models.Model):
    """Latest health of one scraped source, one row per source. A scheduled
    job that can't reach a site looks exactly like a site with no news unless
    something records the difference — see services.record_source_check."""

    source = models.CharField(max_length=30, unique=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    last_checked_at = models.DateTimeField(auto_now=True)
    last_success_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.source}: {self.consecutive_failures} consecutive failure(s)"
