"""Phase 7 Network services: relationship state machine, integrity-checked
actions, shared counts and the Discover / Connected / Pending queries.

Everything a Network page needs from the database goes through here so the
web views, the JSON/API views and the tests all enforce the same rules. The
UI is never the security boundary -- every check below is server-side.

Connection state machine (per pair of users, either direction):

    NONE ──send_request──▶ PENDING_OUTGOING (for requester)
                           PENDING_INCOMING (for receiver)
    PENDING_INCOMING ──accept──▶ CONNECTED
    PENDING_INCOMING ──decline─▶ DECLINED   (permanent, existing policy: the
                                             pair never appears in Discover
                                             again and neither can re-request)
    CONNECTED ──remove──▶ NONE              (row deleted; can reconnect)
    any ──block──▶ BLOCKED                  (rows deleted; nothing can happen
                                             until unblocked)
    NONE ──dismiss (Discover ✕)──▶ DECLINED (one-sided, no notification)
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote

from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import User
from analytics.services import count_bucket, record_event
from notifications.models import Notification
from notifications.services import notify
from ratelimiting.services import is_rate_limited

from . import matching
from .models import Connection, UserRelationshipOverride

EDUCATION_SELECT_RELATED = ('primary_school', 'secondary_school', 'high_school', 'tertiary_school')

MESSAGE_MAX_LENGTH = 300
DISCOVER_PREVIEW_SIZE = 4
PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# relationship state
# ---------------------------------------------------------------------------

class RelState:
    SELF = 'self'
    BLOCKED = 'blocked'
    CONNECTED = 'connected'
    PENDING_OUTGOING = 'pending_outgoing'
    PENDING_INCOMING = 'pending_incoming'
    DECLINED = 'declined'
    NONE = 'none'


_STATE_PRIORITY = {
    'accepted': 0,
    'pending': 1,
    'declined': 2,
}


def relationship_between(viewer, other):
    """(state, connection) between two users. Tolerates the legacy case of
    two rows for one pair (one per direction) by letting accepted beat
    pending beat declined."""
    if viewer.id == other.id:
        return RelState.SELF, None
    if UserRelationshipOverride.is_blocked(viewer, other):
        return RelState.BLOCKED, None
    rows = list(Connection.objects.filter(
        Q(requester=viewer, receiver=other) | Q(requester=other, receiver=viewer)
    ))
    if not rows:
        return RelState.NONE, None
    rows.sort(key=lambda c: _STATE_PRIORITY.get(c.status, 9))
    conn = rows[0]
    if conn.status == 'accepted':
        return RelState.CONNECTED, conn
    if conn.status == 'pending':
        state = RelState.PENDING_OUTGOING if conn.requester_id == viewer.id else RelState.PENDING_INCOMING
        return state, conn
    return RelState.DECLINED, conn


def with_education(user):
    """`user` re-fetched with the four School FKs joined, so matching doesn't
    lazy-load them one query at a time."""
    return User.objects.select_related(*EDUCATION_SELECT_RELATED).get(pk=user.pk)


# ---------------------------------------------------------------------------
# counts (one definition shared by every Network page and the dashboard)
# ---------------------------------------------------------------------------

def accepted_connections_qs(user, blocked_ids=None):
    if blocked_ids is None:
        blocked_ids = UserRelationshipOverride.blocked_partner_ids(user)
    return Connection.accepted_between(user).filter(
        requester__is_active=True, receiver__is_active=True,
    ).exclude(requester_id__in=blocked_ids).exclude(receiver_id__in=blocked_ids)


def incoming_pending_qs(user, blocked_ids=None):
    """Requests waiting for `user`'s decision. Outgoing requests are
    deliberately not part of this -- they show as "Request Sent" in Discover."""
    if blocked_ids is None:
        blocked_ids = UserRelationshipOverride.blocked_partner_ids(user)
    return Connection.objects.filter(
        receiver=user, status='pending', requester__is_active=True,
    ).exclude(requester_id__in=blocked_ids)


def network_state(user):
    blocked_ids = UserRelationshipOverride.blocked_partner_ids(user)
    return {
        'connections_count': accepted_connections_qs(user, blocked_ids).count(),
        'pending_count': incoming_pending_qs(user, blocked_ids).count(),
    }


# ---------------------------------------------------------------------------
# actions (all integrity rules live here)
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    ok: bool
    code: str
    connection: Optional[Connection] = None
    other: Optional[User] = None


def clean_request_message(raw):
    """Plain text only: control characters stripped, blank runs collapsed,
    capped at MESSAGE_MAX_LENGTH. Stored as typed and always HTML-escaped on
    output (templates never mark it safe), so markup in it is inert."""
    if not raw:
        return ''
    text = ''.join(ch for ch in str(raw) if ch in '\n' or ch.isprintable())
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text[:MESSAGE_MAX_LENGTH]


def _lock_pair(a_id, b_id):
    """Serialize concurrent writes between the same two users. Row locks on
    Postgres (production); a harmless no-op on SQLite, which already
    serializes writers. Sorted so two opposite-direction requests can't
    deadlock each other."""
    list(User.objects.select_for_update().filter(id__in=[a_id, b_id]).order_by('id').values_list('id', flat=True))


def _match_props(a, b):
    result = matching.match_users(a, b)
    if result is None:
        return {}
    return {
        'education_level': result.best.education_level,
        'match_reason_code': result.best.reason_code,
    }


def send_request(requester, receiver_id, message=''):
    receiver = User.objects.select_related(*EDUCATION_SELECT_RELATED).filter(id=receiver_id).first()
    if receiver is None or not receiver.is_active:
        return ActionResult(False, 'not_found')
    if receiver.id == requester.id:
        return ActionResult(False, 'self', other=receiver)

    with transaction.atomic():
        _lock_pair(requester.id, receiver.id)
        state, existing = relationship_between(requester, receiver)
        if state == RelState.BLOCKED:
            return ActionResult(False, 'blocked', other=receiver)
        if state == RelState.CONNECTED:
            return ActionResult(False, 'already_connected', existing, receiver)
        if state == RelState.PENDING_OUTGOING:
            return ActionResult(False, 'already_pending', existing, receiver)
        if state == RelState.PENDING_INCOMING:
            return ActionResult(False, 'incoming_pending', existing, receiver)
        if state == RelState.DECLINED:
            return ActionResult(False, 'declined', existing, receiver)
        # Checked last so refused attempts never eat into the quota.
        if is_rate_limited(
            requester, 'connection_request',
            limit=settings.RATE_LIMIT_CONNECTION_REQUEST_MAX,
            window_seconds=settings.RATE_LIMIT_CONNECTION_REQUEST_WINDOW_SECONDS,
        ):
            return ActionResult(False, 'rate_limited', other=receiver)
        conn = Connection.objects.create(
            requester=requester, receiver=receiver, message=clean_request_message(message),
        )

    notify(
        receiver, Notification.Verb.CONNECTION_REQUEST, actor=requester, target=conn,
        push_title=requester.full_name, push_body='Sent you a connection request',
    )
    record_event('connection_request_sent', actor=requester, **_match_props(requester, receiver))
    return ActionResult(True, 'sent', conn, receiver)


def respond_to_request(user, connection_id, action):
    if action not in ('accept', 'decline'):
        return ActionResult(False, 'invalid_action')
    with transaction.atomic():
        conn = Connection.objects.select_for_update().select_related('requester', 'receiver').filter(
            id=connection_id,
        ).first()
        # Someone else's request is reported exactly like a missing one, so
        # ids can't be probed.
        if conn is None or conn.receiver_id != user.id or not conn.requester.is_active:
            return ActionResult(False, 'not_found')
        if conn.status != 'pending':
            return ActionResult(False, 'already_resolved', conn, conn.requester)
        if UserRelationshipOverride.is_blocked(user, conn.requester):
            return ActionResult(False, 'blocked', conn, conn.requester)
        conn.status = 'accepted' if action == 'accept' else 'declined'
        conn.save(update_fields=['status', 'updated_at'])

    requester = conn.requester
    if action == 'accept':
        notify(
            requester, Notification.Verb.CONNECTION_ACCEPTED, actor=user, target=conn,
            push_title=user.full_name, push_body='Accepted your connection request',
        )
        record_event('connection_request_accepted', actor=user, **_match_props(user, requester))
    else:
        record_event('connection_request_declined', actor=user, **_match_props(user, requester))
    return ActionResult(True, 'accepted' if action == 'accept' else 'request_declined', conn, requester)


def remove_connection(user, connection_id):
    with transaction.atomic():
        conn = Connection.objects.select_for_update().select_related('requester', 'receiver').filter(
            Q(id=connection_id) & (Q(requester=user) | Q(receiver=user)), status='accepted',
        ).first()
        if conn is None:
            return ActionResult(False, 'not_found')
        other = conn.receiver if conn.requester_id == user.id else conn.requester
        conn.delete()
    record_event('connection_removed', actor=user)
    return ActionResult(True, 'removed', None, other)


def dismiss_suggestion(user, other_id):
    """Discover's ✕ ("not interested"): a one-sided DECLINED row. Nothing is
    sent to the other person."""
    other = User.objects.filter(id=other_id).first()
    if other is None or other.id == user.id:
        return ActionResult(False, 'not_found')
    with transaction.atomic():
        _lock_pair(user.id, other.id)
        state, _existing = relationship_between(user, other)
        if state == RelState.NONE:
            Connection.objects.create(requester=user, receiver=other, status='declined')
    return ActionResult(True, 'dismissed', other=other)


# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------

LEVEL_FILTERS = ['all'] + list(matching.LEVEL_SLUGS)


def normalize_level_filter(raw):
    return raw if raw in matching.LEVEL_SLUGS else 'all'


@dataclass
class DiscoverCandidate:
    user: User
    reason: matching.MatchReason
    request_sent: bool = False
    connection_id: Optional[str] = None


@dataclass
class DiscoverGroup:
    level: str
    institution_id: int
    institution_name: str
    cohort_year: Optional[int]
    mode: str  # 'cohort' (same year), 'other' (other years) or 'all' (no year on my record)
    total: int
    members: List[DiscoverCandidate] = field(default_factory=list)

    @property
    def level_slug(self):
        return matching.SLUG_BY_LEVEL[self.level]

    @property
    def level_label(self):
        return matching.LEVEL_LABELS[self.level]

    @property
    def title(self):
        return self.institution_name

    @property
    def subtitle(self):
        level = self.level_label
        if self.mode == 'cohort':
            return _('%(level)s · Class of %(year)s') % {'level': level, 'year': self.cohort_year}
        if self.mode == 'other':
            return _('%(level)s · Other years') % {'level': level}
        return _('%(level)s · All years') % {'level': level}

    @property
    def key(self):
        return f'{self.level_slug}-{self.institution_id}-{self.mode}'


@dataclass
class DiscoverResult:
    groups: List[DiscoverGroup]
    has_education: bool
    total_candidates: int
    empty_context: Optional[matching.EducationRecord]


def _relationship_sets(user):
    """One query over the user's Connection rows -> the id sets Discover needs."""
    hidden = set()          # accepted, declined/dismissed, incoming pending
    outgoing = {}           # other_id -> connection id (request sent, awaiting reply)
    rows = Connection.objects.filter(Q(requester=user) | Q(receiver=user)).values_list(
        'id', 'requester_id', 'receiver_id', 'status',
    )
    for cid, requester_id, receiver_id, status in rows:
        other_id = receiver_id if requester_id == user.id else requester_id
        if status == 'pending' and requester_id == user.id:
            outgoing[other_id] = cid
        else:
            hidden.add(other_id)
    return hidden, outgoing


