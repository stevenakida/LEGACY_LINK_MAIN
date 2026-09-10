import requests
from django.core.management.base import BaseCommand

from ingestion.models import IngestedItem
from ingestion.necta import fetch_news_html, parse_news_html
from ingestion.services import get_system_author
from posts.models import Post


class Command(BaseCommand):
    help = (
        "Scrapes https://www.necta.go.tz/news/all and posts any new "
        "announcement (exam timetables, results releases, registration "
        "notices, etc.) to the Home feed as a Public post authored by the "
        "LegacyLink Africa system account. Dedup via ingestion.IngestedItem "
        "keyed on NECTA's own article id, so re-running never reposts the "
        "same announcement. No task-queue/scheduler infra in this project "
        "yet — meant to be invoked periodically by an external scheduler "
        "(e.g. a DO App Platform SCHEDULED job, same pattern as "
        "ratelimiting.cleanup_rate_limit_hits)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--pages', type=int, default=1,
            help=(
                'How many listing pages to scan (default 1 — just the '
                'newest page). Dedup makes scanning further pages on every '
                'routine run wasteful; only raise this for a one-off '
                'backfill of older announcements.'
            ),
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be posted without creating anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        pages = options['pages']

        all_items = []
        for page in range(1, pages + 1):
            try:
                html = fetch_news_html(page=page)
            except requests.RequestException as exc:
                self.stderr.write(self.style.ERROR(f'Failed to fetch NECTA news page {page}: {exc}'))
                continue
            all_items.extend(parse_news_html(html))

        if not all_items:
            self.stdout.write('No NECTA news items found.')
            return

        already_ingested_ids = set(
            IngestedItem.objects.filter(
                source=IngestedItem.Source.NECTA_NEWS,
                external_id__in=[item.external_id for item in all_items],
            ).values_list('external_id', flat=True)
        )
        to_create = [item for item in all_items if item.external_id not in already_ingested_ids]

        self.stdout.write(f'Found {len(all_items)} item(s) on {pages} page(s), {len(to_create)} new.')
        if dry_run:
            for item in to_create:
                self.stdout.write(f'  [{item.external_id}] {item.title}')
            self.stdout.write(self.style.WARNING('Dry run — no changes made.'))
            return
        if not to_create:
            return

        author = get_system_author()
        posted = 0
        for item in to_create:
            body_parts = [item.title]
            if item.summary and item.summary != item.title:
                body_parts.append(item.summary)
            body_parts.append(f'Full announcement: {item.url}')
            Post.objects.create(
                author=author,
                body='\n\n'.join(body_parts)[:2000],
                audience=Post.Audience.PUBLIC,
            )
            IngestedItem.objects.create(source=IngestedItem.Source.NECTA_NEWS, external_id=item.external_id)
            posted += 1

        self.stdout.write(self.style.SUCCESS(f'Posted {posted} new NECTA announcement(s).'))
