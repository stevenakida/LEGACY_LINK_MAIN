"""Profile page (Instagram-style redesign), Settings pages, change/set
password, and the shortened email-verification copy."""
import uuid
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.tokens import email_verification_token
from alumni.models import School
from connections import services
from connections.models import Connection, UserRelationshipOverride
from media_assets.models import MediaAsset
from posts.models import Post

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
OLD, NEW = 'OldPass123!x', 'NewPass456!y'


def person(ident, name, password=OLD, **kw):
    return User.objects.create_user(phone_or_email=ident, password=password, full_name=name, **kw)


def asset(owner):
    token = uuid.uuid4().hex
    return MediaAsset.objects.create(
        owner=owner, category=MediaAsset.Category.IMAGE, original_filename='p.jpg',
        sanitized_filename='p.jpg', declared_size_bytes=10,
        quarantine_storage_key=f'quarantine/{token}.jpg', storage_key=f'ready/{token}.jpg',
        status=MediaAsset.Status.READY,
    )


def messages_of(response):
    return [str(m) for m in response.context['messages']]


@FAST_HASH
class ProfilePageTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Arusha Secondary', school_type='secondary')
        self.me = person('+255744000001', 'Pat Profile', secondary_school=self.school, secondary_completion_year=2004)
        self.client.force_login(self.me)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('profile')).status_code, 302)

    def test_header_links_to_settings_instead_of_a_bare_logout_button(self):
        html = self.client.get(reverse('profile')).content.decode()
        self.assertIn(reverse('settings'), html)
        self.assertNotIn('action="%s"' % reverse('logout'), html)

    def test_stat_row_counts(self):
        mate = person('+255744000002', 'Classmate', secondary_school=self.school, secondary_completion_year=2004)
        friend = person('+255744000003', 'Friend')
        Connection.objects.create(requester=self.me, receiver=friend, status='accepted')
        Post.objects.create(author=self.me, body='one')
        Post.objects.create(author=self.me, body='two')
        ctx = self.client.get(reverse('profile')).context
        self.assertEqual((ctx['posts_count'], ctx['connections_count'], ctx['cohort_count']), (2, 1, 1))
        self.assertEqual(mate.secondary_school, self.school)

    def test_connections_count_matches_the_network_definition(self):
        blocked, inactive = person('+255744000004', 'Blocked'), person('+255744000005', 'Inactive')
        Connection.objects.create(requester=self.me, receiver=blocked, status='accepted')
        Connection.objects.create(requester=inactive, receiver=self.me, status='accepted')
        UserRelationshipOverride.objects.create(actor=self.me, target=blocked, type='block')   # inconsistent on purpose
        inactive.is_active = False
        inactive.save()
        shown = self.client.get(reverse('profile')).context['connections_count']
        self.assertEqual(shown, services.network_state(self.me)['connections_count'])
        self.assertEqual(shown, 0)

    def test_share_url_is_the_public_profile_link(self):
        url = self.client.get(reverse('profile')).context['share_url']
        self.assertTrue(url.endswith('/profile/%s/' % self.me.id), url)
        self.assertEqual(self.client.get('/profile/%s/' % self.me.id).status_code, 302)   # owner is sent back to /profile/

    def test_post_grid_uses_image_tiles_and_text_snippets(self):
        with_photo = Post.objects.create(author=self.me, body='has a photo', media_asset=asset(self.me))
        Post.objects.create(author=self.me, body='word ' * 40)
        html = self.client.get(reverse('profile')).content.decode()
        self.assertIn(reverse('post_image', args=[with_photo.id]), html)
        self.assertIn('ig-post-tile-text', html)
        self.assertIn('…', html)            # long text is truncated to a snippet

    def test_grid_shows_only_my_posts_and_caps_at_thirty(self):
        other = person('+255744000006', 'Someone Else')
        Post.objects.create(author=other, body='not mine, must not appear', audience='public')
        Post.objects.bulk_create([Post(author=self.me, body=f'mine {i}') for i in range(31)])
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.context['posts_count'], 31)
        self.assertEqual(len(list(response.context['posts'])), 30)
        self.assertNotContains(response, 'not mine, must not appear')

    def test_empty_grid_invites_the_first_post(self):
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'No posts yet')
        self.assertContains(response, reverse('dashboard'))

    def test_complete_your_profile_cards(self):
        response = self.client.get(reverse('profile'))
        ctx = response.context
        self.assertEqual(ctx['identity_score_total_count'], 8)
        self.assertEqual(ctx['identity_score_completed_count'], 1)     # only the secondary school so far
        self.assertEqual(len(ctx['identity_score_suggestions']), 4)
        self.assertContains(response, '1 of 8 complete')
        self.assertContains(response, 'ig-task-card')
        for icon in ('work', 'apartment'):
            self.assertContains(response, icon)

    def test_fully_complete_profile_hides_the_task_grid(self):
        # Every weighted field filled -> nothing to suggest.
        prim = School.objects.create(name='Primary Z', school_type='primary')
        uni = School.objects.create(name='Uni Z', school_type='university')
        self.me.avatar = 'avatars/x.png'
        self.me.bio = 'Hello'
        self.me.primary_school, self.me.primary_completion_year = prim, 1998
        self.me.tertiary_school, self.me.tertiary_completion_year = uni, 2012
        self.me.current_location, self.me.current_role, self.me.company_name = 'Arusha', 'Engineer', 'Acme'
        self.me.save()
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.context['identity_score'], 100)
        self.assertNotContains(response, 'Complete your profile')
        self.assertContains(response, 'fully complete')

    def test_tab_switcher_panels_exist(self):
        html = self.client.get(reverse('profile')).content.decode()
        for panel in ('prof-posts', 'prof-education', 'prof-about'):
            self.assertIn('id="%s"' % panel, html)
        self.assertIn('Arusha Secondary', html)     # education timeline still there

    def test_pending_email_banner_is_short(self):
        self.me.email, self.me.email_verified = 'pat@example.com', False
        self.me.save()
        html = self.client.get(reverse('profile')).content.decode()
        self.assertIn('check your inbox for the link', html)
        self.assertIn('Resend email', html)
        self.assertNotIn('spam folder', html)
        self.assertNotIn('enable password reset', html)

    def test_no_recovery_email_banner_is_short(self):
        html = self.client.get(reverse('profile')).content.decode()      # phone-only account, no email
        self.assertIn('No recovery email on file yet.', html)
        self.assertNotIn('reset by SMS', html)


