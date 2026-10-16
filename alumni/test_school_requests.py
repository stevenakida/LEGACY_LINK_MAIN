"""School aliases and the "my school isn't listed" request flow."""
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from notifications.models import Notification

from . import alias_seed, services as school_services
from .models import School, SchoolAlias, SchoolRequest
from .search import search_schools
from .tests import FAST_HASH, make_school


def make_user(ident, name='Requester'):
    return User.objects.create_user(phone_or_email=ident, password='x', full_name=name)


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

class AliasSearchTests(TestCase):
    def setUp(self):
        self.ifm = make_school('Institute of Finance Management - Dar Es Salaam', 'university', region='Dar es Salaam')
        SchoolAlias.objects.create(school=self.ifm, alias='IFM')
        SchoolAlias.objects.create(school=self.ifm, alias='Chuo cha Fedha')
        self.dodoma = make_school('University of Dodoma (UDOM)', 'university', region='Dodoma')
        SchoolAlias.objects.create(school=self.dodoma, alias='Chuo Kikuu cha Dodoma')

    def names(self, query, kind='university'):
        return [s.name for s in search_schools(query, kind)]

    def test_an_acronym_alias_finds_the_school(self):
        self.assertEqual(self.names('IFM'), ['Institute of Finance Management - Dar Es Salaam'])

    def test_a_swahili_alias_finds_the_school(self):
        self.assertEqual(self.names('Chuo Kikuu cha Dodoma'), ['University of Dodoma (UDOM)'])

    def test_alias_words_must_all_match_the_same_alias(self):
        # "fedha" is in one school's alias and "dodoma" in another's: no mixing.
        self.assertEqual(self.names('fedha dodoma'), [])

    def test_a_school_with_several_matching_aliases_is_listed_once(self):
        SchoolAlias.objects.create(school=self.ifm, alias='IFM Dar')
        self.assertEqual(self.names('ifm').count('Institute of Finance Management - Dar Es Salaam'), 1)

    def test_an_exact_alias_outranks_a_longer_name_match(self):
        make_school('IFM Training Centre Unrelated', 'university')
        self.assertEqual(self.names('IFM')[0], 'Institute of Finance Management - Dar Es Salaam')

    def test_aliases_do_not_leak_across_types(self):
        self.assertEqual(self.names('IFM', 'secondary'), [])


class AliasSeedTests(TestCase):
    def test_seed_adds_aliases_by_exact_name_and_is_idempotent(self):
        school = make_school('University of Dodoma (UDOM)', 'university')
        created, missing = alias_seed.seed(School, SchoolAlias)
        self.assertEqual(list(school.aliases.values_list('alias', flat=True)), ['Chuo Kikuu cha Dodoma'])
        self.assertIn('University of Dar es Salaam (UDSM)', missing)   # not in this database: skipped, never invented
        again, _ = alias_seed.seed(School, SchoolAlias)
        self.assertEqual(again, 0)
        self.assertEqual(school.aliases.count(), 1)

    def test_seed_never_attaches_to_a_different_type_with_the_same_name(self):
        make_school('University of Dodoma (UDOM)', 'secondary')
        self.assertEqual(alias_seed.seed(School, SchoolAlias)[0], 0)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

@FAST_HASH
class CreateRequestTests(TestCase):
    def setUp(self):
        self.user = make_user('+255744200001')
        make_school('Arusha')                                          # stored bare, like the real list
        make_school('Njiro', 'primary', region='Kilimanjaro')
        make_school('Njiro Hill', 'primary', region='Arusha')

    def req(self, name, kind='secondary', region='', **kw):
        return school_services.create_request(self.user, kind, name, region, **kw)

    def test_a_new_school_is_stored_pending_with_cleaned_input(self):
        request, created = self.req('  Moshi   Day \n Secondary ', region=' Kilimanjaro ')
        self.assertTrue(created)
        self.assertEqual((request.name, request.region, request.status), ('Moshi Day Secondary', 'Kilimanjaro', 'pending'))

    def test_names_that_are_too_short_or_not_words_are_refused(self):
        for bad in ('', 'ab', '   ', '12345', '!!!'):
            with self.assertRaises(school_services.InvalidRequest):
                self.req(bad)

    def test_an_unknown_type_is_refused(self):
        with self.assertRaises(school_services.InvalidRequest):
            self.req('Moshi Day', kind='nonsense')

    def test_the_official_form_of_a_listed_school_is_caught_as_already_listed(self):
        with self.assertRaises(school_services.AlreadyListed) as ctx:
            self.req('Arusha Secondary School')
        self.assertEqual([s.name for s in ctx.exception.matches], ['Arusha'])

    def test_the_same_name_in_another_region_is_a_different_school(self):
        request, created = self.req('Njiro', 'primary', region='Mara')
        self.assertTrue(created)

    def test_the_same_name_with_no_region_is_treated_as_already_listed(self):
        with self.assertRaises(school_services.AlreadyListed):
            self.req('Njiro', 'primary')

    def test_the_same_name_in_the_same_region_is_already_listed(self):
        with self.assertRaises(school_services.AlreadyListed):
            self.req('njiro', 'primary', region='kilimanjaro')

    def test_an_alias_counts_as_listed(self):
        SchoolAlias.objects.create(school=School.objects.get(name='Arusha'), alias='Arusha Old Boys')
        with self.assertRaises(school_services.AlreadyListed):
            self.req('Arusha Old Boys')

    def test_asking_twice_returns_the_same_pending_request(self):
        first, created_first = self.req('Moshi Day')
        second, created_second = self.req('moshi day secondary school')
        self.assertEqual((created_first, created_second, first.pk), (True, False, second.pk))

    def test_the_rate_limit_is_only_consulted_when_a_new_request_would_be_stored(self):
        calls = []

        def allowed():
            calls.append(1)
            return False

        self.req('Moshi Day', rate_limited=allowed)
        self.req('Moshi Day', rate_limited=allowed)               # duplicate: no check
        with self.assertRaises(school_services.InvalidRequest):
            self.req('x', rate_limited=allowed)                   # invalid: no check
        self.assertEqual(len(calls), 1)
        with self.assertRaises(school_services.RateLimited):
            self.req('Another School', rate_limited=lambda: True)


