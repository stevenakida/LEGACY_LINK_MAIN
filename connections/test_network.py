"""Phase 7: Network (Discover / Connected / Pending) behaviour, integrity and
query-count tests."""
from urllib.parse import unquote

from django.db import connection as db_connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from alumni.models import School
from moderation.models import ContentReport
from notifications.models import Notification

from . import matching as m
from . import services
from .models import Connection, UserRelationshipOverride

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


def school(name, kind='secondary'):
    return School.objects.create(name=name, school_type=kind)


def person(ident, name, **edu):
    return User.objects.create_user(phone_or_email=ident, password='x', full_name=name, **edu)


def bulk_people(n, prefix, **edu):
    users = [
        User(phone_or_email=f'+2557{prefix}{i:05d}', full_name=f'{prefix.upper()} Person {i:02d}', **edu)
        for i in range(n)
    ]
    User.objects.bulk_create(users)
    return list(User.objects.filter(phone_or_email__startswith=f'+2557{prefix}'))


class NetworkBase(TestCase):
    def setUp(self):
        self.arusha = school('Arusha Secondary School')
        self.enab = school('Enaboishu High School', 'high_school')
        self.uni = school('Dar University', 'university')
        self.me = person('+255722000001', 'Stephen Me',
                         secondary_school=self.arusha, secondary_completion_year=2004,
                         high_school=self.enab, high_school_completion_year=2007)
        self.client.force_login(self.me)

    def mk(self, n, name, **edu):
        return person(f'+2557299{n:05d}', name, **edu)

    def fresh_me(self):
        return services.with_education(self.me)

    def page(self, tab='discover', **params):
        params['tab'] = tab
        return self.client.get(reverse('connections'), params)


# ---------------------------------------------------------------------------
# DISCOVER
# ---------------------------------------------------------------------------

