"""Scrapes https://www.necta.go.tz/news/all — NECTA publishes exam
timetables, registration notices, and results-release announcements there
as static server-rendered HTML (verified 2026-09-11; article markup:
<article class="entry"><h2 class="entry-title"><a href="/news/read/ID">).
No official API or RSS feed exists for this site, so this depends on that
markup shape staying stable — see parse_news_html's per-article try/except
for how a redesign degrades (skips the unparseable article, logs it, rather
than crashing the whole run)."""
import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

logger = logging.getLogger(__name__)

NECTA_BASE_URL = 'https://www.necta.go.tz'
NECTA_NEWS_URL = f'{NECTA_BASE_URL}/news/all'
REQUEST_TIMEOUT = 15
USER_AGENT = 'LegacyLinkAfrica-NewsBot/1.0 (+https://legacylinkafrica.app; contact via app feedback)'


class NectaNewsItem:
    __slots__ = ('external_id', 'title', 'summary', 'published_at', 'url')

    def __init__(self, external_id, title, summary, published_at, url):
        self.external_id = external_id
        self.title = title
        self.summary = summary
        self.published_at = published_at
        self.url = url


def fetch_news_html(page=1):
    """Fetches one page of the news listing. Raises requests.RequestException
    on a network/HTTP failure — callers decide how to handle that (the
    management command logs and continues to the next page rather than
    aborting the whole run over one bad page)."""
    params = {'page': page} if page > 1 else {}
    response = requests.get(
        NECTA_NEWS_URL, params=params, timeout=REQUEST_TIMEOUT,
        headers={'User-Agent': USER_AGENT},
    )
    response.raise_for_status()
    return response.text


def parse_news_html(html):
    """Parses one news-listing page into NectaNewsItems, newest first (the
    site's own order). Skips (and logs) any <article> that doesn't match
    the expected shape instead of raising, so one malformed entry can't
    sink the whole ingestion run."""
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for article in soup.select('article.entry'):
        try:
            items.append(_parse_article(article))
        except Exception:
            logger.exception('Failed to parse a NECTA news <article> — skipping it')
    return items


def _parse_article(article):
    title_link = article.select_one('.entry-title a')
    if title_link is None or not title_link.get('href'):
        raise ValueError('article has no title link')
    href = title_link['href']
    title = title_link.get_text(strip=True)
    if not title:
        raise ValueError('article has no title text')

    match = re.search(r'/news/read/(\d+)', href)
    if match:
        # A regular announcement — internal article page.
        external_id = match.group(1)
        url = href if href.startswith('http') else f'{NECTA_BASE_URL}{href}'
    elif href.startswith('http'):
        # Results-release announcements ("MATOKEO YA...") link straight out
        # to the separate results portal (matokeo.necta.go.tz) instead of
        # an internal /news/read/ article. That URL is itself stable and
        # unique per exam/year, so use it directly as the dedup key.
        external_id = href
        url = href
    else:
        raise ValueError(f'unrecognized NECTA article link shape: {href}')

    time_tag = article.select_one('.entry-meta time')
    published_at = _parse_datetime(time_tag.get_text(strip=True)) if time_tag else None

    summary_p = article.select_one('.entry-content p')
    summary = summary_p.get_text(strip=True) if summary_p else ''

    return NectaNewsItem(
        external_id=external_id, title=title, summary=summary,
        published_at=published_at, url=url,
    )


def _parse_datetime(text):
    """NECTA's <time datetime="..."> attribute is a static placeholder
    ("2020-01-01") on every article as of 2026-09-11 — the real date only
    exists in the tag's visible text, e.g. 'Jul 16, 2026 13:25'."""
    try:
        naive = datetime.strptime(text, '%b %d, %Y %H:%M')
    except ValueError:
        return None
    return timezone.make_aware(naive)
