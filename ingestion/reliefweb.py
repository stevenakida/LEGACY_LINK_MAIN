"""Fetches Tanzania-filtered job postings from the official ReliefWeb API
(https://apidoc.reliefweb.int/) — humanitarian/UN/NGO/development vacancies.
Verified 2026-09-11 against the live docs and a real (rejected, since no
appname is registered yet) request: ReliefWeb requires a pre-approved
`appname` as of Nov 2025 — an unapproved one gets a 403 with a clear
message, handled below as ReliefWebNotConfigured rather than a raw
HTTPError. See RELIEFWEB_APPNAME in config/settings.py."""
import logging

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

RELIEFWEB_JOBS_URL = 'https://api.reliefweb.int/v2/jobs'
REQUEST_TIMEOUT = 15
COUNTRY = 'Tanzania'

# Dotted paths come back as nested JSON (see _parse_job) — this is the
# ReliefWeb API's own convention, not something we're choosing.
FIELDS_INCLUDE = [
    'title', 'body', 'url', 'url_alias',
    'source.name', 'source.shortname',
    'country.name', 'city.name',
    'date.created', 'date.closing',
]


class ReliefWebJob:
    __slots__ = ('external_id', 'title', 'body', 'organization', 'location', 'url', 'closing_date')

    def __init__(self, external_id, title, body, organization, location, url, closing_date):
        self.external_id = external_id
        self.title = title
        self.body = body
        self.organization = organization
        self.location = location
        self.url = url
        self.closing_date = closing_date


class ReliefWebNotConfigured(Exception):
    """RELIEFWEB_APPNAME is unset, or ReliefWeb rejected it. Request an
    appname at https://apidoc.reliefweb.int/parameters#appname — ReliefWeb
    reviews the request by hand and emails back an approval, so this can't
    be automated; someone has to actually submit that form."""


def fetch_jobs(limit=20):
    appname = settings.RELIEFWEB_APPNAME
    if not appname:
        raise ReliefWebNotConfigured(
            'RELIEFWEB_APPNAME is not set. Request an appname at '
            'https://apidoc.reliefweb.int/parameters#appname (ReliefWeb '
            'reviews the request and emails an approval) and set it as an '
            'env var before this command can fetch anything.'
        )
    params = [
        ('appname', appname),
        ('limit', limit),
        ('sort[]', 'date.created:desc'),
        ('filter[field]', 'country'),
        ('filter[value]', COUNTRY),
    ] + [('fields[include][]', field) for field in FIELDS_INCLUDE]

    response = requests.get(RELIEFWEB_JOBS_URL, params=params, timeout=REQUEST_TIMEOUT)
    if response.status_code == 403:
        raise ReliefWebNotConfigured(
            f'ReliefWeb rejected the request (403) — the appname is likely '
            f'not yet approved. Response: {response.text[:300]}'
        )
    response.raise_for_status()
    return response.json()


def parse_jobs_response(payload):
    items = []
    for row in payload.get('data', []):
        try:
            items.append(_parse_job(row))
        except Exception:
            logger.exception('Failed to parse a ReliefWeb job row (id=%s) — skipping it', row.get('id'))
    return items


def _first_name(value):
    """Several nested ReliefWeb fields (source, country, city) come back as
    a list of {"name": ...} dicts even when there's only one entry — take
    the first. Tolerates a bare dict or string too, in case a field
    doesn't follow that convention."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        return value.get('name', '') or ''
    if isinstance(value, str):
        return value
    return ''


def _parse_job(row):
    external_id = str(row['id'])
    fields = row.get('fields') or {}
    title = (fields.get('title') or '').strip()
    if not title:
        raise ValueError('job row has no title')

    body = (fields.get('body') or '').strip()
    organization = _first_name(fields.get('source'))
    country = _first_name(fields.get('country'))
    city = _first_name(fields.get('city'))
    location = ', '.join(part for part in (city, country) if part)
    url = fields.get('url') or fields.get('url_alias') or ''

    date_field = fields.get('date') or {}
    closing_raw = date_field.get('closing')
    closing_date = parse_datetime(closing_raw) if closing_raw else None

    return ReliefWebJob(
        external_id=external_id, title=title, body=body, organization=organization,
        location=location, url=url, closing_date=closing_date,
    )
