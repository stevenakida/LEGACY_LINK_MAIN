from django.core.management.base import BaseCommand
from django.utils import timezone

from media_assets.models import MediaAsset
from media_assets.services import purge_storage_and_mark_deleted


class Command(BaseCommand):
    help = (
        "Purges stuck/expired/orphaned MediaAsset uploads: INITIALIZED rows "
        "whose upload URL expired before a file ever arrived, terminal "
        "FAILED/REJECTED rows past the retention window, and unattached "
        "READY rows past their purge_at. There is no task-queue/scheduler "
        "infra in this project yet, so this is meant to be invoked "
        "periodically by an external scheduler (e.g. a Render cron job or "
        "host crontab running 'manage.py cleanup_media' hourly) — see the "
        "Phase 1 report for what needs provisioning."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be purged without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()

        expired_initializations = MediaAsset.objects.filter(
            status=MediaAsset.Status.INITIALIZED,
            upload_url_expires_at__lt=now,
        )
        terminal_past_retention = MediaAsset.objects.filter(
            status__in=[MediaAsset.Status.FAILED, MediaAsset.Status.REJECTED],
            purge_at__lt=now,
        )
        orphaned_ready = MediaAsset.objects.filter(
            status=MediaAsset.Status.READY,
            is_attached=False,
            purge_at__lt=now,
        )

        candidates = list(expired_initializations) + list(terminal_past_retention) + list(orphaned_ready)
        self.stdout.write(f"Found {len(candidates)} media asset(s) to purge.")

        for asset in candidates:
            self.stdout.write(f"  - {asset.id} [{asset.category}/{asset.status}] owner={asset.owner_id}")
            if not dry_run:
                purge_storage_and_mark_deleted(asset)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Purged {len(candidates)} media asset(s)."))
