"""No real network calls in this suite — every test mocks the HTTP layer
(fetch_news_html / requests.get) with fixture data. See ingestion/necta.py
and ingestion/reliefweb.py docstrings for how those fixtures were derived
from the real, live sites (verified 2026-09-11)."""
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.models import User
from ingestion.models import IngestedItem
from ingestion.necta import parse_news_html
from ingestion.reliefweb import ReliefWebNotConfigured, parse_jobs_response
from ingestion.services import get_system_author
from opportunities.models import Opportunity
from posts.models import Post

# A trimmed-but-real sample of https://www.necta.go.tz/news/all's markup:
# one ordinary announcement (/news/read/<id>) and one results-release
# announcement (links straight out to the separate matokeo.necta.go.tz
# portal instead) — the two shapes _parse_article has to handle.
NECTA_SAMPLE_HTML = """
<section id="blog" class="blog"><div class="container"><div class="row"><div class="col-lg-8 entries">
<article class="entry">
    <h2 class="entry-title"><a href="/news/read/73">USAJILI WA WATAHINIWA WA KUJITEGEMEA ACSEE 2027</a></h2>
    <div class="entry-meta"><ul><li><time datetime="2020-01-01">Jul 16, 2026 13:25</time></li></ul></div>
    <div class="entry-content"><p>ACSEE 2027</p><div class="read-more"><a href="/news/read/73">Read More</a></div></div>
</article>
<article class="entry">
    <h2 class="entry-title"><a href="https://matokeo.necta.go.tz/results/2026/acsee/index.htm">MATOKEO YA MTIHANI WA KIDATO CHA SITA (ACSEE) 2026</a></h2>
    <div class="entry-meta"><ul><li><time datetime="2020-01-01">Jul 6, 2026 11:26</time></li></ul></div>
    <div class="entry-content"><p>ACSEE 2026</p><div class="read-more"><a href="https://matokeo.necta.go.tz/results/2026/acsee/index.htm">Read More</a></div></div>
</article>
<article class="entry">
    <h2 class="entry-title"><a href="#no-href-attr-case"></a></h2>
</article>
</div></div></div></section>
"""


class NectaParsingTests(TestCase):
    def test_parses_ordinary_article_and_results_article(self):
        items = parse_news_html(NECTA_SAMPLE_HTML)
        self.assertEqual(len(items), 2)

        ordinary, results = items
        self.assertEqual(ordinary.external_id, '73')
        self.assertEqual(ordinary.title, 'USAJILI WA WATAHINIWA WA KUJITEGEMEA ACSEE 2027')
        self.assertEqual(ordinary.url, 'https://www.necta.go.tz/news/read/73')
        self.assertEqual(ordinary.published_at.year, 2026)
        self.assertEqual(ordinary.published_at.month, 7)

        self.assertEqual(results.external_id, 'https://matokeo.necta.go.tz/results/2026/acsee/index.htm')
        self.assertEqual(results.url, results.external_id)
        self.assertIn('ACSEE) 2026', results.title)

    def test_malformed_article_is_skipped_not_raised(self):
        # The third <article> in the fixture has an empty href and no
        # title text — parse_news_html must skip it, not blow up the run.
        items = parse_news_html(NECTA_SAMPLE_HTML)
        self.assertEqual(len(items), 2)  # the malformed third one is absent


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class NectaIngestCommandTests(TestCase):
    def _run(self, *args):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('ingest_necta_news', *args, stdout=out)
        return out.getvalue()

    @patch('ingestion.management.commands.ingest_necta_news.fetch_news_html')
    def test_dry_run_creates_nothing(self, mock_fetch):
        mock_fetch.return_value = NECTA_SAMPLE_HTML
        output = self._run('--dry-run')
        self.assertIn('2 new', output)
        self.assertEqual(Post.objects.count(), 0)
        self.assertEqual(IngestedItem.objects.count(), 0)

    @patch('ingestion.management.commands.ingest_necta_news.fetch_news_html')
    def test_creates_public_posts_authored_by_system_account(self, mock_fetch):
        mock_fetch.return_value = NECTA_SAMPLE_HTML
        self._run()
        self.assertEqual(Post.objects.count(), 2)
        for post in Post.objects.all():
            self.assertEqual(post.audience, Post.Audience.PUBLIC)
            self.assertEqual(post.approval_status, Post.ApprovalStatus.NOT_REQUIRED)
            self.assertEqual(post.author.full_name, 'LegacyLink Africa')
        self.assertEqual(IngestedItem.objects.filter(source=IngestedItem.Source.NECTA_NEWS).count(), 2)

    @patch('ingestion.management.commands.ingest_necta_news.fetch_news_html')
    def test_second_run_does_not_repost(self, mock_fetch):
        mock_fetch.return_value = NECTA_SAMPLE_HTML
        self._run()
        output = self._run()
        self.assertIn('0 new', output)
        self.assertEqual(Post.objects.count(), 2)  # unchanged


