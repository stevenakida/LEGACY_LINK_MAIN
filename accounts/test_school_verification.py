"""The "School Verified" badge means staff checked the school and year -- not
that someone typed them into a profile (CEO checklist item 8)."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from alumni.models import School
from connections.models import Connection

from .models import User

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def make_school(name):
    return School.objects.create(name=name, slug=name.lower().replace(' ', '-'), school_type='secondary')


@FAST_HASH
class BadgeRulesTests(TestCase):
    def setUp(self):
        self.arusha = make_school('Arusha')
        self.viewer = User.objects.create_user(phone_or_email='+255744500001', password='x', full_name='Viewer')
        self.person = User.objects.create_user(
            phone_or_email='+255744500002', password='x', full_name='Complete Profile',
            secondary_school=self.arusha, secondary_completion_year=2004)
        self.client.force_login(self.viewer)

    def public_page(self):
        return self.client.get(reverse('view_profile', args=[self.person.id])).content.decode()

    def test_a_complete_profile_is_not_verified_just_because_it_is_complete(self):
        self.assertFalse(self.person.school_is_verified)
        self.assertNotIn('School Verified', self.public_page())

    def test_a_staff_verified_school_shows_the_badge_on_the_public_profile(self):
        self.person.school_verified_at = timezone.now()
        self.person.save()
        self.assertTrue(self.person.school_is_verified)
        self.assertIn('School Verified', self.public_page())

    def test_the_owner_sees_their_own_badge_only_when_verified(self):
        self.client.force_login(self.person)
        self.assertNotContains(self.client.get(reverse('profile')), 'School Verified')
        self.person.school_verified_at = timezone.now()
        self.person.save()
        self.assertContains(self.client.get(reverse('profile')), 'School Verified')

    def test_having_a_connection_no_longer_earns_a_verified_badge(self):
        Connection.objects.create(requester=self.viewer, receiver=self.person, status='accepted')
        page = self.public_page()
        self.assertNotIn('Community Verified', page)
        self.assertNotIn('School Verified', page)
        self.assertNotIn('verify-badge', page)

    def test_the_timestamp_alone_is_not_enough_without_a_school_and_year(self):
        self.person.school_verified_at = timezone.now()
        self.person.secondary_school = None
        self.person.secondary_completion_year = None
        self.person.save()
        self.assertFalse(self.person.school_is_verified)


@FAST_HASH
class VerificationClearsOnChangeTests(TestCase):
    def setUp(self):
        self.arusha = make_school('Arusha')
        self.other = make_school('Other School')
        self.user = User.objects.create_user(
            phone_or_email='+255744500010', password='x', full_name='Verified Person',
            secondary_school=self.arusha, secondary_completion_year=2004)
        User.objects.filter(pk=self.user.pk).update(school_verified_at=timezone.now())
        self.user.refresh_from_db()

    def reloaded(self):
        return User.objects.get(pk=self.user.pk)

    def test_changing_the_school_clears_it(self):
        self.user.secondary_school = self.other
        self.user.save()
        self.assertIsNone(self.reloaded().school_verified_at)

    def test_changing_the_year_clears_it(self):
        self.user.secondary_completion_year = 2005
        self.user.save()
        self.assertIsNone(self.reloaded().school_verified_at)

    def test_unrelated_changes_keep_it(self):
        self.user.bio = 'new bio'
        self.user.current_role = 'Engineer'
        self.user.save()
        self.assertIsNotNone(self.reloaded().school_verified_at)

    def test_saving_the_same_school_and_year_keeps_it(self):
        self.user.secondary_school = self.arusha
        self.user.secondary_completion_year = 2004
        self.user.save()
        self.assertIsNotNone(self.reloaded().school_verified_at)

    def test_update_fields_that_skip_the_school_keep_it(self):
        self.user.secondary_school = self.other          # changed in memory but not being saved
        self.user.bio = 'saved bio'
        self.user.save(update_fields=['bio'])
        self.assertIsNotNone(self.reloaded().school_verified_at)

    def test_update_fields_that_include_the_school_clear_it_and_persist_that(self):
        self.user.secondary_school = self.other
        self.user.save(update_fields=['secondary_school'])
        reloaded = self.reloaded()
        self.assertEqual(reloaded.secondary_school_id, self.other.id)
        self.assertIsNone(reloaded.school_verified_at)

    def test_the_profile_form_resubmitting_the_same_school_keeps_it(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('profile_edit'), {
            'full_name': 'Verified Person', 'secondary_school': self.arusha.id, 'secondary_completion_year': '2004',
        })
        self.assertIn(response.status_code, (200, 302))
        self.assertIsNotNone(self.reloaded().school_verified_at)

    def test_the_profile_form_switching_school_clears_it(self):
        self.client.force_login(self.user)
        self.client.post(reverse('profile_edit'), {
            'full_name': 'Verified Person', 'secondary_school': self.other.id, 'secondary_completion_year': '2004',
        })
        self.assertIsNone(self.reloaded().school_verified_at)

    def test_a_new_account_starts_unverified(self):
        fresh = User.objects.create_user(phone_or_email='+255744500011', password='x', full_name='Fresh')
        self.assertIsNone(fresh.school_verified_at)


@FAST_HASH
class AdminVerificationActionTests(TestCase):
    def setUp(self):
        self.arusha = make_school('Arusha')
        self.staff = User.objects.create_user(phone_or_email='+255744500020', password='x', full_name='Staff')
        self.staff.is_staff = self.staff.is_superuser = True
        self.staff.save()
        self.complete = User.objects.create_user(
            phone_or_email='+255744500021', password='x', full_name='Has School',
            secondary_school=self.arusha, secondary_completion_year=2004)
        self.no_year = User.objects.create_user(
            phone_or_email='+255744500022', password='x', full_name='No Year', secondary_school=self.arusha)
        self.client.force_login(self.staff)

    def run_action(self, action, *users):
        return self.client.post(
            reverse('admin:accounts_user_changelist'),
            {'action': action, '_selected_action': [str(u.pk) for u in users]}, follow=True)

    def test_verify_marks_complete_profiles_and_skips_incomplete_ones(self):
        response = self.run_action('verify_school', self.complete, self.no_year)
        self.complete.refresh_from_db()
        self.no_year.refresh_from_db()
        self.assertIsNotNone(self.complete.school_verified_at)
        self.assertIsNone(self.no_year.school_verified_at)
        self.assertContains(response, 'skipped')

    def test_unverify_removes_it(self):
        self.run_action('verify_school', self.complete)
        self.run_action('unverify_school', self.complete)
        self.complete.refresh_from_db()
        self.assertIsNone(self.complete.school_verified_at)

    def test_the_user_list_shows_a_verified_column_and_filter(self):
        self.run_action('verify_school', self.complete)
        response = self.client.get(reverse('admin:accounts_user_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'School verified')

    def test_the_user_change_page_opens_with_the_read_only_field(self):
        response = self.client.get(reverse('admin:accounts_user_change', args=[self.complete.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'School verified at')