@FAST_HASH
class DiscoverTests(NetworkBase):
    def setUp(self):
        super().setUp()
        self.neema = self.mk(1, 'Neema Joseph', secondary_school=self.arusha, secondary_completion_year=2004)
        self.daniel = self.mk(2, 'Daniel Paulo', secondary_school=self.arusha, secondary_completion_year=2007)
        self.halima = self.mk(3, 'Halima Said', high_school=self.enab, high_school_completion_year=2007)
        self.outsider = self.mk(4, 'Outside Person', secondary_school=school('Other Secondary'),
                                secondary_completion_year=2004)

    def groups(self, **kw):
        return services.discover(self.fresh_me(), **kw).groups

    def by_name(self, groups):
        return {g.key: [c.user.full_name for c in g.members] for g in groups}

    def test_same_institution_and_year_is_classmate(self):
        cohort = [g for g in self.groups() if g.institution_id == self.arusha.id and g.mode == 'cohort'][0]
        self.assertEqual([c.user for c in cohort.members], [self.neema])
        self.assertEqual(cohort.members[0].reason.reason_code, m.CLASSMATE)
        self.assertEqual(cohort.members[0].reason.cohort_year, 2004)

    def test_same_o_level_other_year_gets_same_o_level_reason(self):
        other = [g for g in self.groups() if g.institution_id == self.arusha.id and g.mode == 'other'][0]
        self.assertEqual(other.members[0].user, self.daniel)
        self.assertEqual(other.members[0].reason.reason_code, m.SAME_O_LEVEL)
        self.assertEqual(other.members[0].reason.cohort_year, 2007)

    def test_a_level_classmate_lives_in_its_own_group(self):
        g = [g for g in self.groups() if g.institution_id == self.enab.id][0]
        self.assertEqual(g.level, m.A_LEVEL)
        self.assertEqual(g.members[0].reason.reason_code, m.CLASSMATE)

    def test_same_a_level_other_year(self):
        person('+255722900001', 'Late A Level', high_school=self.enab, high_school_completion_year=2009)
        g = [g for g in self.groups() if g.institution_id == self.enab.id and g.mode == 'other'][0]
        self.assertEqual(g.members[0].reason.reason_code, m.SAME_A_LEVEL)

    def test_same_university_and_same_primary_reasons(self):
        prim = school('Primary Z', 'primary')
        self.me.tertiary_school = self.uni
        self.me.tertiary_completion_year = 2015
        self.me.primary_school = prim
        self.me.save()
        person('+255722900002', 'Uni Mate', tertiary_school=self.uni, tertiary_completion_year=2018)
        person('+255722900003', 'Primary Mate', primary_school=prim, primary_completion_year=None)
        reasons = {c.user.full_name: c.reason.reason_code
                   for g in self.groups() for c in g.members}
        self.assertEqual(reasons['Uni Mate'], m.SAME_UNIVERSITY)
        self.assertEqual(reasons['Primary Mate'], m.SAME_PRIMARY)

    def test_candidate_with_missing_year_is_still_discovered_as_same_o_level(self):
        # NULL years must not fall out of the "other years" group at the
        # database level (exclude() on a nullable column is easy to get wrong).
        person('+255722900040', 'No Year Nina', secondary_school=self.arusha)
        group = [g for g in self.groups() if g.institution_id == self.arusha.id and g.mode == 'other'][0]
        reasons = {c.user.full_name: c.reason for c in group.members}
        self.assertEqual(reasons['No Year Nina'].reason_code, m.SAME_O_LEVEL)
        self.assertIsNone(reasons['No Year Nina'].cohort_year)

    def test_different_institution_is_excluded(self):
        names = {c.user.full_name for g in self.groups() for c in g.members}
        self.assertNotIn('Outside Person', names)

    def test_blocked_either_direction_is_excluded(self):
        UserRelationshipOverride.objects.create(actor=self.me, target=self.neema, type='block')
        UserRelationshipOverride.objects.create(actor=self.daniel, target=self.me, type='block')
        names = {c.user.full_name for g in self.groups() for c in g.members}
        self.assertNotIn('Neema Joseph', names)
        self.assertNotIn('Daniel Paulo', names)

    def test_accepted_connection_is_excluded(self):
        Connection.objects.create(requester=self.me, receiver=self.neema, status='accepted')
        names = {c.user.full_name for g in self.groups() for c in g.members}
        self.assertNotIn('Neema Joseph', names)

    def test_outgoing_pending_stays_visible_as_request_sent(self):
        conn = Connection.objects.create(requester=self.me, receiver=self.neema)
        cand = [c for g in self.groups() for c in g.members if c.user == self.neema][0]
        self.assertTrue(cand.request_sent)
        self.assertEqual(cand.connection_id, conn.id)
        self.assertContains(self.page(), 'Request Sent')

    def test_incoming_pending_is_not_offered_a_connect_button(self):
        Connection.objects.create(requester=self.neema, receiver=self.me)
        names = {c.user.full_name for g in self.groups() for c in g.members}
        self.assertNotIn('Neema Joseph', names)

    def test_declined_and_dismissed_people_are_excluded(self):
        Connection.objects.create(requester=self.neema, receiver=self.me, status='declined')
        services.dismiss_suggestion(self.me, self.daniel.id)
        names = {c.user.full_name for g in self.groups() for c in g.members}
        self.assertNotIn('Neema Joseph', names)
        self.assertNotIn('Daniel Paulo', names)

    def test_inactive_and_self_excluded(self):
        self.neema.is_active = False
        self.neema.save()
        names = {c.user.full_name for g in self.groups() for c in g.members}
        self.assertNotIn('Neema Joseph', names)
        self.assertNotIn('Stephen Me', names)

    def test_accepting_removes_person_from_discover(self):
        conn = Connection.objects.create(requester=self.neema, receiver=self.me)
        services.respond_to_request(self.me, conn.id, 'accept')
        names = {c.user.full_name for g in self.groups() for c in g.members}
        self.assertNotIn('Neema Joseph', names)

    def test_group_order_is_my_classes_before_other_years(self):
        modes = [g.mode for g in self.groups()]
        self.assertEqual(modes, sorted(modes, key=lambda x: 0 if x in ('cohort', 'all') else 1))

    def test_record_without_year_yields_a_single_all_years_group(self):
        me = person('+255722900010', 'No Year', secondary_school=self.arusha)
        groups = services.discover(services.with_education(me)).groups
        self.assertEqual([g.mode for g in groups], ['all'])
        self.assertEqual(groups[0].total, 3)   # Neema, Daniel and Stephen all attended Arusha

    # -- search ---------------------------------------------------------
    def test_search_by_name(self):
        names = {c.user.full_name for g in self.groups(q='neema') for c in g.members}
        self.assertEqual(names, {'Neema Joseph'})

    def test_search_by_institution_returns_that_institutions_alumni(self):
        names = {c.user.full_name for g in self.groups(q='Arusha Sec') for c in g.members}
        self.assertEqual(names, {'Neema Joseph', 'Daniel Paulo'})

    def test_search_by_cohort_year(self):
        names = {c.user.full_name for g in self.groups(q='2007') for c in g.members}
        self.assertEqual(names, {'Daniel Paulo', 'Halima Said'})

    def test_search_through_the_page(self):
        response = self.page(q='Halima')
        self.assertContains(response, 'Halima Said')
        self.assertNotContains(response, 'Neema Joseph')

    # -- filters --------------------------------------------------------
    def test_education_filter(self):
        names = {c.user.full_name for g in self.groups(level_filter='a_level') for c in g.members}
        self.assertEqual(names, {'Halima Said'})
        names = {c.user.full_name for g in self.groups(level_filter='o_level') for c in g.members}
        self.assertEqual(names, {'Neema Joseph', 'Daniel Paulo'})

    def test_invalid_filter_falls_back_to_all(self):
        self.assertEqual(len(self.groups(level_filter='bogus')), len(self.groups()))

    def test_filter_and_search_combine(self):
        names = {c.user.full_name for g in self.groups(level_filter='o_level', q='2007') for c in g.members}
        self.assertEqual(names, {'Daniel Paulo'})

    # -- grouped results / view all --------------------------------------
    def test_groups_are_per_institution_level_and_cohort(self):
        keys = {g.key for g in self.groups()}
        self.assertEqual(keys, {
            f'o_level-{self.arusha.id}-cohort', f'o_level-{self.arusha.id}-other', f'a_level-{self.enab.id}-cohort',
        })

    def test_preview_is_limited_and_view_all_link_shown(self):
        bulk_people(6, 'aa', secondary_school=self.arusha, secondary_completion_year=2004)
        group = [g for g in self.groups() if g.key == f'o_level-{self.arusha.id}-cohort'][0]
        self.assertEqual(group.total, 7)
        self.assertEqual(len(group.members), services.DISCOVER_PREVIEW_SIZE)
        response = self.page()
        self.assertContains(response, reverse('discover_group', args=['o_level', self.arusha.id, 'cohort']))
        self.assertContains(response, '7 alumni found')

    def test_view_all_page_is_paginated(self):
        bulk_people(25, 'ab', secondary_school=self.arusha, secondary_completion_year=2004)
        url = reverse('discover_group', args=['o_level', self.arusha.id, 'cohort'])
        page1 = self.client.get(url)
        self.assertEqual(page1.status_code, 200)
        self.assertEqual(len(page1.context['group'].members), services.PAGE_SIZE)
        self.assertEqual(page1.context['group'].total, 26)
        page2 = self.client.get(url, {'page': 2})
        self.assertEqual(len(page2.context['group'].members), 6)
        self.assertContains(page2, 'Page 2 of 2')

    def test_view_all_page_search_works_with_pagination_state(self):
        bulk_people(25, 'ac', secondary_school=self.arusha, secondary_completion_year=2004)
        url = reverse('discover_group', args=['o_level', self.arusha.id, 'cohort'])
        response = self.client.get(url, {'q': 'neema'})
        self.assertEqual([c.user for c in response.context['group'].members], [self.neema])

    def test_view_all_only_for_groups_in_my_own_journey(self):
        other = school('Not My School')
        for args in (['o_level', other.id, 'cohort'], ['nonsense', self.arusha.id, 'cohort'],
                     ['o_level', self.arusha.id, 'weird'], ['primary', self.arusha.id, 'all']):
            self.assertEqual(self.client.get(reverse('discover_group', args=args)).status_code, 404, args)

    # -- empty states -----------------------------------------------------
    def test_empty_state_uses_real_school_and_class_context(self):
        loner_school = school('Lonely Secondary')
        loner = person('+255722900020', 'Loner', secondary_school=loner_school, secondary_completion_year=2001)
        self.client.force_login(loner)
        response = self.page()
        self.assertContains(response, 'No alumni found yet from')
        self.assertContains(response, 'Lonely Secondary')
        self.assertContains(response, 'Class of 2001')
        self.assertContains(response, 'Invite Classmates')
        self.assertContains(response, 'wa.me')

    def test_no_education_prompts_to_add_it(self):
        self.client.force_login(person('+255722900021', 'Blank'))
        response = self.page()
        self.assertContains(response, 'Add your school to find alumni')
        self.assertContains(response, reverse('profile_edit'))

    def test_search_with_no_results_says_so(self):
        response = self.page(q='zzzzz')
        self.assertContains(response, 'No alumni found for')
        self.assertContains(response, 'Clear search')

    # -- whatsapp ---------------------------------------------------------
    @override_settings(PUBLIC_APP_URL='https://alumni.example.org/')
    def test_invite_uses_configured_public_url_and_school_context(self):
        loner = person('+255722900022', 'Loner2', secondary_school=school('Kilimani Secondary'),
                       secondary_completion_year=1999)
        self.client.force_login(loner)
        response = self.page()
        text = unquote(response.context['invite_url'])
        self.assertIn('Kilimani Secondary', text)
        self.assertIn('Class of 1999', text)
        self.assertIn('https://alumni.example.org', text)
        self.assertNotIn('ondigitalocean', response.content.decode())

    def test_invite_falls_back_to_request_origin_and_carries_no_identifiers(self):
        url = unquote(self.page().context['invite_url'])
        self.assertIn('testserver', url)
        self.assertNotIn(str(self.me.id), url)

    # -- duplicate protection ---------------------------------------------
    def test_second_connect_click_creates_no_duplicate(self):
        url = reverse('send_connection_web', args=[self.neema.id])
        self.client.post(url, {'message': 'hi'})
        self.client.post(url, {'message': 'hi again'})
        self.assertEqual(Connection.objects.filter(requester=self.me, receiver=self.neema).count(), 1)