def _search_condition(q, record, year_attr):
    q = (q or '').strip()
    if not q:
        return Q()
    # Naming the school itself matches everyone at it; otherwise match the
    # person's name, or an exact 4-digit class year.
    if q.lower() in record.institution_name.lower():
        return Q()
    cond = Q(full_name__icontains=q)
    if q.isdigit() and len(q) == 4:
        cond |= Q(**{year_attr: int(q)})
    return cond


def _group_specs(record, base_qs, year_attr):
    """(mode, queryset) pairs for one of the viewer's education records."""
    if record.cohort_year:
        cohort_qs = base_qs.filter(**{year_attr: record.cohort_year})
        other_qs = base_qs.exclude(**{year_attr: record.cohort_year})
        return [('cohort', cohort_qs), ('other', other_qs)]
    return [('all', base_qs)]


def _base_candidates(user, record, level, hidden_ids, blocked_ids, q):
    school_attr, year_attr = matching.LEVEL_FIELDS[level]
    qs = User.objects.filter(is_active=True, **{f'{school_attr}_id': record.institution_id})
    qs = qs.exclude(id=user.id).exclude(id__in=hidden_ids).exclude(id__in=blocked_ids)
    cond = _search_condition(q, record, year_attr)
    if cond:
        qs = qs.filter(cond)
    return qs.order_by('full_name', 'id'), year_attr