@FAST_HASH
class VerificationCopyTests(TestCase):
    def setUp(self):
        self.user = person('+255744000010', 'Vera Verify')
        self.client.force_login(self.user)

    def test_saving_a_new_email_uses_the_short_message(self):
        with mock.patch('config.views.dispatch_email_verification') as dispatch:
            response = self.client.post(reverse('profile_edit'), {'full_name': 'Vera Verify', 'email': 'vera@example.com'},
                                        follow=True)
        dispatch.assert_called_once()
        self.assertIn('Profile updated! Check your email to verify it.', messages_of(response))

    def test_saving_without_an_email_change_keeps_the_plain_message(self):
        response = self.client.post(reverse('profile_edit'), {'full_name': 'Vera Verify'}, follow=True)
        self.assertIn('Profile updated successfully!', messages_of(response))

    def test_verified_message_is_short(self):
        self.user.email = 'vera@example.com'
        self.user.save()
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = email_verification_token.make_token(self.user)
        response = self.client.get(reverse('verify_email_confirm', args=[uid, token]), follow=True)
        self.assertIn('Email verified! You can now use it to reset your password.', messages_of(response))
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)


@FAST_HASH
class SettingsPageTests(TestCase):
    def setUp(self):
        self.me = person('+255744000020', 'Sam Settings')
        self.b1 = person('+255744000021', 'Blocked Bea')
        self.b2 = person('+255744000022', 'Muted Max')
        self.stranger = person('+255744000023', 'Stranger Sue')
        self.client.force_login(self.me)

    def test_every_settings_page_requires_login(self):
        self.client.logout()
        for name in ('settings', 'change_password', 'blocked_accounts', 'muted_accounts'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)

    def test_menu_shows_counts_and_all_sections(self):
        UserRelationshipOverride.objects.create(actor=self.me, target=self.b1, type='block')
        UserRelationshipOverride.objects.create(actor=self.me, target=self.b2, type='mute')
        response = self.client.get(reverse('settings'))
        self.assertEqual((response.context['blocked_count'], response.context['muted_count']), (1, 1))
        for needle in ('Account', 'Privacy &amp; safety', 'Preferences', 'Support', 'Log out',
                       reverse('blocked_accounts'), reverse('muted_accounts'), reverse('notifications_list'),
                       reverse('terms'), 'theme-toggle-btn', 'lang-toggle-btn', 'action="%s"' % reverse('logout')):
            self.assertContains(response, needle)

    def test_language_row_carries_the_current_language_code(self):
        self.assertContains(self.client.get(reverse('settings')), 'data-lang="en"')

    def test_password_row_label_depends_on_whether_a_password_exists(self):
        self.assertContains(self.client.get(reverse('settings')), 'Change password')
        google = person('google@example.com', 'Google Only', password=None)
        google.set_unusable_password()
        google.save()
        self.client.force_login(google)
        html = self.client.get(reverse('settings')).content.decode()
        self.assertIn('Set a password', html)
        self.assertNotIn('Change password', html)

    def test_recovery_email_row_only_when_no_verified_email(self):
        self.assertContains(self.client.get(reverse('settings')), 'Add a recovery email')
        self.me.email, self.me.email_verified = 'sam@example.com', True
        self.me.save()
        self.assertNotContains(self.client.get(reverse('settings')), 'Add a recovery email')

    def test_blocked_list_and_unblock_round_trip(self):
        UserRelationshipOverride.objects.create(actor=self.me, target=self.b1, type='block')
        self.assertContains(self.client.get(reverse('blocked_accounts')), 'Blocked Bea')
        response = self.client.post(reverse('unblock_user_web', args=[self.b1.id]), {'next': reverse('blocked_accounts')})
        self.assertEqual(response.url, reverse('blocked_accounts'))
        self.assertFalse(UserRelationshipOverride.objects.filter(actor=self.me, type='block').exists())
        self.assertContains(self.client.get(reverse('blocked_accounts')), 'No blocked accounts')

    def test_muted_list_and_unmute_round_trip(self):
        UserRelationshipOverride.objects.create(actor=self.me, target=self.b2, type='mute')
        self.assertContains(self.client.get(reverse('muted_accounts')), 'Muted Max')
        self.client.post(reverse('unmute_user_web', args=[self.b2.id]), {'next': reverse('muted_accounts')})
        self.assertContains(self.client.get(reverse('muted_accounts')), 'No muted accounts')

    def test_lists_show_only_my_own_overrides_and_only_the_right_type(self):
        UserRelationshipOverride.objects.create(actor=self.stranger, target=self.b1, type='block')   # someone else's
        UserRelationshipOverride.objects.create(actor=self.me, target=self.b2, type='mute')
        self.assertNotContains(self.client.get(reverse('blocked_accounts')), 'Blocked Bea')
        self.assertNotContains(self.client.get(reverse('blocked_accounts')), 'Muted Max')
        self.assertNotContains(self.client.get(reverse('muted_accounts')), 'Blocked Bea')

    def test_people_who_blocked_me_are_not_listed_in_my_blocked_accounts(self):
        UserRelationshipOverride.objects.create(actor=self.b1, target=self.me, type='block')
        self.assertNotContains(self.client.get(reverse('blocked_accounts')), 'Blocked Bea')


