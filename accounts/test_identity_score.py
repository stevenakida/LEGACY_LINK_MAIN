"""Identity score: the icon key and completed-count added for the profile
page's "Complete your profile" task cards, and the compatibility the
dashboard relies on."""
from django.test import TestCase, override_settings

from accounts.models import User
from alumni.models import School

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


@FAST_HASH
class IdentityScoreSuggestionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('+255755000001', 'x', full_name='Ida Score')

    def test_every_suggestion_has_label_points_and_icon(self):
        for suggestion in self.user.identity_score_suggestions:
            self.assertEqual(set(suggestion), {'label', 'points', 'icon'})
            self.assertTrue(suggestion['icon'])

    def test_dashboard_keys_are_still_present(self):
        # dashboard.html reads suggestions.0.label / .points
        first = self.user.identity_score_suggestions[0]
        self.assertIn('label', first)
        self.assertIn('points', first)

    def test_suggestions_are_sorted_by_points_descending(self):
        points = [s['points'] for s in self.user.identity_score_suggestions]
        self.assertEqual(points, sorted(points, reverse=True))
        self.assertEqual(points[0], 20)             # profession is the heaviest item

    def test_new_user_has_nothing_completed(self):
        self.assertEqual(self.user.identity_score, 0)
        self.assertEqual(self.user.identity_score_completed_count, 0)
        self.assertEqual(len(self.user.identity_score_suggestions), len(User.IDENTITY_SCORE_WEIGHTS))

    def test_completed_count_and_score_track_filled_fields(self):
        school = School.objects.create(name='Arusha Secondary', school_type='secondary')
        self.user.bio = 'Hello'
        self.user.secondary_school, self.user.secondary_completion_year = school, 2004
        self.user.current_role = 'Engineer'
        self.assertEqual(self.user.identity_score_completed_count, 3)
        self.assertEqual(self.user.identity_score, 10 + 12 + 20)
        labels = [s['label'] for s in self.user.identity_score_suggestions]
        self.assertNotIn('Add a short bio about yourself', labels)
        self.assertNotIn('Add your profession', labels)

    def test_school_without_a_year_does_not_count_as_complete(self):
        school = School.objects.create(name='No Year Secondary', school_type='secondary')
        self.user.secondary_school = school
        self.assertEqual(self.user.identity_score_completed_count, 0)

    def test_completed_plus_missing_equals_the_total(self):
        self.user.bio = 'Hello'
        total = len(User.IDENTITY_SCORE_WEIGHTS)
        self.assertEqual(self.user.identity_score_completed_count + len(self.user.identity_score_suggestions), total)
