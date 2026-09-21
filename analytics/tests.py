from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from alumni.models import School
from connections import services
from connections.models import Connection

from .models import ProductEvent
from .services import ALLOWED_PROPERTIES, NETWORK_EVENTS, count_bucket, record_event

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


@FAST_HASH
class RecordEventTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('+255733000001', 'x', full_name='Ann Analyst')

    def test_only_allowlisted_events_are_stored(self):
        self.assertIsNone(record_event('made_up_event', actor=self.user))
        self.assertEqual(ProductEvent.objects.count(), 0)
        self.assertIsNotNone(record_event('network_opened', actor=self.user, tab='discover'))

    def test_only_allowlisted_properties_are_stored(self):
        record_event('discover_search', actor=self.user, has_results=True, result_count_bucket='1-5',
                     full_name='Ann Analyst', email='ann@example.com', phone='+255733000001',
                     message='private note', query='ann')
        props = ProductEvent.objects.get().properties
        self.assertEqual(set(props), {'has_results', 'result_count_bucket'})
        for forbidden in ('full_name', 'email', 'phone', 'message', 'query'):
            self.assertNotIn(forbidden, props)

    def test_property_allowlist_contains_nothing_identifying(self):
        for key in ALLOWED_PROPERTIES:
            for bad in ('name', 'email', 'phone', 'message', 'text', 'query'):
                self.assertNotIn(bad, key)

    def test_all_spec_events_are_registered(self):
        expected = {
            'network_opened', 'discover_opened', 'discover_search', 'education_filter_selected',
            'discover_group_view_all', 'profile_opened_from_network', 'connection_request_sent',
            'connection_request_accepted', 'connection_request_declined', 'connection_removed',
            'connected_message_clicked', 'whatsapp_invite_clicked', 'pending_opened',
        }
        self.assertEqual(NETWORK_EVENTS, expected)

    def test_registry_is_domain_based_not_network_only(self):
        # Events from other product areas are accepted by the same generic
        # table without any schema or gate change.
        for name in ('account_created', 'education_added', 'classmate_discovered', 'message_sent',
                     'post_created', 'opportunity_viewed', 'event_rsvp', 'notification_opened'):
            self.assertIsNotNone(record_event(name, actor=self.user), name)
        self.assertEqual(ProductEvent.objects.count(), 8)
        self.assertIsNone(record_event('not_in_any_domain', actor=self.user))

    def test_count_buckets_are_coarse(self):
        self.assertEqual([count_bucket(n) for n in (0, 1, 5, 6, 20, 21, 500)],
                         ['0', '1-5', '1-5', '6-20', '6-20', '21+', '21+'])

    def test_anonymous_actor_is_stored_as_null(self):
        record_event('network_opened', actor=AnonymousUser())
        self.assertIsNone(ProductEvent.objects.get().actor)


@FAST_HASH
class NetworkEventEmissionTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Arusha Secondary', school_type='secondary')
        self.me = User.objects.create_user('+255733000010', 'x', full_name='Me', secondary_school=self.school,
                                           secondary_completion_year=2004)
        self.other = User.objects.create_user('+255733000011', 'x', full_name='Other Person',
                                              secondary_school=self.school, secondary_completion_year=2004)
        self.client.force_login(self.me)

    def names(self):
        return list(ProductEvent.objects.order_by('created_at').values_list('name', flat=True))

    def test_page_views_emit_events(self):
        self.client.get(reverse('connections'), {'tab': 'discover', 'q': 'other', 'level': 'o_level'})
        self.client.get(reverse('connections'), {'tab': 'pending'})
        names = self.names()
        for expected in ('network_opened', 'discover_opened', 'discover_search',
                         'education_filter_selected', 'pending_opened'):
            self.assertIn(expected, names)

    def test_group_view_all_and_profile_open_events(self):
        self.client.get(reverse('discover_group', args=['o_level', self.school.id, 'cohort']))
        self.client.get(reverse('view_profile', args=[self.other.id]), {'next': '/connections/?tab=discover'})
        self.assertIn('discover_group_view_all', self.names())
        self.assertIn('profile_opened_from_network', self.names())

    def test_action_events_carry_only_safe_properties(self):
        services.send_request(self.me, self.other.id, message='very private words')
        conn = Connection.objects.get()
        services.respond_to_request(self.other, conn.id, 'accept')
        services.remove_connection(self.me, conn.id)
        self.assertEqual(self.names(), ['connection_request_sent', 'connection_request_accepted', 'connection_removed'])
        sent = ProductEvent.objects.get(name='connection_request_sent')
        self.assertEqual(sent.properties, {'education_level': 'O_LEVEL', 'match_reason_code': 'CLASSMATE'})
        dump = ' '.join(str(e.properties) for e in ProductEvent.objects.all())
        for secret in ('very private words', 'Other Person', '+2557330000'):
            self.assertNotIn(secret, dump)

    def test_decline_event(self):
        conn = Connection.objects.create(requester=self.other, receiver=self.me)
        services.respond_to_request(self.me, conn.id, 'decline')
        self.assertIn('connection_request_declined', self.names())

    def test_message_click_event(self):
        Connection.objects.create(requester=self.other, receiver=self.me, status='accepted')
        self.client.post(reverse('messages_start', args=[self.other.id]), {'source': 'network'})
        self.assertIn('connected_message_clicked', self.names())

    def test_client_beacon_accepts_only_client_events(self):
        url = reverse('network_track_event')
        self.assertEqual(self.client.post(url, {'event': 'whatsapp_invite_clicked'}).status_code, 204)
        self.assertEqual(self.client.post(url, {'event': 'connection_request_sent'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'event': 'nonsense'}).status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.names().count('whatsapp_invite_clicked'), 1)
        self.client.logout()
        self.assertEqual(self.client.post(url, {'event': 'whatsapp_invite_clicked'}).status_code, 401)
