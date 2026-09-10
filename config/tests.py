"""Password reset / email-linking regression tests.

Root-cause bug being guarded against: forgot_password looked up accounts by
`phone_or_email` only, so a user who registered with a phone number and
later added an email from their profile could never be matched — no reset
email was ever generated for them, though the form always reported success.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.core import mail
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.tokens import email_verification_token


class _ImmediateThread:
    """Stand-in for threading.Thread that runs the target synchronously, so
    tests can assert on mail.outbox right after the view call instead of
    racing a background daemon thread."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@contextmanager
def synchronous_email():
    with patch('config.views.threading.Thread', _ImmediateThread):
        yield


class ForgotPasswordTests(TestCase):
    def setUp(self):
        self.phone_user = User.objects.create_user(
            '0712345678', 'pass1234', full_name='Phone Only',
        )
        self.email_user = User.objects.create_user(
            'registered@example.com', 'pass1234', full_name='Email User',
        )

    def _post_forgot(self, email):
        with synchronous_email():
            return self.client.post('/forgot-password/', {'email': email})

    # -- 1. phone-only registration ----------------------------------------
    def test_phone_only_registration_has_no_email(self):
        self.assertEqual(self.phone_user.email, '')
        self.assertFalse(self.phone_user.email_verified)
        self.assertNotIn('@', self.phone_user.phone_or_email)
        self.assertIsNone(self.phone_user.eligible_reset_email())

    # -- 2/3. adding email later / it becomes findable ----------------------
    def test_adding_email_later_is_found_by_lookup_but_not_yet_eligible(self):
        self.client.force_login(self.phone_user)
        with synchronous_email():
            self.client.post('/profile/edit/', {
                'full_name': 'Phone Only', 'email': 'phoneuser@example.com',
            })
        self.phone_user.refresh_from_db()
        self.assertEqual(self.phone_user.email, 'phoneuser@example.com')
        self.assertFalse(self.phone_user.email_verified)
        found = User.find_by_email_identifier('phoneuser@example.com')
        self.assertEqual(found, self.phone_user)
        # Not eligible yet — unverified.
        self.assertIsNone(self.phone_user.eligible_reset_email())

    # -- 4. reset works after adding AND verifying the email -----------------
    def test_reset_succeeds_after_email_added_and_verified(self):
        self.client.force_login(self.phone_user)
        with synchronous_email():
            self.client.post('/profile/edit/', {
                'full_name': 'Phone Only', 'email': 'phoneuser@example.com',
            })
        self.phone_user.refresh_from_db()
        verify_mail = mail.outbox[-1]
        self.assertIn('phoneuser@example.com', verify_mail.to)

        uidb64 = urlsafe_base64_encode(force_bytes(self.phone_user.pk))
        token = email_verification_token.make_token(self.phone_user)
        self.client.logout()
        response = self.client.get(f'/verify-email/{uidb64}/{token}/')
        self.assertEqual(response.status_code, 302)
        self.phone_user.refresh_from_db()
        self.assertTrue(self.phone_user.email_verified)
        self.assertEqual(self.phone_user.eligible_reset_email(), 'phoneuser@example.com')

        mail.outbox.clear()
        response = self._post_forgot('phoneuser@example.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('phoneuser@example.com', mail.outbox[0].to)
        self.assertIn('reset-password', mail.outbox[0].body)

    # -- unverified email must NOT receive a reset link (account-takeover guard)
    def test_reset_not_sent_for_unverified_profile_email(self):
        self.client.force_login(self.phone_user)
        with synchronous_email():
            self.client.post('/profile/edit/', {
                'full_name': 'Phone Only', 'email': 'phoneuser@example.com',
            })
        self.client.logout()
        mail.outbox.clear()
        response = self._post_forgot('phoneuser@example.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    # -- 9. normal email-registered user reset (compatibility) --------------
    def test_reset_works_for_user_who_registered_with_email(self):
        response = self._post_forgot('registered@example.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('registered@example.com', mail.outbox[0].to)

    # -- 12/13. non-existent email + enumeration-safe response --------------
    def test_nonexistent_email_gives_generic_success_and_sends_nothing(self):
        response = self._post_forgot('nobody@example.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_response_identical_for_existing_and_nonexistent_email(self):
        with synchronous_email():
            r1 = self.client.post('/forgot-password/', {'email': 'registered@example.com'}, follow=True)
        r2 = self.client.post('/forgot-password/', {'email': 'nobody@example.com'}, follow=True)
        self.assertEqual(r1.status_code, r2.status_code)
        msgs1 = [str(m) for m in r1.context['messages']]
        msgs2 = [str(m) for m in r2.context['messages']]
        self.assertEqual(msgs1, msgs2)

    # -- account with no email at all ---------------------------------------
    def test_phone_only_account_with_no_email_has_no_eligible_reset_email(self):
        self.assertIsNone(self.phone_user.eligible_reset_email())
        self.assertFalse(bool(self.phone_user.email))

    # -- 10. expired token ----------------------------------------------------
    def test_expired_reset_token_is_rejected(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.email_user.pk))
        token = default_token_generator.make_token(self.email_user)
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            response = self.client.post(
                f'/reset-password/{uidb64}/{token}/',
                {'password': 'newpass123', 'confirm_password': 'newpass123'},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/forgot-password/')
        self.email_user.refresh_from_db()
        self.assertTrue(self.email_user.check_password('pass1234'))

    # -- 11. reused token -----------------------------------------------------
    def test_reset_token_cannot_be_reused(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.email_user.pk))
        token = default_token_generator.make_token(self.email_user)

        first = self.client.post(
            f'/reset-password/{uidb64}/{token}/',
            {'password': 'firstpass123', 'confirm_password': 'firstpass123'},
        )
        self.assertEqual(first.status_code, 302)
        self.email_user.refresh_from_db()
        self.assertTrue(self.email_user.check_password('firstpass123'))

        second = self.client.post(
            f'/reset-password/{uidb64}/{token}/',
            {'password': 'secondpass123', 'confirm_password': 'secondpass123'},
        )
        self.assertEqual(second.status_code, 302)
        self.assertEqual(second.url, '/forgot-password/')
        self.email_user.refresh_from_db()
        # Still the first password — the reused token never got a chance to change it.
        self.assertTrue(self.email_user.check_password('firstpass123'))


class ProfileEmailUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('0722334455', 'pass1234', full_name='Alice')
        self.other = User.objects.create_user('bob@example.com', 'pass1234', full_name='Bob')
        self.client.force_login(self.user)

    # -- 5. duplicate email prevention ---------------------------------------
    def test_duplicate_email_rejected_against_another_users_email_field(self):
        holder = User.objects.create_user('0700000001', 'pass1234', full_name='Carol')
        holder.email = 'taken@example.com'
        holder.email_verified = True
        holder.save()

        with synchronous_email():
            response = self.client.post('/profile/edit/', {
                'full_name': 'Alice Updated', 'email': 'taken@example.com',
            })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')
        # Other fields in the same submission still saved.
        self.assertEqual(self.user.full_name, 'Alice Updated')

    def test_duplicate_email_rejected_against_another_users_login_identifier(self):
        with synchronous_email():
            response = self.client.post('/profile/edit/', {
                'full_name': 'Alice', 'email': 'bob@example.com',
            })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    # -- 6. invalid email ------------------------------------------------------
    def test_invalid_email_rejected(self):
        with synchronous_email():
            response = self.client.post('/profile/edit/', {
                'full_name': 'Alice', 'email': 'not-an-email',
            })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_valid_new_email_is_normalized_lowercase(self):
        with synchronous_email():
            self.client.post('/profile/edit/', {
                'full_name': 'Alice', 'email': 'Alice.New@Example.COM',
            })
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice.new@example.com')
        self.assertFalse(self.user.email_verified)

    def test_unchanged_email_does_not_reset_verification_or_resend(self):
        self.user.email = 'alice@example.com'
        self.user.email_verified = True
        self.user.save()
        with synchronous_email():
            self.client.post('/profile/edit/', {
                'full_name': 'Alice', 'email': 'alice@example.com',
            })
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertEqual(len(mail.outbox), 0)

    def test_changing_email_sends_verification_and_clears_verified_flag(self):
        self.user.email = 'old@example.com'
        self.user.email_verified = True
        self.user.save()
        with synchronous_email():
            self.client.post('/profile/edit/', {
                'full_name': 'Alice', 'email': 'new@example.com',
            })
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertFalse(self.user.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('new@example.com', mail.outbox[0].to)


class EmailVerificationTokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('0733445566', 'pass1234', full_name='Dee')
        self.user.email = 'dee@example.com'
        self.user.save()

    def test_verification_token_reused_after_success_is_rejected(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)

        first = self.client.get(f'/verify-email/{uidb64}/{token}/')
        self.assertEqual(first.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

        # Same link again — token was minted against email_verified=False,
        # which has since flipped, so the hash no longer matches.
        second = self.client.get(f'/verify-email/{uidb64}/{token}/')
        self.assertEqual(second.status_code, 302)

    def test_verification_token_invalidated_by_changing_email_again(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)

        self.user.email = 'someone-else@example.com'
        self.user.save()

        response = self.client.get(f'/verify-email/{uidb64}/{token}/')
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)


class MalformedLinkTests(TestCase):
    """A uidb64 that decodes to a non-UUID string used to raise an uncaught
    django.core.exceptions.ValidationError from User.objects.get(pk=uid)
    (pk is a UUIDField) — a 500 instead of the intended graceful
    "invalid or expired" message, on both link-confirmation views."""

    def test_reset_password_confirm_with_malformed_uid_does_not_500(self):
        bad_uidb64 = urlsafe_base64_encode(b'not-a-uuid')
        response = self.client.get(f'/reset-password/{bad_uidb64}/some-token/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/forgot-password/')

    def test_verify_email_confirm_with_malformed_uid_does_not_500(self):
        bad_uidb64 = urlsafe_base64_encode(b'not-a-uuid')
        response = self.client.get(f'/verify-email/{bad_uidb64}/some-token/')
        self.assertEqual(response.status_code, 302)


class ResendEmailVerificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('0744556677', 'pass1234', full_name='Erin')

    def test_resend_requires_login(self):
        response = self.client.post('/profile/resend-verification/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_resend_sends_a_fresh_link_for_pending_unverified_email(self):
        self.user.email = 'erin@example.com'
        self.user.save()
        self.client.force_login(self.user)
        with synchronous_email():
            response = self.client.post('/profile/resend-verification/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('erin@example.com', mail.outbox[0].to)

    def test_resend_is_a_noop_when_no_email_on_file(self):
        self.client.force_login(self.user)
        with synchronous_email():
            response = self.client.post('/profile/resend-verification/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_is_a_noop_when_already_verified(self):
        self.user.email = 'erin@example.com'
        self.user.email_verified = True
        self.user.save()
        self.client.force_login(self.user)
        with synchronous_email():
            response = self.client.post('/profile/resend-verification/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_unblocks_reset_end_to_end(self):
        """The exact scenario reported in production: an email added to a
        phone-only account before this verification flow existed sits
        unverified after migrate, and profile_edit's change-detection won't
        re-dispatch for an unchanged value — resend is the only way back in."""
        self.user.email = 'erin@example.com'
        self.user.save()  # email_verified stays False, as it would after migrate
        self.client.force_login(self.user)
        with synchronous_email():
            self.client.post('/profile/resend-verification/')
        verify_mail = mail.outbox[-1]
        self.assertIn('erin@example.com', verify_mail.to)

        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)
        self.client.get(f'/verify-email/{uidb64}/{token}/')
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

        self.client.logout()
        mail.outbox.clear()
        with synchronous_email():
            response = self.client.post('/forgot-password/', {'email': 'erin@example.com'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('erin@example.com', mail.outbox[0].to)


class PhonePrefixLoginTests(TestCase):
    """Registration already normalizes any of +255XXXXXXXXX / 255XXXXXXXXX /
    0XXXXXXXXX to the same canonical phone_or_email — but login previously
    passed the raw typed value straight to an exact-match query, so only the
    exact format used at signup ever worked. authenticate() now goes through
    User.find_by_login_identifier, which normalizes first."""

    def setUp(self):
        # Registers as +255752402315 (see normalize_identifier).
        self.user = User.objects.create_user('0752402315', 'pass1234', full_name='Fahari')

    def _login(self, typed_username):
        return self.client.post('/login/', {'username': typed_username, 'password': 'pass1234'})

    def test_login_with_registered_format_works(self):
        response = self._login('0752402315')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')

    def test_login_with_plus255_prefix_works(self):
        response = self._login('+255752402315')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')

    def test_login_with_bare_255_prefix_works(self):
        response = self._login('255752402315')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')

    def test_wrong_password_with_alternate_prefix_still_reports_invalid_password_not_missing_account(self):
        response = self.client.post('/login/', {'username': '+255752402315', 'password': 'wrongpass'}, follow=True)
        msgs = [str(m) for m in response.context['messages']]
        self.assertTrue(any('Invalid password' in m for m in msgs))


class LoginByVerifiedEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('0766778899', 'pass1234', full_name='Grace')

    def _login(self, typed_username, password='pass1234'):
        return self.client.post('/login/', {'username': typed_username, 'password': password})

    def test_login_by_email_fails_before_verification(self):
        self.user.email = 'grace@example.com'
        self.user.save()
        response = self._login('grace@example.com')
        self.assertEqual(response.status_code, 200)  # re-renders login.html, no redirect

    def test_login_by_verified_email_succeeds_with_same_password(self):
        self.user.email = 'grace@example.com'
        self.user.email_verified = True
        self.user.save()
        response = self._login('grace@example.com')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')

    def test_login_by_phone_still_works_after_verified_email_added(self):
        self.user.email = 'grace@example.com'
        self.user.email_verified = True
        self.user.save()
        response = self._login('0766778899')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')

    def test_verified_email_login_is_case_insensitive(self):
        self.user.email = 'grace@example.com'
        self.user.email_verified = True
        self.user.save()
        response = self._login('Grace@Example.com')
        self.assertEqual(response.status_code, 302)


class LoginPrefillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('0788990011', 'oldpass123', full_name='Halima')

    def test_login_get_prefills_username_from_identifier_query_param(self):
        response = self.client.get('/login/?identifier=%2B255788990011')
        self.assertContains(response, '+255788990011')

    def test_login_get_without_identifier_has_empty_prefill(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)

    def test_reset_password_redirects_to_login_with_identifier_prefilled(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.post(
            f'/reset-password/{uidb64}/{token}/',
            {'password': 'newpass123', 'confirm_password': 'newpass123'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/?identifier='))
        self.assertIn('255788990011', response.url)

        # Following the redirect shows the login page with the field
        # pre-filled and only the password left for the user to type.
        followed = self.client.get(response.url)
        self.assertContains(followed, '+255788990011')

    def test_reset_password_prefills_verified_email_when_that_was_the_reset_channel(self):
        self.user.email = 'halima@example.com'
        self.user.email_verified = True
        self.user.save()
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.post(
            f'/reset-password/{uidb64}/{token}/',
            {'password': 'newpass123', 'confirm_password': 'newpass123'},
        )
        # phone_or_email itself isn't an email, so eligible_reset_email()
        # returns the verified profile email — that's the address the link
        # was actually delivered to, so it's what gets pre-filled.
        self.assertIn('halima%40example.com', response.url)
