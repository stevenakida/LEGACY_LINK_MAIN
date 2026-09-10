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