# ---------------------------------------------------------------------------
# CONNECTED
# ---------------------------------------------------------------------------

@FAST_HASH
class ConnectedTests(NetworkBase):
    def setUp(self):
        super().setUp()
        self.neema = self.mk(1, 'Neema Joseph', secondary_school=self.arusha, secondary_completion_year=2004)
        self.daniel = self.mk(2, 'Daniel Paulo', high_school=self.enab, high_school_completion_year=2007)
        self.stranger = self.mk(3, 'Stranger Nowhere')     # no education at all
        self.c_neema = Connection.objects.create(requester=self.neema, receiver=self.me, status='accepted')
        self.c_daniel = Connection.objects.create(requester=self.me, receiver=self.daniel, status='accepted')
        self.c_stranger = Connection.objects.create(requester=self.me, receiver=self.stranger, status='accepted')

    def cards(self, **params):
        return {c.other.full_name: c for c in self.page('connected', **params).context['page_obj'].object_list}

    def test_accepted_connections_are_listed_with_the_shared_education(self):
        cards = self.cards()
        self.assertEqual(set(cards), {'Neema Joseph', 'Daniel Paulo', 'Stranger Nowhere'})
        self.assertEqual(cards['Neema Joseph'].match.reason_code, m.CLASSMATE)
        self.assertEqual(cards['Neema Joseph'].match.institution_name, 'Arusha Secondary School')
        self.assertEqual(cards['Daniel Paulo'].match.reason_code, m.CLASSMATE)
        self.assertEqual(cards['Daniel Paulo'].match.education_level, m.A_LEVEL)

    def test_page_shows_institution_level_year_and_reason(self):
        response = self.page('connected')
        self.assertContains(response, 'Enaboishu High School')
        self.assertContains(response, 'A-Level · Class of 2007')
        self.assertContains(response, 'Classmate')

    def test_connection_with_missing_year_still_shows_the_shared_school(self):
        nina = self.mk(20, 'Nina NoYear', secondary_school=self.arusha)      # same school, year not entered
        Connection.objects.create(requester=self.me, receiver=nina, status='accepted')
        card = self.cards()['Nina NoYear']
        self.assertEqual(card.match.reason_code, m.SAME_O_LEVEL)
        response = self.page('connected')
        self.assertContains(response, 'Same O-Level')
        self.assertNotContains(response, 'Unknown school')

    def test_never_shows_unknown_school(self):
        self.assertNotContains(self.page('connected'), 'Unknown school')
        self.assertContains(self.page('connected'), 'Education not yet added')

    def test_connection_without_shared_school_shows_their_own_real_record(self):
        elsewhere = person('+255722900030', 'Elsewhere', secondary_school=school('Faraway Secondary'),
                           secondary_completion_year=1990)
        Connection.objects.create(requester=self.me, receiver=elsewhere, status='accepted')
        card = self.cards()['Elsewhere']
        self.assertIsNone(card.match)
        self.assertEqual(card.fallback.institution_name, 'Faraway Secondary')
        response = self.page('connected')
        self.assertContains(response, 'Faraway Secondary')
        self.assertNotContains(response, 'Unknown school')

    def test_search_by_name_institution_and_year(self):
        self.assertEqual(set(self.cards(q='neema')), {'Neema Joseph'})
        self.assertEqual(set(self.cards(q='Enaboishu')), {'Daniel Paulo'})
        self.assertEqual(set(self.cards(q='2004')), {'Neema Joseph'})

    def test_education_filters(self):
        self.assertEqual(set(self.cards(level='o_level')), {'Neema Joseph'})
        self.assertEqual(set(self.cards(level='a_level')), {'Daniel Paulo'})
        self.assertEqual(set(self.cards(level='university')), set())
        self.assertEqual(len(self.cards(level='all')), 3)

    def test_search_only_covers_my_own_connections(self):
        self.mk(9, 'Neema Stranger')     # not connected
        self.assertEqual(set(self.cards(q='neema')), {'Neema Joseph'})

    def test_blocked_or_inactive_people_are_hidden_and_not_counted(self):
        UserRelationshipOverride.objects.create(actor=self.me, target=self.neema, type='block')  # inconsistent row on purpose
        self.daniel.is_active = False
        self.daniel.save()
        self.assertEqual(set(self.cards()), {'Stranger Nowhere'})
        self.assertEqual(services.network_state(self.me)['connections_count'], 1)

    def test_message_action_and_profile_link_are_present(self):
        response = self.page('connected')
        self.assertContains(response, reverse('messages_start', args=[self.neema.id]))
        self.assertContains(response, reverse('view_profile', args=[self.neema.id]))
        self.assertContains(response, 'name="source" value="network"')

    def test_message_button_starts_a_conversation(self):
        response = self.client.post(reverse('messages_start', args=[self.neema.id]), {'source': 'network'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/messages/', response.url)

    def test_three_dot_menu_exposes_view_remove_report_block(self):
        response = self.page('connected')
        for needle in (reverse('remove_connection_web', args=[self.c_neema.id]),
                       reverse('report_user_web', args=[self.neema.id]),
                       reverse('block_user_web', args=[self.neema.id]),
                       'More actions for Neema Joseph'):
            self.assertContains(response, needle)

    def test_remove_connection_updates_state_and_counts(self):
        self.assertEqual(self.page('connected').context['connections_count'], 3)
        response = self.client.post(reverse('remove_connection_web', args=[self.c_neema.id]), **AJAX)
        self.assertEqual(response.json()['connections_count'], 2)
        self.assertTrue(response.json()['ok'])
        self.assertFalse(Connection.objects.filter(id=self.c_neema.id).exists())
        self.assertNotIn('Neema Joseph', self.cards())

    def test_removed_person_returns_to_discover_and_can_reconnect(self):
        self.client.post(reverse('remove_connection_web', args=[self.c_neema.id]))
        names = {c.user.full_name for g in services.discover(self.fresh_me()).groups for c in g.members}
        self.assertIn('Neema Joseph', names)

    def test_cannot_remove_someone_elses_connection(self):
        third = self.mk(10, 'Third')
        fourth = self.mk(11, 'Fourth')
        foreign = Connection.objects.create(requester=third, receiver=fourth, status='accepted')
        response = self.client.post(reverse('remove_connection_web', args=[foreign.id]), **AJAX)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Connection.objects.filter(id=foreign.id).exists())

    def test_pending_or_declined_rows_cannot_be_removed_as_connections(self):
        pending = Connection.objects.create(requester=self.me, receiver=self.mk(12, 'Pending Person'))
        self.assertEqual(self.client.post(reverse('remove_connection_web', args=[pending.id]), **AJAX).status_code, 404)

    def test_blocking_from_the_menu_removes_the_connection_and_updates_counts(self):
        self.client.post(reverse('block_user_web', args=[self.neema.id]))
        self.assertNotIn('Neema Joseph', self.cards())
        self.assertEqual(services.network_state(self.me)['connections_count'], 2)

    def test_pagination(self):
        for p in bulk_people(25, 'cc', secondary_school=self.arusha, secondary_completion_year=2004):
            Connection.objects.create(requester=self.me, receiver=p, status='accepted')
        page1 = self.page('connected').context['page_obj']
        self.assertEqual(len(page1.object_list), services.PAGE_SIZE)
        page2 = self.page('connected', page=2).context['page_obj']
        self.assertEqual(len(page2.object_list), 8)
        response = self.page('connected', q='CC', page=1)
        self.assertContains(response, 'Page 1 of 2')
        self.assertContains(response, 'q=CC')

    def test_empty_state_and_grow_footer(self):
        self.client.force_login(self.mk(13, 'Fresh'))
        empty = self.page('connected')
        self.assertContains(empty, 'No connections yet.')
        self.assertContains(empty, 'Discover Alumni')
        self.client.force_login(self.me)
        self.assertContains(self.page('connected'), 'Grow your network')

    def test_no_matches_for_search_shows_a_useful_state(self):
        self.assertContains(self.page('connected', q='nobody-here'), 'No connections match')


# ---------------------------------------------------------------------------
# PENDING
# ---------------------------------------------------------------------------

@FAST_HASH
class PendingTests(NetworkBase):
    def setUp(self):
        super().setUp()
        self.neema = self.mk(1, 'Neema Joseph', secondary_school=self.arusha, secondary_completion_year=2004)
        self.daniel = self.mk(2, 'Daniel Paulo', secondary_school=self.arusha, secondary_completion_year=2004)
        self.c1 = Connection.objects.create(requester=self.neema, receiver=self.me, message='Hi Stephen, same class!')
        self.c2 = Connection.objects.create(requester=self.daniel, receiver=self.me)
        Connection.objects.filter(id=self.c1.id).update(created_at=timezone.now() - timezone.timedelta(days=2))

    def cards(self):
        return list(self.page('pending').context['page_obj'].object_list)

    def test_incoming_requests_are_listed_newest_first(self):
        self.assertEqual([c.other.full_name for c in self.cards()], ['Daniel Paulo', 'Neema Joseph'])

    def test_outgoing_requests_are_not_in_pending_or_its_count(self):
        out = self.mk(3, 'Outgoing Target')
        Connection.objects.create(requester=self.me, receiver=out)
        self.assertNotIn('Outgoing Target', [c.other.full_name for c in self.cards()])
        self.assertEqual(services.network_state(self.me)['pending_count'], 2)

    def test_counts_shown_in_header_and_tab_badge(self):
        response = self.page('pending')
        self.assertEqual(response.context['pending_count'], 2)
        self.assertContains(response, 'id="net-pending-count">2<')
        self.assertContains(response, 'requests waiting for your decision')

    def test_card_shows_education_reason_message_and_age(self):
        response = self.page('pending')
        self.assertContains(response, 'Arusha Secondary School')
        self.assertContains(response, 'Class of 2004')
        self.assertContains(response, 'Classmate')
        self.assertContains(response, 'Hi Stephen, same class!')
        self.assertContains(response, '2\xa0days ago')
        self.assertContains(response, 'Wants to connect with you.')   # Daniel wrote no note

    def test_fresh_request_reads_just_now_not_zero_minutes(self):
        html = self.page('pending').content.decode()
        self.assertIn('Just now', html)
        self.assertNotIn('0\xa0minutes', html)

    def test_message_is_rendered_as_inert_text(self):
        Connection.objects.filter(id=self.c1.id).update(message='<script>alert(1)</script><b>x</b>')
        html = self.page('pending').content.decode()
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)

    def test_profile_can_be_inspected_before_deciding(self):
        self.assertContains(self.page('pending'), reverse('view_profile', args=[self.neema.id]))
        self.assertEqual(self.client.get(reverse('view_profile', args=[self.neema.id])).status_code, 200)

    def test_accept_updates_everything(self):
        response = self.client.post(reverse('respond_connection_web', args=[self.c1.id]), {'action': 'accept'}, **AJAX)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertEqual((body['connections_count'], body['pending_count']), (1, 1))
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, 'accepted')
        self.assertNotIn('Neema Joseph', [c.other.full_name for c in self.cards()])
        connected = self.page('connected').context['page_obj'].object_list
        self.assertEqual([c.other.full_name for c in connected], ['Neema Joseph'])
        self.assertTrue(Notification.objects.filter(
            recipient=self.neema, verb=Notification.Verb.CONNECTION_ACCEPTED, actor=self.me).exists())

    def test_decline_updates_counts_and_does_not_connect(self):
        response = self.client.post(reverse('respond_connection_web', args=[self.c1.id]), {'action': 'decline'}, **AJAX)
        body = response.json()
        self.assertEqual((body['connections_count'], body['pending_count']), (0, 1))
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, 'declined')
        self.assertFalse(Notification.objects.filter(recipient=self.neema, verb='connection_accepted').exists())

    def test_declined_requester_cannot_immediately_retry(self):
        # Existing product policy (documented in Phase 7 report): a decline is final.
        self.client.post(reverse('respond_connection_web', args=[self.c1.id]), {'action': 'decline'})
        self.client.force_login(self.neema)
        response = self.client.post(reverse('send_connection_web', args=[self.me.id]), **AJAX)
        self.assertEqual(response.json()['code'], 'declined')
        self.assertEqual(Connection.objects.filter(requester=self.neema, receiver=self.me).count(), 1)

    def test_stale_request_cannot_be_answered_twice_or_flipped(self):
        url = reverse('respond_connection_web', args=[self.c1.id])
        self.client.post(url, {'action': 'accept'})
        again = self.client.post(url, {'action': 'accept'}, **AJAX)
        flip = self.client.post(url, {'action': 'decline'}, **AJAX)
        self.assertEqual((again.status_code, again.json()['code']), (400, 'already_resolved'))
        self.assertEqual(flip.json()['code'], 'already_resolved')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, 'accepted')
        self.assertEqual(Notification.objects.filter(recipient=self.neema, verb='connection_accepted').count(), 1)

    def test_declined_request_cannot_be_reopened_by_accepting(self):
        url = reverse('respond_connection_web', args=[self.c1.id])
        self.client.post(url, {'action': 'decline'})
        self.assertEqual(self.client.post(url, {'action': 'accept'}, **AJAX).json()['code'], 'already_resolved')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, 'declined')

    def test_only_the_receiver_can_respond(self):
        self.client.force_login(self.daniel)       # a third party, and not the receiver
        response = self.client.post(reverse('respond_connection_web', args=[self.c1.id]), {'action': 'accept'}, **AJAX)
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.neema)        # the requester can't accept their own request either
        response = self.client.post(reverse('respond_connection_web', args=[self.c1.id]), {'action': 'accept'}, **AJAX)
        self.assertEqual(response.status_code, 404)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, 'pending')

    def test_invalid_action_is_rejected(self):
        response = self.client.post(reverse('respond_connection_web', args=[self.c1.id]), {'action': 'nuke'}, **AJAX)
        self.assertEqual(response.json()['code'], 'invalid_action')

    def test_blocking_overrides_a_pending_request(self):
        self.client.post(reverse('block_user_web', args=[self.neema.id]))
        self.assertFalse(Connection.objects.filter(id=self.c1.id).exists())
        response = self.client.post(reverse('respond_connection_web', args=[self.c1.id]), {'action': 'accept'}, **AJAX)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(services.network_state(self.me)['pending_count'], 1)

    def test_backend_refuses_accept_when_a_block_exists_even_if_the_row_survived(self):
        UserRelationshipOverride.objects.create(actor=self.me, target=self.neema, type='block')
        result = services.respond_to_request(self.me, self.c1.id, 'accept')
        self.assertEqual(result.code, 'blocked')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, 'pending')
        self.assertNotIn('Neema Joseph', [c.other.full_name for c in self.cards()])

    def test_safety_menu_has_view_report_block(self):
        response = self.page('pending')
        for needle in (reverse('report_user_web', args=[self.neema.id]),
                       reverse('block_user_web', args=[self.neema.id]), 'More actions for Neema Joseph'):
            self.assertContains(response, needle)

    def test_report_flow_reuses_the_moderation_system(self):
        url = reverse('report_user_web', args=[self.neema.id])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'category': 'harassment', 'description': 'rude', 'next': '/connections/?tab=pending'})
        self.assertEqual(response.status_code, 302)
        report = ContentReport.objects.get()
        self.assertEqual((report.reporter, report.target, report.category), (self.me, self.neema, 'harassment'))
        from moderation.models import ModerationHold
        self.assertTrue(ModerationHold.objects.filter(object_id=self.neema.id, reason='user_report').exists())

    def test_report_rejects_bad_category_and_self_report(self):
        url = reverse('report_user_web', args=[self.neema.id])
        response = self.client.post(url, {'category': 'nonsense'})
        self.assertContains(response, 'Please choose a reason')
        self.assertEqual(ContentReport.objects.count(), 0)
        self.assertEqual(self.client.post(reverse('report_user_web', args=[self.me.id]), {'category': 'spam'}).status_code, 302)
        self.assertEqual(ContentReport.objects.count(), 0)

    def test_report_next_url_cannot_redirect_off_site(self):
        response = self.client.post(reverse('report_user_web', args=[self.neema.id]),
                                    {'category': 'spam', 'next': 'https://evil.example/'})
        self.assertEqual(response.url, reverse('connections'))

    def test_pagination_keeps_newest_first(self):
        for i, p in enumerate(bulk_people(22, 'pp', secondary_school=self.arusha, secondary_completion_year=2004)):
            Connection.objects.create(requester=p, receiver=self.me)
        page = self.page('pending').context['page_obj']
        self.assertEqual(page.paginator.count, 24)
        created = [c.connection.created_at for c in page.object_list]
        self.assertEqual(created, sorted(created, reverse=True))
        self.assertContains(self.page('pending'), 'Page 1 of 2')

    def test_empty_state(self):
        Connection.objects.filter(receiver=self.me).delete()
        response = self.page('pending')
        self.assertContains(response, 'No pending requests.')
        self.assertContains(response, 'show up here')


