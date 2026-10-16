"""'My school isn't listed' requests: validation, duplicate detection and the
admin's approve / reject outcomes. The endpoint (config.views.school_request)
and the admin actions (alumni.admin) both go through here."""
import re

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from notifications.models import Notification
from notifications.services import notify

from .models import School, SchoolAlias, SchoolRequest
from .search import query_tokens, search_schools

# Which User field holds the school for each School.school_type.
USER_FIELD_BY_TYPE = {
    'primary': 'primary_school',
    'secondary': 'secondary_school',
    'high_school': 'high_school',
    'university': 'tertiary_school',
}

NAME_MIN, NAME_MAX = 3, 200
PLACE_MAX = 100


class InvalidRequest(Exception):
    pass


class AlreadyListed(Exception):
    def __init__(self, matches):
        super().__init__('already listed')
        self.matches = matches


def _clean(text, limit):
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text or '')
    return re.sub(r'\s+', ' ', text).strip()[:limit]


def _same_place(a, b):
    a, b = (a or '').strip().lower(), (b or '').strip().lower()
    return not a or not b or a == b


def listed_matches(name, school_type, region=''):
    """Existing schools of this type that ARE the requested school: same name
    once filler words/case/punctuation are ignored, and a compatible region
    (an unknown region on either side is compatible, so "Njiro" with no
    region still points at the existing "Njiro" rows instead of piling up a
    third)."""
    wanted = query_tokens(name, school_type)
    if not wanted:
        return []
    return [
        s for s in search_schools(name, school_type, limit=20)
        if (query_tokens(s.name, school_type) == wanted
            or any(query_tokens(a.alias, school_type) == wanted for a in s.aliases.all()))
        and _same_place(s.region, region)
    ]


class RateLimited(Exception):
    pass


def create_request(user, school_type, name, region='', district='', rate_limited=None):
    """Returns (SchoolRequest, created). Raises InvalidRequest / AlreadyListed /
    RateLimited. `rate_limited` is a zero-argument callable consulted only
    when a NEW request would be stored, so a rejected or duplicate attempt
    never uses up the user's allowance."""
    if school_type not in dict(School.TYPE_CHOICES):
        raise InvalidRequest('Choose what kind of school this is.')
    name = _clean(name, NAME_MAX)
    if len(name) < NAME_MIN or not re.search(r'[^\W\d_]', name):
        raise InvalidRequest('Please type the school\'s name.')
    region, district = _clean(region, PLACE_MAX), _clean(district, PLACE_MAX)

    matches = listed_matches(name, school_type, region)
    if matches:
        raise AlreadyListed(matches)

    wanted = query_tokens(name, school_type)
    for pending in SchoolRequest.objects.filter(user=user, school_type=school_type, status=SchoolRequest.Status.PENDING):
        if query_tokens(pending.name, school_type) == wanted and _same_place(pending.region, region):
            return pending, False
    if rate_limited is not None and rate_limited():
        raise RateLimited()
    request = SchoolRequest.objects.create(
        user=user, school_type=school_type, name=name, region=region, district=district,
    )
    return request, True


def _unique_slug(name, school_type):
    base = slugify(f'{name}-{school_type}')[:280] or school_type
    slug, n = base, 2
    while School.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


def _link_to_requester(request, school):
    """Fill the requester's own school field -- only if it's still empty, so a
    choice they made in the meantime is never overwritten. Their completion
    year was saved independently, so it lines up as soon as the school does."""
    field = USER_FIELD_BY_TYPE[request.school_type]
    user = request.user
    if getattr(user, field) is None:
        setattr(user, field, school)
        user.save(update_fields=[field])


def _resolve(request, status, school, resolved_by, note=''):
    request.status = status
    request.resolved_school = school
    request.resolved_by = resolved_by
    request.resolved_at = timezone.now()
    if note:
        request.admin_note = note[:300]
    request.save()


def approve_as_new_school(request, resolved_by):
    """Create the school as requested. Refuses (InvalidRequest) when it is
    already on the list -- use approve_as_existing so the requester's
    spelling becomes an alias instead of a duplicate row."""
    if request.status != SchoolRequest.Status.PENDING:
        raise InvalidRequest('Already resolved.')
    existing = listed_matches(request.name, request.school_type, request.region)
    if existing:
        raise InvalidRequest(f'Already on the list as "{existing[0].name}" -- approve it as that school instead.')
    with transaction.atomic():
        school = School.objects.create(
            name=request.name, school_type=request.school_type, region=request.region,
            district=request.district, slug=_unique_slug(request.name, request.school_type),
        )
        _link_to_requester(request, school)
        _resolve(request, SchoolRequest.Status.APPROVED, school, resolved_by)
    _notify_approved(request, school, resolved_by)
    return school


def approve_as_existing(request, school, resolved_by):
    """Point the request at a school that's already listed, and remember the
    requested spelling as an alias so the next person who types it finds it."""
    if request.status != SchoolRequest.Status.PENDING:
        raise InvalidRequest('Already resolved.')
    if school.school_type != request.school_type:
        raise InvalidRequest('The chosen school is a different type from the request.')
    with transaction.atomic():
        known = {school.name.lower()} | {a.lower() for a in school.aliases.values_list('alias', flat=True)}
        if request.name.lower() not in known:
            SchoolAlias.objects.create(school=school, alias=request.name)
        _link_to_requester(request, school)
        _resolve(request, SchoolRequest.Status.APPROVED, school, resolved_by)
    _notify_approved(request, school, resolved_by)
    return school


def reject(request, resolved_by, note=''):
    if request.status != SchoolRequest.Status.PENDING:
        raise InvalidRequest('Already resolved.')
    _resolve(request, SchoolRequest.Status.REJECTED, None, resolved_by, note)
    notify(
        request.user, Notification.Verb.SCHOOL_REQUEST_REJECTED, actor=resolved_by, target=request,
        push_title='LegacyLink Africa', push_body=f'We couldn\'t add "{request.name}" to the school list.',
    )


def _notify_approved(request, school, resolved_by):
    notify(
        request.user, Notification.Verb.SCHOOL_REQUEST_APPROVED, actor=resolved_by, target=request,
        push_title='LegacyLink Africa', push_body=f'"{school.name}" is now on your school list.',
    )
