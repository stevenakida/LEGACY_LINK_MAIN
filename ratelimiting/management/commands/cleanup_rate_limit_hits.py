from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ratelimiting.models import RateLimitHit


class Command(BaseCommand):
    help = (
        "Purges RateLimitHit rows older than RATE_LIMIT_HIT_RETENTION_HOURS "
        "— every rate-limit window is measured in minutes, so anything past "
        "the retention period is guaranteed to already be outside every "
        "window and only exists to be pruned. There is no task-queue/"
        "scheduler infra in this project yet, so this is meant to be "
        "invoked periodically by an external scheduler (e.g. a host "
        "crontab running 'manage.py cleanup_rate_limit_hits' daily) — same "
        "pattern as media_assets' cleanup_media command."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be purged without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        cutoff = timezone.now() - timezone.timedelta(hours=settings.RATE_LIMIT_HIT_RETENTION_HOURS)
        candidates = RateLimitHit.objects.filter(created_at__lt=cutoff)
        count = candidates.count()

        self.stdout.write(f"Found {count} rate limit hit(s) older than {settings.RATE_LIMIT_HIT_RETENTION_HOURS}h to purge.")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
        else:
            candidates.delete()
            self.stdout.write(self.style.SUCCESS(f"Purged {count} rate limit hit(s)."))
