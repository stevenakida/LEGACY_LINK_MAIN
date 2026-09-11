from unittest.mock import patch

from django.test import TestCase

from .models import User

# View-level password-reset / email-linking tests live in config/tests.py
# (that's where forgot_password, profile_edit, and verify_email_confirm are
# defined). These cover the User model helpers directly.


class EligibleResetEmailTests(TestCase):
    def test_email_registered_user_is_always_eligible(self):
        user = User.objects.create_user('someone@example.com', 'pass1234', full_name='Someone')
        self.assertEqual(user.eligible_reset_email(), 'someone@example.com')

    def test_phone_only_user_with_no_profile_email_is_not_eligible(self):
        user = User.objects.create_user('0711223344', 'pass1234', full_name='Phone Only')
        self.assertIsNone(user.eligible_reset_email())

    def test_phone_only_user_with_unverified_profile_email_is_not_eligible(self):
        user = User.objects.create_user('0711223345', 'pass1234', full_name='Phone Only')
        user.email = 'added@example.com'
        user.save()
        self.assertIsNone(user.eligible_reset_email())

    def test_phone_only_user_with_verified_profile_email_is_eligible(self):
        user = User.objects.create_user('0711223346', 'pass1234', full_name='Phone Only')
        user.email = 'added@example.com'
        user.email_verified = True
        user.save()
        self.assertEqual(user.eligible_reset_email(), 'added@example.com')


class FindByEmailIdentifierTests(TestCase):
    def test_matches_login_identifier(self):
        user = User.objects.create_user('someone@example.com', 'pass1234', full_name='Someone')
        self.assertEqual(User.find_by_email_identifier('someone@example.com'), user)
        self.assertEqual(User.find_by_email_identifier('SOMEONE@EXAMPLE.COM'), user)

    def test_matches_profile_email(self):
        user = User.objects.create_user('0711223344', 'pass1234', full_name='Phone Only')
        user.email = 'added@example.com'
        user.save()
        self.assertEqual(User.find_by_email_identifier('added@example.com'), user)

    def test_no_match_returns_none(self):
        self.assertIsNone(User.find_by_email_identifier('nobody@example.com'))


class MeViewEmailUpdateTests(TestCase):
    """Mobile API parity with config.views.profile_edit: PATCH /api/auth/me/
    must apply the same validate/normalize/dedupe/re-verify rules to `email`
    as the web profile-edit form — both now go through
    User.apply_email_update, see accounts/serializers.py."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.user = User.objects.create_user('0722334455', 'pass1234', full_name='Alice')
        self.other = User.objects.create_user('bob@example.com', 'pass1234', full_name='Bob')
        self.client.force_authenticate(user=self.user)

    def _patch(self, data):
        return self.client.patch('/api/auth/me/', data, format='json')

    def test_valid_new_email_is_saved_normalized_and_unverified(self):
        with patch('accounts.serializers.dispatch_email_verification') as mock_dispatch:
            response = self._patch({'email': 'Alice.New@Example.COM'})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice.new@example.com')
        self.assertFalse(self.user.email_verified)
        mock_dispatch.assert_called_once()

    def test_invalid_email_rejects_whole_patch_atomically(self):
        response = self._patch({'email': 'not-an-email', 'bio': 'new bio'})
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')
        self.assertEqual(self.user.bio, '')  # bio also not saved — atomic

    def test_duplicate_email_rejects_whole_patch(self):
        response = self._patch({'email': 'bob@example.com'})
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_unchanged_email_does_not_dispatch_verification(self):
        self.user.email = 'alice@example.com'
        self.user.email_verified = True
        self.user.save()
        with patch('accounts.serializers.dispatch_email_verification') as mock_dispatch:
            response = self._patch({'email': 'alice@example.com', 'bio': 'hi'})
        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_not_called()
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertEqual(self.user.bio, 'hi')

    def test_email_verified_is_read_only(self):
        with patch('accounts.serializers.dispatch_email_verification'):
            response = self._patch({'email': 'alice@example.com', 'email_verified': True})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)  # client-sent True is ignored

    def test_phone_number_updates_normally(self):
        response = self._patch({'phone_number': '0755111222'})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, '0755111222')
