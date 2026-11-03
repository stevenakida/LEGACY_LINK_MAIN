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
from datetime import date, datetime, time, timedelta

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

logger = logging.getLogger(__name__)

NECTA_BASE_URL = 'https://www.necta.go.tz'
NECTA_NEWS_URL = f'{NECTA_BASE_URL}/news/all'
REQUEST_TIMEOUT = 15
USER_AGENT = 'LegacyLinkAfrica-NewsBot/1.0 (+https://legacylinkafrica.app; contact via app feedback)'

# The separate results portal stayed up on 2026-11-03 while www.necta.go.tz
# was unreachable on PSLE results day, so it's checked as a second source.
# Its home page lists every result set it still hosts, including ones from
# past years that were never ingested, so only recently dated entries count.
NECTA_PORTAL_URL = 'https://matokeo.necta.go.tz/'
PORTAL_RECENT_DAYS = 14

# Hand-written post text for a results release, keyed on its dedup URL. Takes
# priority over the generated title + link body whichever source finds it.
CURATED_POST_BODIES = {
    'https://matokeo.necta.go.tz/results/2026/psle/psle.htm': (
        'Matokeo ya Darasa la Saba (PSLE) 2026 yametangazwa\n\n'
        'NECTA imetangaza matokeo tarehe 3 Novemba 2026. Ufaulu wa jumla umepanda '
        'hadi 85.22%, kutoka 81.80% mwaka 2025. Watahiniwa 970,876 wamefaulu kwa '
        'madaraja A, B na C.\n\n'
        'Wavulana wamefaulu kwa 86.18% na wasichana kwa 84.43%. Matokeo ya '
        'watahiniwa 31 yamefutwa.\n\n'
        'Angalia matokeo: https://matokeo.necta.go.tz/results/2026/psle/psle.htm'
    ),
}


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


def fetch_portal_html():
    """Fetches the results portal's home page. Raises
    requests.RequestException on a network/HTTP failure, like fetch_news_html."""
    response = requests.get(
        NECTA_PORTAL_URL, timeout=REQUEST_TIMEOUT,
        headers={'User-Agent': USER_AGENT},
    )
    response.raise_for_status()
    return response.text


def parse_portal_html(html, today=None):
    """Parses the results portal's home page into NectaNewsItems, using the
    result URL as external_id — the same dedup key parse_news_html uses for
    results-release announcements, so one release found on both sites only
    posts once. Markup verified 2026-11-03: <div class="latest-news"> holding
    <div class="news-date"><span>Nov</span> 03</div> and <h2 class="news-title"><a>."""
    today = today or timezone.localdate()
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for entry in soup.select('div.latest-news'):
        try:
            items.append(_parse_portal_entry(entry, today))
        except Exception:
            logger.exception('Failed to parse a NECTA results portal entry — skipping it')
    return items


def recent_portal_items(items, today=None):
    """Keeps only entries dated within the last PORTAL_RECENT_DAYS. An entry
    whose date couldn't be established is left out, not assumed new: reposting
    years-old results to the whole feed is worse than missing one."""
    today = today or timezone.localdate()
    cutoff = today - timedelta(days=PORTAL_RECENT_DAYS)
    return [
        item for item in items
        if item.published_at is not None and item.published_at.date() >= cutoff
    ]


def _parse_portal_entry(entry, today):
    title_link = entry.select_one('.news-title a')
    if title_link is None or not title_link.get('href'):
        raise ValueError('portal entry has no title link')
    url = title_link['href']
    title = title_link.get_text(strip=True)
    if not title:
        raise ValueError('portal entry has no title text')

    date_tag = entry.select_one('.news-date')
    published_on = _parse_portal_date(date_tag.get_text(' ', strip=True), url, today) if date_tag else None
    published_at = (
        timezone.make_aware(datetime.combine(published_on, time.min)) if published_on else None
    )
    return NectaNewsItem(external_id=url, title=title, summary='', published_at=published_at, url=url)


def _parse_portal_date(text, url, today):
    """The portal shows only month and day ('Nov 03'), so the year is taken as
    the latest occurrence not after today, then checked against the exam year
    in the URL. Without that check an old entry would look new again every
    year on its anniversary. The exam year may trail by one only for a release
    early in the year (CSEE 2026 results come out in January 2027)."""
    year_match = re.search(r'/results/(\d{4})/', url)
    if year_match is None:
        return None
    try:
        parsed = datetime.strptime(text, '%b %d')
        published_on = date(today.year, parsed.month, parsed.day)
        if published_on > today:
            published_on = date(today.year - 1, parsed.month, parsed.day)
    except ValueError:
        return None

    exam_year = int(year_match.group(1))
    if exam_year == published_on.year:
        return published_on
    if exam_year == published_on.year - 1 and published_on.month <= 3:
        return published_on
    return None


def _parse_datetime(text):
    """NECTA's <time datetime="..."> attribute is a static placeholder
    ("2020-01-01") on every article as of 2026-09-11 — the real date only
    exists in the tag's visible text, e.g. 'Jul 16, 2026 13:25'."""
    try:
        naive = datetime.strptime(text, '%b %d, %Y %H:%M')
    except ValueError:
        return None
    return timezone.make_aware(naive)
