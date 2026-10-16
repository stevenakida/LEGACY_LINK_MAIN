"""Registration applies the same password rules as every other place a
password is set (change and reset) -- it used to accept anything, even "123"."""
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User

STRONG = 'Tr@vel-Mango-2026'
FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def form(**overrides):
    data = {'full_name': 'Amina Juma', 'phone_or_email': '+255744300001', 'password': STRONG, 'agree_terms': 'on'}
    data.update(overrides)
    return data


@FAST_HASH
class WebRegisterPasswordTests(TestCase):
    def register(self, **overrides):
        return self.client.post(reverse('register'), form(**overrides))

    def test_a_strong_password_registers_and_signs_in(self):
        response = self.register()
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        user = User.objects.get(phone_or_email='+255744300001')
        self.assertTrue(user.check_password(STRONG))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk) if isinstance(user.pk, int) \
            else self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_weak_passwords_are_refused_and_no_account_is_created(self):
        for weak in ('123', 'abcdefg', '12345678', 'password', '11111111'):
            response = self.register(password=weak)
            self.assertEqual(response.status_code, 200, weak)              # stays on the form
            self.assertFalse(User.objects.filter(phone_or_email='+255744300001').exists(), weak)

    def test_the_reasons_are_shown_to_the_person(self):
        response = self.register(password='123')
        self.assertContains(response, 'too short')

    def test_a_password_that_is_just_the_email_address_is_refused(self):
        response = self.register(phone_or_email='amina.juma@example.com', password='amina.juma@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'too similar')
        self.assertFalse(User.objects.filter(phone_or_email='amina.juma@example.com').exists())

    def test_a_missing_password_is_refused(self):
        response = self.register(password='')
        self.assertContains(response, 'Please choose a password.')
        self.assertFalse(User.objects.filter(phone_or_email='+255744300001').exists())

    def test_typed_values_come_back_but_the_password_never_does(self):
        response = self.register(password='123', full_name='Amina Juma')
        self.assertContains(response, 'value="Amina Juma"')
        self.assertContains(response, 'value="+255744300001"')
        self.assertNotContains(response, '123</')
        self.assertNotContains(response, 'value="123"')

    def test_the_terms_are_still_required(self):
        data = form()
        del data['agree_terms']
        response = self.client.post(reverse('register'), data)
        self.assertContains(response, 'You must accept the Terms of Use')
        self.assertFalse(User.objects.filter(phone_or_email='+255744300001').exists())


@FAST_HASH
class ApiRegisterPasswordTests(TestCase):
    def post(self, **overrides):
        data = {'full_name': 'Amina Juma', 'phone_or_email': '+255744300002', 'password': STRONG}
        data.update(overrides)
        return APIClient().post('/api/auth/register/', data, format='json')

    def test_a_strong_password_registers(self):
        response = self.post()
        self.assertIn(response.status_code, (200, 201))
        self.assertTrue(User.objects.get(phone_or_email='+255744300002').check_password(STRONG))

    def test_weak_passwords_are_refused_with_the_reasons(self):
        for weak in ('abc123', '123456', 'password', '12345678'):
            response = self.post(password=weak)
            self.assertEqual(response.status_code, 400, weak)
            self.assertIn('password', response.json(), weak)
        self.assertFalse(User.objects.filter(phone_or_email='+255744300002').exists())

    def test_the_web_form_and_the_api_agree(self):
        # 6 characters used to pass the API but the project's rule is 8+.
        self.assertEqual(self.post(password='Ab1!xy').status_code, 400)


@FAST_HASH
class DuplicateRegisterTests(TransactionTestCase):
    """A duplicate identifier aborts the database transaction, so this needs
    a TransactionTestCase (the view reports it and carries on, as in production)."""

    def test_a_duplicate_identifier_is_still_refused(self):
        self.client.post(reverse('register'), form())
        self.client.logout()
        response = self.client.post(reverse('register'), form(full_name='Someone Else'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Registration failed')
        self.assertEqual(User.objects.filter(phone_or_email='+255744300001').count(), 1)
