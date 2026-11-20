"""Public account-deletion page (Google Play requires a deletion URL that works
without signing in). The real deletion form still needs a login."""
from django.test import TestCase
from django.urls import reverse


class AccountDeletionInfoPageTests(TestCase):
    def test_open_to_signed_out_visitors_without_redirect(self):
        response = self.client.get(reverse('account_deletion_info'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(reverse('account_deletion_info'), '/account-deletion/')

    def test_names_the_app_and_explains_the_steps(self):
        page = self.client.get(reverse('account_deletion_info')).content.decode()
        self.assertIn('LegacyLink Africa', page)
        for step in ('Profile', 'Settings', 'Delete account', 'Delete my account', 'DELETE'):
            self.assertIn(step, page)

    def test_lists_what_is_deleted_and_what_may_remain(self):
        page = self.client.get(reverse('account_deletion_info')).content.decode()
        for item in ('posts', 'comments', 'connections', 'chats', 'Photos', 'notifications'):
            self.assertIn(item, page)
        self.assertIn('secure backups', page)

    def test_contact_email_is_visible_text_not_a_cloudflare_obfuscated_literal(self):
        page = self.client.get(reverse('account_deletion_info')).content.decode()
        self.assertIn('developer&#64;legacylink.africa', page)
        self.assertNotIn('developer@legacylink.africa', page)

    def test_links_to_the_real_deletion_form_which_still_requires_login(self):
        page = self.client.get(reverse('account_deletion_info')).content.decode()
        self.assertIn(f'href="{reverse("delete_account")}"', page)
        response = self.client.get(reverse('delete_account'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_works_in_a_signed_in_session_too(self):
        from accounts.models import User
        user = User.objects.create_user(phone_or_email='+255744620001', password='x', full_name='Del Page')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('account_deletion_info')).status_code, 200)
