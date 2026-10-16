from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User

from .models import School
from .search import query_tokens, search_schools

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def make_school(name, kind='secondary', **kwargs):
    return School.objects.create(
        name=name, slug=f'{kind}-{name}'.lower().replace(' ', '-').replace("'", ''), school_type=kind, **kwargs
    )


class QueryTokenTests(SimpleTestCase):
    def test_filler_words_are_dropped_for_school_types(self):
        self.assertEqual(query_tokens('Arusha Secondary School', 'secondary'), ['arusha'])
        self.assertEqual(query_tokens('Njiro Hill Primary School', 'primary'), ['njiro', 'hill'])
        self.assertEqual(query_tokens('Enaboishu High School', 'high_school'), ['enaboishu'])

    def test_filler_only_query_falls_back_to_what_was_typed(self):
        # Typing "Primary" on the way to "Primary X" must not blank the list.
        self.assertEqual(query_tokens('primary school', 'primary'), ['primary', 'school'])

    def test_university_names_keep_every_word(self):
        self.assertEqual(query_tokens('University of Dar es Salaam', 'university'),
                         ['university', 'of', 'dar', 'es', 'salaam'])
        self.assertEqual(query_tokens('College of Business Education', 'university'),
                         ['college', 'of', 'business', 'education'])

    def test_punctuation_and_case_are_ignored(self):
        self.assertEqual(query_tokens("  ARUSHA   city boys' ", 'secondary'), ['arusha', 'city', 'boys'])


class SearchSchoolsTests(TestCase):
    def setUp(self):
        self.arusha = make_school('Arusha')
        make_school('Arusha Day')
        make_school("Arusha City Boys'")
        make_school('Njiro', 'secondary')
        self.njiro_hill = make_school('Njiro Hill', 'primary', region='Arusha')
        make_school('Njiro', 'primary', region='Kilimanjaro')

    def names(self, query, kind='secondary', **kw):
        return [s.name for s in search_schools(query, kind, **kw)]

    def test_the_official_full_name_finds_the_bare_name_in_the_list(self):
        # The CEO's own example: stored as "Arusha", typed as "Arusha Secondary School".
        self.assertEqual(self.names('Arusha Secondary School')[0], 'Arusha')

    def test_exact_match_ranks_ahead_of_longer_names(self):
        self.assertEqual(self.names('Arusha'), ['Arusha', 'Arusha Day', "Arusha City Boys'"])

    def test_word_order_does_not_matter(self):
        self.assertEqual(self.names('boys arusha'), ["Arusha City Boys'"])

    def test_partial_words_still_match_while_typing(self):
        self.assertIn('Arusha', self.names('aru'))

    def test_results_are_scoped_to_the_chosen_type(self):
        self.assertEqual([(s.name, s.region) for s in search_schools('njiro', 'primary')],
                         [('Njiro', 'Kilimanjaro'), ('Njiro Hill', 'Arusha')])
        self.assertEqual(self.names('njiro', 'secondary'), ['Njiro'])

    def test_no_type_searches_every_type(self):
        self.assertEqual(len(search_schools('njiro', None)), 3)

    def test_inactive_schools_are_hidden(self):
        School.objects.filter(pk=self.arusha.pk).update(is_active=False)
        self.assertNotIn('Arusha', self.names('Arusha'))

    def test_limit_is_respected(self):
        for i in range(30):
            make_school(f'Mbeya Test {i}')
        self.assertEqual(len(search_schools('mbeya', 'secondary')), 20)
        self.assertEqual(len(search_schools('mbeya', 'secondary', limit=5)), 5)

    def test_blank_query_returns_nothing(self):
        self.assertEqual(search_schools('', 'secondary'), [])
        self.assertEqual(search_schools('   ', 'secondary'), [])


@FAST_HASH
class SchoolSearchEndpointTests(TestCase):
    def setUp(self):
        make_school('Arusha')
        make_school('University of Dar es Salaam (UDSM)', 'university', region='Dar es Salaam')
        self.user = User.objects.create_user(phone_or_email='+255744100001', password='x', full_name='Tester')

    def test_browser_endpoint_requires_login(self):
        response = self.client.get(reverse('school_search'), {'type': 'secondary', 'q': 'Arusha'})
        self.assertEqual(response.status_code, 401)

    def test_browser_endpoint_finds_the_school_by_its_official_name(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('school_search'), {'type': 'secondary', 'q': 'Arusha Secondary School'})
        self.assertEqual([r['name'] for r in response.json()['results']], ['Arusha'])

    def test_browser_endpoint_finds_a_university_by_a_shortened_name(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('school_search'), {'type': 'university', 'q': 'university dar'})
        self.assertEqual([r['name'] for r in response.json()['results']], ['University of Dar es Salaam (UDSM)'])

    def test_browser_endpoint_ignores_an_unknown_type(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('school_search'), {'type': 'nonsense', 'q': 'Arusha'})
        self.assertEqual(response.json(), {'results': []})

    # The mobile API is JWT-only, so these use DRF's client rather than a session login.
    def api(self):
        client = APIClient()
        client.force_authenticate(self.user)
        return client

    def test_mobile_api_uses_the_same_search(self):
        response = self.api().get('/api/alumni/schools/', {'type': 'secondary', 'q': 'Arusha Secondary School'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r['name'] for r in response.json()], ['Arusha'])

    def test_mobile_api_without_a_type_searches_all_types(self):
        response = self.api().get('/api/alumni/schools/', {'q': 'dar es salaam'})
        self.assertEqual([r['name'] for r in response.json()], ['University of Dar es Salaam (UDSM)'])

    def test_mobile_api_blank_query_returns_an_empty_list(self):
        self.assertEqual(self.api().get('/api/alumni/schools/', {'q': ''}).json(), [])
