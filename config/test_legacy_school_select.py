"""The old GET /schools/<id>/select/ changed a logged-in user's school from a
plain link (no POST, no CSRF), so any page or message embedding it could
silently change someone's school. Nothing used it, so it was removed; the
profile form is the only way to change a school."""
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from accounts.models import User
from alumni.models import School

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


@FAST_HASH
class LegacySchoolSelectRemovedTests(TestCase):
    def setUp(self):
        self.old = School.objects.create(name='Old School', slug='old-school', school_type='secondary')
        self.other = School.objects.create(name='Other School', slug='other-school', school_type='secondary')
        self.user = User.objects.create_user(
            phone_or_email='+255744400001', password='x', full_name='Tester', secondary_school=self.old)
        self.client.force_login(self.user)

    def test_the_route_no_longer_exists(self):
        with self.assertRaises(NoReverseMatch):
            reverse('select_school', args=[self.other.id])

    def test_visiting_the_old_link_does_not_change_the_school(self):
        for method in (self.client.get, self.client.post):
            response = method('/schools/%d/select/' % self.other.id)
            self.assertEqual(response.status_code, 404)
        self.user.refresh_from_db()
        self.assertEqual(self.user.secondary_school_id, self.old.id)

    def test_changing_a_school_still_works_through_the_profile_form(self):
        response = self.client.post(reverse('profile_edit'), {
            'full_name': 'Tester', 'secondary_school': self.other.id, 'secondary_completion_year': '2004',
        })
        self.assertIn(response.status_code, (200, 302))
        self.user.refresh_from_db()
        self.assertEqual(self.user.secondary_school_id, self.other.id)
