import logging

from .models import ProductEvent

logger = logging.getLogger(__name__)

# Registry of every event name the product may record, grouped by domain.
# Anything not listed is silently dropped, so a typo or a future caller can't
# smuggle arbitrary event names into the table. The table itself is generic
# (name / actor / properties / timestamp); adding an event from any part of
# the app means adding its name to a domain here -- no schema change.
#
# Only the "network" domain is emitted so far (Phase 7). The other domains
# are declared but NOT yet wired to any call site; they exist so those areas
# can start recording without reopening this module's gate.
EVENT_DOMAINS = {
    'network': frozenset({
        'network_opened',
        'discover_opened',
        'discover_search',
        'education_filter_selected',
        'discover_group_view_all',
        'profile_opened_from_network',
        'connection_request_sent',
        'connection_request_accepted',
        'connection_request_declined',
        'connection_removed',
        'connected_message_clicked',
        'whatsapp_invite_clicked',
        'pending_opened',
    }),
    'account': frozenset({'account_created'}),
    'education': frozenset({'education_added'}),
    'matching': frozenset({'classmate_discovered'}),
    'messaging': frozenset({'message_sent'}),
    'posts': frozenset({'post_created'}),
    'opportunities': frozenset({'opportunity_viewed', 'event_rsvp'}),
    'notifications': frozenset({'notification_opened'}),
}
ALLOWED_EVENTS = frozenset().union(*EVENT_DOMAINS.values())
NETWORK_EVENTS = EVENT_DOMAINS['network']

# Events the browser is allowed to report itself (via /connections/track/).
# Everything else is recorded server-side at the moment the action happens.
CLIENT_EVENTS = frozenset({'whatsapp_invite_clicked'})

# Non-sensitive property keys only -- no names, emails, phone numbers,
# request-message text or profile content, ever.
ALLOWED_PROPERTIES = frozenset({
    'tab',
    'education_level',
    'match_reason_code',
    'has_results',
    'result_count_bucket',
})


def count_bucket(n):
    """Coarse bucket so analytics never stores an exact, potentially
    identifying, result count."""
    if n <= 0:
        return '0'
    if n <= 5:
        return '1-5'
    if n <= 20:
        return '6-20'
    return '21+'


def record_event(name, actor=None, **properties):
    """Record an allowlisted event. Never raises: analytics must not be able
    to break a user-facing action."""
    if name not in ALLOWED_EVENTS:
        return None
    clean = {k: v for k, v in properties.items() if k in ALLOWED_PROPERTIES and v is not None}
    try:
        return ProductEvent.objects.create(
            name=name,
            actor=actor if getattr(actor, 'is_authenticated', False) else None,
            properties=clean,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception('Failed to record analytics event %s', name)
        return None