@FAST_HASH
class ChangePasswordTests(TestCase):
    def setUp(self):
        self.me = person('+255744000030', 'Pia Password')
        self.client.force_login(self.me)
        self.url = reverse('change_password')

    def post(self, old=OLD, n1=NEW, n2=NEW, **kw):
        return self.client.post(self.url, {'old_password': old, 'new_password1': n1, 'new_password2': n2}, **kw)

    def unchanged(self):
        return User.objects.get(pk=self.me.pk).check_password(OLD)

    def test_form_asks_for_the_current_password(self):
        self.assertContains(self.client.get(self.url), 'name="old_password"')

    def test_wrong_current_password_is_rejected(self):
        self.assertContains(self.post(old='nope'), 'Current password is incorrect.')
        self.assertTrue(self.unchanged())

    def test_mismatched_new_passwords_are_rejected(self):
        self.assertContains(self.post(n2='different'), 'New passwords don')
        self.assertTrue(self.unchanged())

    def test_empty_new_password_is_rejected(self):
        self.post(n1='', n2='')
        self.assertTrue(self.unchanged())

    def test_weak_password_is_rejected_by_the_django_validators(self):
        self.assertContains(self.post(n1='abc', n2='abc'), 'too short')
        self.assertTrue(self.unchanged())

    def test_valid_change_updates_the_password_and_keeps_me_logged_in(self):
        response = self.post(follow=True)
        self.assertIn('Password updated successfully!', messages_of(response))
        self.assertTrue(User.objects.get(pk=self.me.pk).check_password(NEW))
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)     # session survived (update_session_auth_hash)

    def test_old_password_stops_working_after_a_change(self):
        self.post()
        self.assertFalse(User.objects.get(pk=self.me.pk).check_password(OLD))

    def test_google_only_account_can_set_a_first_password_without_a_current_one(self):
        google = person('google2@example.com', 'Gina Google', password=None)
        google.set_unusable_password()
        google.save()
        self.client.force_login(google)
        self.assertNotContains(self.client.get(self.url), 'name="old_password"')
        response = self.client.post(self.url, {'new_password1': NEW, 'new_password2': NEW}, follow=True)
        self.assertTrue(any('Password set' in m for m in messages_of(response)))
        self.assertTrue(User.objects.get(pk=google.pk).has_usable_password())

    def test_a_usable_password_always_needs_the_current_one(self):
        # Omitting old_password must not bypass the check for a normal account.
        response = self.client.post(self.url, {'new_password1': NEW, 'new_password2': NEW})
        self.assertContains(response, 'Current password is incorrect.')
        self.assertTrue(self.unchanged())

    def test_anonymous_post_changes_nothing(self):
        self.client.logout()
        response = self.post()
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)
        self.assertTrue(self.unchanged())