RELIEFWEB_SAMPLE_PAYLOAD = {
    'count': 2,
    'totalCount': 2,
    'data': [
        {
            'id': '4123456',
            'fields': {
                'title': 'Monitoring & Evaluation Officer',
                'body': 'Full job description text here.',
                'url': 'https://reliefweb.int/job/4123456/monitoring-evaluation-officer',
                'source': [{'name': 'UNDP', 'shortname': 'UNDP'}],
                'country': [{'name': 'United Republic of Tanzania'}],
                'city': [{'name': 'Dar es Salaam'}],
                'date': {'created': '2026-09-01T00:00:00+00:00', 'closing': '2026-10-01T00:00:00+00:00'},
            },
        },
        {
            'id': '4123457',
            'fields': {
                'title': 'Programme Associate',
                # No body/source/country/city on this one — must not crash.
                'url': 'https://reliefweb.int/job/4123457/programme-associate',
            },
        },
        {
            # Missing title entirely — should be skipped, not crash the batch.
            'id': '4123458',
            'fields': {'url': 'https://reliefweb.int/job/4123458/no-title'},
        },
    ],
}


class ReliefWebParsingTests(TestCase):
    def test_parses_full_and_sparse_rows_skips_titleless_row(self):
        items = parse_jobs_response(RELIEFWEB_SAMPLE_PAYLOAD)
        self.assertEqual(len(items), 2)

        full = items[0]
        self.assertEqual(full.external_id, '4123456')
        self.assertEqual(full.title, 'Monitoring & Evaluation Officer')
        self.assertEqual(full.organization, 'UNDP')
        self.assertEqual(full.location, 'Dar es Salaam, United Republic of Tanzania')
        self.assertEqual(full.closing_date.year, 2026)
        self.assertEqual(full.closing_date.month, 10)

        sparse = items[1]
        self.assertEqual(sparse.external_id, '4123457')
        self.assertEqual(sparse.organization, '')
        self.assertEqual(sparse.location, '')
        self.assertIsNone(sparse.closing_date)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ReliefWebIngestCommandTests(TestCase):
    def _run(self, *args):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('ingest_reliefweb_jobs', *args, stdout=out)
        return out.getvalue()

    def test_missing_appname_raises_clear_command_error(self):
        from django.core.management import CommandError
        with self.settings(RELIEFWEB_APPNAME=''):
            with self.assertRaises(CommandError) as ctx:
                self._run('--dry-run')
        self.assertIn('RELIEFWEB_APPNAME', str(ctx.exception))
        self.assertEqual(Opportunity.objects.count(), 0)

    @override_settings(RELIEFWEB_APPNAME='test-app')
    @patch('ingestion.reliefweb.requests.get')
    def test_dry_run_creates_nothing(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = RELIEFWEB_SAMPLE_PAYLOAD
        mock_get.return_value.raise_for_status.return_value = None
        output = self._run('--dry-run')
        self.assertIn('2 new', output)
        self.assertEqual(Opportunity.objects.count(), 0)

    @override_settings(RELIEFWEB_APPNAME='test-app')
    @patch('ingestion.reliefweb.requests.get')
    def test_creates_job_opportunities_posted_by_system_account(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = RELIEFWEB_SAMPLE_PAYLOAD
        mock_get.return_value.raise_for_status.return_value = None
        self._run()
        self.assertEqual(Opportunity.objects.count(), 2)
        for opp in Opportunity.objects.all():
            self.assertEqual(opp.type, 'job')
            self.assertEqual(opp.posted_by.full_name, 'LegacyLink Africa')
            self.assertTrue(opp.is_active)

    @override_settings(RELIEFWEB_APPNAME='test-app')
    @patch('ingestion.reliefweb.requests.get')
    def test_second_run_does_not_redupe(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = RELIEFWEB_SAMPLE_PAYLOAD
        mock_get.return_value.raise_for_status.return_value = None
        self._run()
        output = self._run()
        self.assertIn('0 new', output)
        self.assertEqual(Opportunity.objects.count(), 2)

    @override_settings(RELIEFWEB_APPNAME='not-yet-approved')
    @patch('ingestion.reliefweb.requests.get')
    def test_403_response_raises_reliefweb_not_configured(self, mock_get):
        from django.core.management import CommandError
        mock_get.return_value.status_code = 403
        mock_get.return_value.text = (
            '{"error":{"message":"You are not using an approved appname."}}'
        )
        with self.assertRaises(CommandError) as ctx:
            self._run('--dry-run')
        self.assertIn('403', str(ctx.exception))
        self.assertEqual(Opportunity.objects.count(), 0)


class SystemAuthorTests(TestCase):
    def test_get_or_create_is_idempotent_and_unusable_password(self):
        first = get_system_author()
        second = get_system_author()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(User.objects.filter(full_name='LegacyLink Africa').count(), 1)
        self.assertFalse(first.has_usable_password())

    def test_system_account_cannot_authenticate(self):
        get_system_author()
        self.assertFalse(
            self.client.login(username='system+content@legacylinkafrica.local', password='anything')
        )