def _candidate(record, mode, member, year_attr, outgoing):
    member_year = getattr(member, year_attr)
    reason = matching.reason_for(
        record.level, record.institution_id, record.institution_name,
        same_cohort=(mode == 'cohort'), other_year=member_year,
    )
    conn_id = outgoing.get(member.id)
    return DiscoverCandidate(member, reason, request_sent=conn_id is not None, connection_id=conn_id)


def discover(user, level_filter='all', q='', preview_size=DISCOVER_PREVIEW_SIZE):
    """Grouped Discover results for `user`. `user` should come from
    `with_education` (or request.user, at the cost of a few lazy loads)."""
    level_filter = normalize_level_filter(level_filter)
    all_records = matching.education_records(user)
    records = all_records
    if level_filter != 'all':
        records = [r for r in records if matching.SLUG_BY_LEVEL[r.level] == level_filter]

    blocked_ids = UserRelationshipOverride.blocked_partner_ids(user)
    hidden_ids, outgoing = _relationship_sets(user)

    groups, total = [], 0
    # Strongest first: my class groups, then "other years" groups; within
    # each, most recent education first (matching.LEVELS order).
    ordered = sorted(records, key=lambda r: matching.LEVEL_ORDER.index(r.level))
    specs = []
    for record in ordered:
        base_qs, year_attr = _base_candidates(user, record, record.level, hidden_ids, blocked_ids, q)
        for mode, qs in _group_specs(record, base_qs, year_attr):
            specs.append((record, mode, qs, year_attr))
    specs.sort(key=lambda s: 0 if s[1] in ('cohort', 'all') else 1)  # stable: keeps level order

    for record, mode, qs, year_attr in specs:
        count = qs.count()
        if not count:
            continue
        members = [
            _candidate(record, mode, m, year_attr, outgoing) for m in qs[:preview_size]
        ]
        groups.append(DiscoverGroup(
            level=record.level, institution_id=record.institution_id,
            institution_name=record.institution_name, cohort_year=record.cohort_year,
            mode=mode, total=count, members=members,
        ))
        total += count

    empty_context = ordered[0] if ordered else None
    return DiscoverResult(groups, bool(all_records), total, empty_context)