# ---------------------------------------------------------------------------
# SHARED STATE / HEADER
# ---------------------------------------------------------------------------

@FAST_HASH
class SharedNetworkStateTests(NetworkBase):
    def test_tab_order_and_common_header_on_every_tab(self):
        for tab in ('discover', 'connected', 'pending'):
            html = self.page(tab).content.decode()
            self.assertLess(html.index('>Discover<'), html.index('>Connected<'))
            self.assertLess(html.index('>Connected<'), html.index('Pending\n'))
            self.assertIn('net-connections-count', html)
            self.assertIn('net-pending-count', html)

    def test_default_tab_is_discover_and_bad_tab_falls_back(self):
        self.assertEqual(self.client.get(reverse('connections')).context['tab'], 'discover')
        self.assertEqual(self.client.get(reverse('connections'), {'tab': 'bogus'}).context['tab'], 'discover')

    def test_dashboard_uses_the_same_counts(self):
        a, b = self.mk(1, 'A'), self.mk(2, 'B')
        Connection.objects.create(requester=a, receiver=self.me)
        Connection.objects.create(requester=self.me, receiver=b)           # outgoing: not pending for me
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['pending_count'], 1)
        self.assertEqual(response.context['connections_count'], 0)

    def test_counts_follow_request_accept_decline_remove_and_block(self):
        a, b, c = self.mk(1, 'A'), self.mk(2, 'B'), self.mk(3, 'C')
        state = lambda: services.network_state(self.me)      # noqa: E731
        ra = Connection.objects.create(requester=a, receiver=self.me)
        rb = Connection.objects.create(requester=b, receiver=self.me)
        Connection.objects.create(requester=c, receiver=self.me)
        self.assertEqual(state(), {'connections_count': 0, 'pending_count': 3})
        services.respond_to_request(self.me, ra.id, 'accept')
        self.assertEqual(state(), {'connections_count': 1, 'pending_count': 2})
        services.respond_to_request(self.me, rb.id, 'decline')
        self.assertEqual(state(), {'connections_count': 1, 'pending_count': 1})
        self.client.post(reverse('block_user_web', args=[c.id]))
        self.assertEqual(state(), {'connections_count': 1, 'pending_count': 0})
        services.remove_connection(self.me, ra.id)
        self.assertEqual(state(), {'connections_count': 0, 'pending_count': 0})

    def test_login_required(self):
        self.client.logout()
        for name in ('connections',):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)


