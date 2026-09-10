import requests
from django.core.management.base import BaseCommand, CommandError

from ingestion.models import IngestedItem
from ingestion.reliefweb import ReliefWebNotConfigured, fetch_jobs, parse_jobs_response
from ingestion.services import get_system_author
from opportunities.models import Opportunity


class Command(BaseCommand):
    help = (
        "Fetches Tanzania-filtered job postings from the official "
        "ReliefWeb API (humanitarian/UN/NGO/development vacancies — "
        "https://apidoc.reliefweb.int/) and adds any new one to "
        "Opportunities as a Job, posted by the LegacyLink Africa system "
        "account. Requires RELIEFWEB_APPNAME (see config/settings.py) — "
        "ReliefWeb requires a pre-approved appname as of Nov 2025; request "
        "one at https://apidoc.reliefweb.int/parameters#appname. Dedup via "
        "ingestion.IngestedItem keyed on ReliefWeb's own job id. No task-"
        "queue/scheduler infra in this project yet — meant to be invoked "
        "periodically by an external scheduler (e.g. a DO App Platform "
        "SCHEDULED job, same pattern as ratelimiting.cleanup_rate_limit_hits)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20, help='Max jobs to fetch per run (default 20).')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be added without creating anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        try:
            payload = fetch_jobs(limit=options['limit'])
        except ReliefWebNotConfigured as exc:
            raise CommandError(str(exc))
        except requests.RequestException as exc:
            raise CommandError(f'Failed to reach the ReliefWeb API: {exc}')

        all_items = parse_jobs_response(payload)
        if not all_items:
            self.stdout.write('No ReliefWeb jobs found for Tanzania.')
            return

        already_ingested_ids = set(
            IngestedItem.objects.filter(
                source=IngestedItem.Source.RELIEFWEB_JOB,
                external_id__in=[item.external_id for item in all_items],
            ).values_list('external_id', flat=True)
        )
        to_create = [item for item in all_items if item.external_id not in already_ingested_ids]

        self.stdout.write(f'Found {len(all_items)} job(s), {len(to_create)} new.')
        if dry_run:
            for item in to_create:
                self.stdout.write(f'  [{item.external_id}] {item.title} — {item.organization}')
            self.stdout.write(self.style.WARNING('Dry run — no changes made.'))
            return
        if not to_create:
            return

        author = get_system_author()
        created = 0
        for item in to_create:
            description_parts = [item.body] if item.body else []
            if item.closing_date:
                description_parts.append(f'Apply by: {item.closing_date:%d %b %Y}')
            description_parts.append(f'Source: {item.url}')
            Opportunity.objects.create(
                type='job',
                title=item.title[:200],
                description='\n\n'.join(description_parts),
                organization=item.organization[:200],
                location=item.location[:200],
                external_link=item.url,
                posted_by=author,
            )
            IngestedItem.objects.create(source=IngestedItem.Source.RELIEFWEB_JOB, external_id=item.external_id)
            created += 1

        self.stdout.write(self.style.SUCCESS(f'Added {created} new ReliefWeb job(s).'))