def discover_group_page(user, level_slug, institution_id, mode, q='', page=1):
    """One Discover group in full, paginated. Only groups that belong to the
    viewer's own education journey exist -- anything else returns None, so
    this can't be used to browse arbitrary schools."""
    level = matching.LEVEL_SLUGS.get(level_slug)
    if level is None or mode not in ('cohort', 'other', 'all'):
        return None
    record = next(
        (r for r in matching.education_records(user)
         if r.level == level and r.institution_id == institution_id),
        None,
    )
    if record is None:
        return None
    if mode in ('cohort', 'other') and not record.cohort_year:
        return None

    blocked_ids = UserRelationshipOverride.blocked_partner_ids(user)
    hidden_ids, outgoing = _relationship_sets(user)
    base_qs, year_attr = _base_candidates(user, record, level, hidden_ids, blocked_ids, q)
    qs = dict(_group_specs(record, base_qs, year_attr)).get(mode)
    if qs is None:
        return None
    paginator = Paginator(qs, PAGE_SIZE)
    page_obj = paginator.get_page(page)
    members = [_candidate(record, mode, m, year_attr, outgoing) for m in page_obj.object_list]
    group = DiscoverGroup(
        level=level, institution_id=institution_id, institution_name=record.institution_name,
        cohort_year=record.cohort_year, mode=mode, total=paginator.count, members=members,
    )
    return group, page_obj