# ---------------------------------------------------------------------------
# INTEGRITY (service + web + API)
# ---------------------------------------------------------------------------

@FAST_HASH
class IntegrityTests(NetworkBase):
    def setUp(self):
        super().setUp()
        self.other = self.mk(1, 'Other Person', secondary_school=self.arusha, secondary_completion_year=2004)

    def send(self, target=None, **kw):
        return services.send_request(self.me, (target or self.other).id, **kw)

    def test_happy_path_creates_one_pending_request_and_notifies(self):
        result = self.send(message='hello')
        self.assertTrue(result.ok)
        self.assertEqual(result.connection.message, 'hello')
        self.assertEqual(result.connection.status, 'pending')
        self.assertTrue(Notification.objects.filter(recipient=self.other, verb='connection_request').exists())

    def test_self_request_blocked(self):
        self.assertEqual(services.send_request(self.me, self.me.id).code, 'self')
        self.assertEqual(Connection.objects.count(), 0)

    def test_duplicate_pending_blocked(self):
        self.send()
        self.assertEqual(self.send().code, 'already_pending')
        self.assertEqual(Connection.objects.count(), 1)

    def test_request_to_connected_user_blocked(self):
        Connection.objects.create(requester=self.other, receiver=self.me, status='accepted')
        self.assertEqual(self.send().code, 'already_connected')

    def test_request_when_they_already_asked_me_is_blocked_not_duplicated(self):
        Connection.objects.create(requester=self.other, receiver=self.me)
        self.assertEqual(self.send().code, 'incoming_pending')
        self.assertEqual(Connection.objects.count(), 1)

    def test_request_involving_blocked_user_blocked_both_directions(self):
        UserRelationshipOverride.objects.create(actor=self.other, target=self.me, type='block')
        self.assertEqual(self.send().code, 'blocked')
        UserRelationshipOverride.objects.all().delete()
        UserRelationshipOverride.objects.create(actor=self.me, target=self.other, type='block')
        self.assertEqual(self.send().code, 'blocked')

    def test_request_to_missing_or_inactive_account_blocked(self):
        import uuid
        self.assertEqual(services.send_request(self.me, uuid.uuid4()).code, 'not_found')
        self.other.is_active = False
        self.other.save()
        self.assertEqual(self.send().code, 'not_found')

    def test_message_is_optional_sanitised_and_capped(self):
        self.assertEqual(self.send(message='').connection.message, '')
        Connection.objects.all().delete()
        long = 'x' * 500
        self.assertEqual(len(self.send(message=long).connection.message), services.MESSAGE_MAX_LENGTH)
        self.assertEqual(services.clean_request_message('  a\x00b\x07c \n\n\n\n d  '), 'abc \n\n d')
        self.assertEqual(services.clean_request_message(None), '')

    @override_settings(RATE_LIMIT_CONNECTION_REQUEST_MAX=2, RATE_LIMIT_CONNECTION_REQUEST_WINDOW_SECONDS=600)
    def test_requests_are_rate_limited_but_refusals_do_not_use_quota(self):
        a, b, c = self.mk(2, 'A'), self.mk(3, 'B'), self.mk(4, 'C')
        self.assertEqual(self.send(a).code, 'sent')
        self.assertEqual(self.send(a).code, 'already_pending')     # refused: costs nothing
        self.assertEqual(self.send(b).code, 'sent')
        self.assertEqual(self.send(c).code, 'rate_limited')
        self.assertFalse(Connection.objects.filter(receiver=c).exists())

    def test_unauthenticated_actions_never_mutate(self):
        self.client.logout()
        conn = Connection.objects.create(requester=self.other, receiver=self.me)
        for url, data in ((reverse('send_connection_web', args=[self.other.id]), {}),
                          (reverse('respond_connection_web', args=[conn.id]), {'action': 'accept'}),
                          (reverse('remove_connection_web', args=[conn.id]), {}),
                          (reverse('dismiss_discover_web', args=[self.other.id]), {})):
            self.assertEqual(self.client.post(url, data).status_code, 302)
            self.assertEqual(self.client.post(url, data, **AJAX).status_code, 401)
        conn.refresh_from_db()
        self.assertEqual(conn.status, 'pending')

    def test_get_requests_to_action_urls_change_nothing(self):
        conn = Connection.objects.create(requester=self.other, receiver=self.me)
        self.client.get(reverse('respond_connection_web', args=[conn.id]), {'action': 'accept'})
        self.client.get(reverse('send_connection_web', args=[self.other.id]))
        conn.refresh_from_db()
        self.assertEqual(conn.status, 'pending')
        self.assertEqual(Connection.objects.count(), 1)

    def test_csrf_is_enforced_on_every_action(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.me)
        conn = Connection.objects.create(requester=self.other, receiver=self.me)
        for url in (reverse('send_connection_web', args=[self.other.id]),
                    reverse('respond_connection_web', args=[conn.id]),
                    reverse('remove_connection_web', args=[conn.id]),
                    reverse('dismiss_discover_web', args=[self.other.id]),
                    reverse('network_track_event')):
            self.assertEqual(strict.post(url, {'action': 'accept', 'event': 'whatsapp_invite_clicked'}).status_code, 403, url)
        conn.refresh_from_db()
        self.assertEqual(conn.status, 'pending')

    def test_next_url_cannot_redirect_off_site(self):
        response = self.client.post(reverse('send_connection_web', args=[self.other.id]), {'next': '//evil.example'})
        self.assertEqual(response.url, reverse('connections'))

    def test_dismiss_creates_a_silent_one_sided_decline(self):
        self.client.post(reverse('dismiss_discover_web', args=[self.other.id]))
        conn = Connection.objects.get()
        self.assertEqual((conn.requester, conn.receiver, conn.status), (self.me, self.other, 'declined'))
        self.assertEqual(Notification.objects.count(), 0)

    # -- API ---------------------------------------------------------------
    def api(self, user=None):
        client = APIClient()
        client.force_authenticate(user=user or self.me)
        return client

    def test_api_send_enforces_the_same_rules(self):
        client = self.api()
        url = reverse('send', args=[self.other.id])
        first = client.post(url, {'message': 'hi via api'}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(Connection.objects.get().message, 'hi via api')
        self.assertEqual(client.post(url).status_code, 400)                       # duplicate
        self.assertEqual(client.post(reverse('send', args=[self.me.id])).status_code, 400)   # self
        self.assertEqual(Connection.objects.count(), 1)

    def test_api_reverse_direction_request_is_not_duplicated(self):
        Connection.objects.create(requester=self.other, receiver=self.me)
        self.assertEqual(self.api().post(reverse('send', args=[self.other.id])).status_code, 400)
        self.assertEqual(Connection.objects.count(), 1)

    def test_api_respond_cannot_reopen_or_hijack(self):
        conn = Connection.objects.create(requester=self.other, receiver=self.me)
        url = reverse('respond', args=[conn.id])
        self.assertEqual(self.api(self.other).patch(url, {'action': 'accept'}, format='json').status_code, 404)
        self.assertEqual(self.api().patch(url, {'action': 'accept'}, format='json').status_code, 200)
        self.assertEqual(self.api().patch(url, {'action': 'decline'}, format='json').status_code, 409)
        conn.refresh_from_db()
        self.assertEqual(conn.status, 'accepted')

    def test_api_lists_use_the_shared_definitions(self):
        Connection.objects.create(requester=self.other, receiver=self.me)
        out = self.mk(2, 'Outgoing')
        Connection.objects.create(requester=self.me, receiver=out)
        rows = self.api().get(reverse('connections_api'), {'tab': 'pending'}).json()
        self.assertEqual(len(rows), 1)          # incoming only, as in the web UI


# ---------------------------------------------------------------------------
# PERFORMANCE: query counts must not grow with the number of people shown
# ---------------------------------------------------------------------------

@FAST_HASH
class QueryCountTests(NetworkBase):
    def queries(self, tab, **params):
        with CaptureQueriesContext(db_connection) as ctx:
            response = self.page(tab, **params)
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_discover_query_count_is_constant_in_group_size(self):
        bulk_people(3, 'da', secondary_school=self.arusha, secondary_completion_year=2004)
        small = self.queries('discover')
        bulk_people(15, 'db', secondary_school=self.arusha, secondary_completion_year=2004)
        self.assertEqual(self.queries('discover'), small)
        self.assertLessEqual(small, 20)   # measured: 18

    def test_connected_query_count_is_constant_in_connection_count(self):
        def add(n, prefix):
            for p in bulk_people(n, prefix, secondary_school=self.arusha, secondary_completion_year=2004,
                                 high_school=self.enab, high_school_completion_year=2007):
                Connection.objects.create(requester=self.me, receiver=p, status='accepted')
        add(3, 'ea')
        small = self.queries('connected')
        add(12, 'eb')
        self.assertEqual(self.queries('connected'), small)
        self.assertLessEqual(small, 14)   # measured: 12

    def test_pending_query_count_is_constant_in_request_count(self):
        def add(n, prefix):
            for p in bulk_people(n, prefix, secondary_school=self.arusha, secondary_completion_year=2004):
                Connection.objects.create(requester=p, receiver=self.me, message='hi')
        add(3, 'fa')
        small = self.queries('pending')
        add(12, 'fb')
        self.assertEqual(self.queries('pending'), small)
        self.assertLessEqual(small, 16)   # measured: 14