@FAST_HASH
class ResolveRequestTests(TestCase):
    def setUp(self):
        self.user = make_user('+255744200010')
        self.admin = make_user('+255744200011', 'Admin')
        self.request = SchoolRequest.objects.create(
            user=self.user, school_type='secondary', name='Moshi Day Secondary', region='Kilimanjaro')

    def verbs(self):
        return list(Notification.objects.filter(recipient=self.user).values_list('verb', flat=True))

    def test_approve_as_new_creates_the_school_links_the_requester_and_notifies(self):
        school = school_services.approve_as_new_school(self.request, self.admin)
        self.request.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual((school.name, school.region, school.school_type), ('Moshi Day Secondary', 'Kilimanjaro', 'secondary'))
        self.assertTrue(school.slug)
        self.assertEqual(self.user.secondary_school_id, school.id)
        self.assertEqual((self.request.status, self.request.resolved_school_id), ('approved', school.id))
        self.assertEqual(self.verbs(), [Notification.Verb.SCHOOL_REQUEST_APPROVED])

    def test_a_school_the_user_already_chose_is_not_overwritten(self):
        other = make_school('Chosen Meanwhile')
        self.user.secondary_school = other
        self.user.save()
        school_services.approve_as_new_school(self.request, self.admin)
        self.user.refresh_from_db()
        self.assertEqual(self.user.secondary_school_id, other.id)

    def test_new_schools_with_the_same_name_get_distinct_slugs(self):
        make_school('Moshi Day Secondary', region='Arusha')       # occupies the natural slug, different region
        school_services.approve_as_new_school(self.request, self.admin)
        self.assertEqual(School.objects.filter(name='Moshi Day Secondary').count(), 2)

    def test_approve_as_new_refuses_when_it_is_already_on_the_list(self):
        make_school('Moshi Day Secondary', region='Kilimanjaro')
        with self.assertRaises(school_services.InvalidRequest):
            school_services.approve_as_new_school(self.request, self.admin)
        self.assertEqual(School.objects.filter(name='Moshi Day Secondary').count(), 1)

    def test_approve_as_existing_adds_the_spelling_as_an_alias_and_links(self):
        existing = make_school('Moshi Day')
        school_services.approve_as_existing(self.request, existing, self.admin)
        self.user.refresh_from_db()
        self.assertEqual(self.user.secondary_school_id, existing.id)
        self.assertEqual(list(existing.aliases.values_list('alias', flat=True)), ['Moshi Day Secondary'])
        self.assertEqual([s.name for s in search_schools('Moshi Day Secondary', 'secondary')][:1], ['Moshi Day'])

    def test_approve_as_existing_rejects_a_school_of_another_type(self):
        wrong = make_school('Moshi Day', 'primary')
        with self.assertRaises(school_services.InvalidRequest):
            school_services.approve_as_existing(self.request, wrong, self.admin)

    def test_reject_marks_it_and_notifies_without_creating_anything(self):
        before = School.objects.count()
        school_services.reject(self.request, self.admin, 'Not a real school')
        self.request.refresh_from_db()
        self.assertEqual((self.request.status, self.request.admin_note), ('rejected', 'Not a real school'))
        self.assertEqual(School.objects.count(), before)
        self.assertEqual(self.verbs(), [Notification.Verb.SCHOOL_REQUEST_REJECTED])

    def test_a_resolved_request_cannot_be_resolved_again(self):
        school_services.reject(self.request, self.admin)
        with self.assertRaises(school_services.InvalidRequest):
            school_services.approve_as_new_school(self.request, self.admin)