# ---------------------------------------------------------------------------
# Connected / Pending
# ---------------------------------------------------------------------------

@dataclass
class RelationshipCard:
    """One row on the Connected or Pending tab."""
    connection: Connection
    other: User
    match: Optional[matching.MatchReason]
    fallback: Optional[matching.EducationRecord] = None

    @property
    def has_education(self):
        return self.match is not None or self.fallback is not None

    @property
    def just_now(self):
        return (timezone.now() - self.connection.created_at).total_seconds() < 60


def _other_side(conn, user):
    return conn.receiver if conn.requester_id == user.id else conn.requester


def _card(conn, user, my_records):
    other = _other_side(conn, user)
    their_records = matching.education_records(other)
    result = matching.match_records(my_records, their_records)
    if result is not None:
        return RelationshipCard(conn, other, result.best)
    return RelationshipCard(conn, other, None, matching.fallback_record(other))


def _side_select_related():
    fields = ['requester', 'receiver']
    for side in ('requester', 'receiver'):
        fields.extend(f'{side}__{fk}' for fk in EDUCATION_SELECT_RELATED)
    return fields


def _card_matches_query(card, q):
    q = (q or '').strip().lower()
    if not q:
        return True
    other = card.other
    if q in (other.full_name or '').lower():
        return True
    for record in matching.education_records(other):
        if q in record.institution_name.lower():
            return True
        if q.isdigit() and record.cohort_year and str(record.cohort_year) == q:
            return True
    return False


def connected_page(user, level_filter='all', q='', page=1):
    level_filter = normalize_level_filter(level_filter)
    my_records = matching.education_records(user)
    conns = accepted_connections_qs(user).select_related(*_side_select_related()).order_by('-updated_at', '-created_at')
    cards = [_card(c, user, my_records) for c in conns]
    if level_filter != 'all':
        wanted = matching.LEVEL_SLUGS[level_filter]
        cards = [c for c in cards if c.match and c.match.education_level == wanted]
    cards = [c for c in cards if _card_matches_query(c, q)]
    paginator = Paginator(cards, PAGE_SIZE)
    return paginator.get_page(page)


def pending_page(user, page=1):
    my_records = matching.education_records(user)
    qs = incoming_pending_qs(user).select_related(
        'requester', *(f'requester__{fk}' for fk in EDUCATION_SELECT_RELATED),
    ).order_by('-created_at', '-id')
    paginator = Paginator(qs, PAGE_SIZE)
    page_obj = paginator.get_page(page)
    page_obj.object_list = [_card(c, user, my_records) for c in page_obj.object_list]
    return page_obj


# ---------------------------------------------------------------------------
# WhatsApp invite
# ---------------------------------------------------------------------------

def public_app_url(request):
    configured = (settings.PUBLIC_APP_URL or '').strip()
    return configured.rstrip('/') if configured else request.build_absolute_uri('/').rstrip('/')


def whatsapp_invite_url(request, institution_name=None, cohort_year=None):
    """Prefilled wa.me link. Only the school/year context and the public app
    URL go into the text -- no user ids or other identifiers."""
    url = public_app_url(request)
    if institution_name and cohort_year:
        text = _("I'm reconnecting with alumni from %(school)s, Class of %(year)s on LegacyLink Africa. Join our alumni network here: %(url)s") % {
            'school': institution_name, 'year': cohort_year, 'url': url,
        }
    elif institution_name:
        text = _("I'm reconnecting with alumni from %(school)s on LegacyLink Africa. Join our alumni network here: %(url)s") % {
            'school': institution_name, 'url': url,
        }
    else:
        text = _('Join me on LegacyLink Africa to reconnect with our classmates and alumni: %(url)s') % {'url': url}
    return 'https://wa.me/?text=' + quote(text)


def result_count_bucket(n):
    return count_bucket(n)
