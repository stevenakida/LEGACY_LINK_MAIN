import requests
from django.core.management.base import BaseCommand, CommandError

from ingestion.models import IngestedItem
from ingestion.necta import (
    CURATED_POST_BODIES,
    fetch_news_html,
    fetch_portal_html,
    parse_news_html,
    parse_portal_html,
    recent_portal_items,
)
from ingestion.services import get_system_author, record_source_check
from posts.models import Post

SOURCE_NEWS = 'necta_news'
SOURCE_PORTAL = 'necta_portal'


class Command(BaseCommand):
    help = (
        "Scrapes https://www.necta.go.tz/news/all and the results portal at "
        "https://matokeo.necta.go.tz/ and posts any new announcement (exam "
        "timetables, results releases, registration notices, etc.) to the "
        "Home feed as a Public post authored by the LegacyLink Africa system "
        "account. Dedup via ingestion.IngestedItem keyed on NECTA's own "
        "article id or result URL, so re-running never reposts the same "
        "announcement. One source failing doesn't stop the other; both "
        "failing exits non-zero. Each source's health is kept in "
        "ingestion.SourceCheck. No task-queue/scheduler infra in this project "
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

        news_items, news_error = self._fetch_news(pages)
        portal_items, portal_error = self._fetch_portal()

        if not dry_run:
            record_source_check(SOURCE_NEWS, news_error)
            record_source_check(SOURCE_PORTAL, portal_error)
        if news_error and portal_error:
            raise CommandError(f'All NECTA sources failed. News: {news_error} Portal: {portal_error}')

        # News page first: when a release is on both, its entry has a summary.
        items_by_id = {}
        for item in news_items + portal_items:
            items_by_id.setdefault(item.external_id, item)
        all_items = list(items_by_id.values())

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
            Post.objects.create(
                author=author,
                body=self._post_body(item),
                audience=Post.Audience.PUBLIC,
            )
            IngestedItem.objects.create(source=IngestedItem.Source.NECTA_NEWS, external_id=item.external_id)
            posted += 1

        self.stdout.write(self.style.SUCCESS(f'Posted {posted} new NECTA announcement(s).'))

    def _fetch_news(self, pages):
        """Returns (items, error). A page that loads but yields no articles
        counts as a failure too: that's what a site redesign looks like, and
        it must not pass for a quiet news week."""
        items = []
        errors = []
        for page in range(1, pages + 1):
            try:
                html = fetch_news_html(page=page)
            except requests.RequestException as exc:
                errors.append(f'Failed to fetch NECTA news page {page}: {exc}')
                self.stderr.write(self.style.ERROR(errors[-1]))
                continue
            items.extend(parse_news_html(html))
        if items:
            return items, ''
        return [], ' '.join(errors) or 'NECTA news page loaded but no articles could be parsed.'

    def _fetch_portal(self):
        """Returns (recent items, error), with the same no-entries rule as
        _fetch_news. Having entries but none recent is the normal case."""
        try:
            html = fetch_portal_html()
        except requests.RequestException as exc:
            error = f'Failed to fetch NECTA results portal: {exc}'
            self.stderr.write(self.style.ERROR(error))
            return [], error
        items = parse_portal_html(html)
        if not items:
            return [], 'NECTA results portal loaded but no entries could be parsed.'
        return recent_portal_items(items), ''

    def _post_body(self, item):
        curated = CURATED_POST_BODIES.get(item.url)
        if curated:
            return curated[:2000]
        body_parts = [item.title]
        if item.summary and item.summary != item.title:
            body_parts.append(item.summary)
        body_parts.append(f'Full announcement: {item.url}')
        return '\n\n'.join(body_parts)[:2000]