@FAST_HASH
class SchoolRequestEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user('+255744200020')
        make_school('Arusha')

    def post(self, **data):
        self.client.force_login(self.user)
        return self.client.post(reverse('school_request'), data)

    def test_requires_login_and_post(self):
        self.assertEqual(self.client.post(reverse('school_request'), {}).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('school_request')).status_code, 405)

    def test_a_valid_request_is_stored(self):
        response = self.post(school_type='secondary', name='Moshi Day', region='Kilimanjaro')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'created': True, 'name': 'Moshi Day'})
        self.assertEqual(SchoolRequest.objects.get().user, self.user)

    def test_an_invalid_request_is_a_400_with_a_message(self):
        response = self.post(school_type='secondary', name='x')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_an_already_listed_school_is_a_409_carrying_the_matches(self):
        response = self.post(school_type='secondary', name='Arusha Secondary School')
        self.assertEqual(response.status_code, 409)
        self.assertEqual([m['name'] for m in response.json()['matches']], ['Arusha'])
        self.assertEqual(SchoolRequest.objects.count(), 0)

    @override_settings(RATE_LIMIT_SCHOOL_REQUEST_MAX=1, RATE_LIMIT_SCHOOL_REQUEST_WINDOW_SECONDS=60)
    def test_the_daily_allowance_is_enforced(self):
        self.assertEqual(self.post(school_type='secondary', name='Moshi Day').status_code, 200)
        self.assertEqual(self.post(school_type='secondary', name='Another School').status_code, 429)
        self.assertEqual(SchoolRequest.objects.count(), 1)


@FAST_HASH
class SchoolRequestPagesTests(TestCase):
    def setUp(self):
        self.user = make_user('+255744200030')
        self.client.force_login(self.user)

    def test_profile_edit_shows_the_pending_request_and_the_autocomplete_hook(self):
        SchoolRequest.objects.create(user=self.user, school_type='primary', name='Msasani Hill')
        response = self.client.get(reverse('profile_edit'))
        self.assertContains(response, 'Msasani Hill')
        self.assertContains(response, 'data-request-endpoint="%s"' % reverse('school_request'))

    def test_a_resolved_request_is_no_longer_shown_as_pending(self):
        SchoolRequest.objects.create(
            user=self.user, school_type='primary', name='Msasani Hill', status=SchoolRequest.Status.REJECTED)
        self.assertNotContains(self.client.get(reverse('profile_edit')), 'Msasani Hill')

    def test_notifications_page_words_both_outcomes(self):
        approved = SchoolRequest.objects.create(user=self.user, school_type='primary', name='Msasani Hill')
        rejected = SchoolRequest.objects.create(user=self.user, school_type='primary', name='Not A School')
        Notification.objects.create(recipient=self.user, verb=Notification.Verb.SCHOOL_REQUEST_APPROVED, target=approved)
        Notification.objects.create(recipient=self.user, verb=Notification.Verb.SCHOOL_REQUEST_REJECTED, target=rejected)
        page = self.client.get(reverse('notifications_list'))
        self.assertContains(page, 'is now on the school list')
        self.assertContains(page, 'Msasani Hill')
        self.assertContains(page, 'to the school list')
        self.assertContains(page, 'Not A School')


@FAST_HASH
class SchoolRequestAdminActionTests(TestCase):
    def setUp(self):
        self.staff = make_user('+255744200040', 'Staff')
        self.staff.is_staff = self.staff.is_superuser = True
        self.staff.save()
        self.user = make_user('+255744200041')
        self.request = SchoolRequest.objects.create(
            user=self.user, school_type='secondary', name='Moshi Day', region='Kilimanjaro')
        self.client.force_login(self.staff)

    def run_action(self, action):
        return self.client.post(
            reverse('admin:alumni_schoolrequest_changelist'),
            {'action': action, '_selected_action': [str(self.request.pk)]}, follow=True)

    def test_approve_as_new_action(self):
        self.run_action('approve_as_new')
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'approved')
        self.assertTrue(School.objects.filter(name='Moshi Day', school_type='secondary').exists())

    def test_approve_as_existing_needs_a_chosen_school_first(self):
        response = self.run_action('approve_as_existing')
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'pending')
        self.assertContains(response, 'pick the existing school')

    def test_approve_as_existing_with_a_chosen_school(self):
        existing = make_school('Moshi Day Boys')
        self.request.resolved_school = existing
        self.request.save()
        self.run_action('approve_as_existing')
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'approved')
        self.assertTrue(existing.aliases.filter(alias='Moshi Day').exists())

    def test_reject_action(self):
        self.run_action('reject_requests')
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'rejected')
