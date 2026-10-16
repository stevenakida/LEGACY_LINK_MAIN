"""The profile-completion meter is called "Profile Strength" everywhere users
see it, and Home confirms a complete profile instead of asking for more
(CEO checklist item 7). The code identifiers (identity_score) are unchanged."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from accounts.models import User
from alumni.models import School

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], MEDIA_ASSETS_S3_ENABLED=False)

SIGNED_IN_PAGES = [
    'dashboard', 'profile', 'profile_edit', 'connections', 'messages_inbox', 'opportunities',
    'notifications_list', 'settings',
]


def school(name, kind):
    return School.objects.create(name=name, slug=f'{kind}-{name}'.lower().replace(' ', '-'), school_type=kind)


def complete_user():
    """Every Profile Strength component filled in."""
    return User.objects.create_user(
        phone_or_email='+255744600001', password='x', full_name='Complete Person',
        avatar='avatars/complete.png', bio='A short bio', current_location='Arusha', current_role='Engineer',
        company_name='LegacyLink', primary_school=school('Njiro Hill', 'primary'), primary_completion_year=2000,
        secondary_school=school('Arusha', 'secondary'), secondary_completion_year=2004,
        tertiary_school=school('UDSM', 'university'), tertiary_completion_year=2012,
    )


@FAST_HASH
class ProfileStrengthWordingTests(TestCase):
    def setUp(self):
        self.new = User.objects.create_user(phone_or_email='+255744600002', password='x', full_name='Brand New')

    def test_home_calls_it_profile_strength_for_an_incomplete_profile(self):
        self.client.force_login(self.new)
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, 'Profile Strength')
        self.assertNotContains(page, 'Identity Score')
        self.assertContains(page, 'Complete your profile to increase your visibility')
        self.assertContains(page, 'chip-action')                       # the next thing to add
        self.assertNotContains(page, 'fully complete')

    def test_home_confirms_a_complete_profile_instead_of_asking_for_more(self):
        user = complete_user()
        self.assertEqual(user.identity_score, 100)
        self.client.force_login(user)
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, 'Profile Strength')
        self.assertContains(page, '100%')
        self.assertContains(page, 'Your profile is fully complete')
        self.assertNotContains(page, 'Complete your profile to increase your visibility')
        self.assertNotContains(page, 'chip-action')

    def test_the_profile_page_agrees_with_home(self):
        self.client.force_login(complete_user())
        profile = self.client.get(reverse('profile'))
        self.assertContains(profile, 'Profile Strength')
        self.assertContains(profile, 'fully complete')

    def test_both_pages_move_off_complete_together(self):
        user = complete_user()
        user.current_role = ''
        user.save()
        self.client.force_login(user)
        for name in ('dashboard', 'profile'):
            page = self.client.get(reverse(name))
            self.assertNotContains(page, 'fully complete', msg_prefix=name)

    def test_the_old_name_appears_on_no_signed_in_page(self):
        for user in (self.new, complete_user()):
            self.client.force_login(user)
            for name in SIGNED_IN_PAGES:
                page = self.client.get(reverse(name))
                self.assertEqual(page.status_code, 200, name)
                self.assertNotContains(page, 'Identity Score', msg_prefix=f'{name} for {user.full_name}')
            for tab in ('discover', 'connected', 'pending'):
                page = self.client.get(reverse('connections'), {'tab': tab})
                self.assertNotContains(page, 'Identity Score', msg_prefix=f'connections?tab={tab}')

    def test_the_network_invite_line_no_longer_makes_a_false_claim(self):
        # Invites are not part of the score, so the empty-state line must not say they grow it.
        self.client.force_login(complete_user())
        page = self.client.get(reverse('connections'), {'tab': 'discover'})
        self.assertContains(page, 'the more of them join, the more people you can reconnect with')
        self.assertNotContains(page, 'grows your')

    def test_swahili_has_a_translation_for_the_new_name_and_message(self):
        with translation.override('sw'):
            self.assertEqual(translation.gettext('Profile Strength'), 'Nguvu ya Wasifu')
            self.assertEqual(
                translation.gettext('Your profile is fully complete — nice work!'),
                'Wasifu wako umekamilika kabisa — kazi nzuri!')

    def test_home_shows_the_swahili_name_for_swahili_users(self):
        user = complete_user()
        self.client.force_login(user)
        self.client.post(reverse('set_language_web'), {'language': 'sw'})
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, 'Nguvu ya Wasifu')
        self.assertContains(page, 'Wasifu wako umekamilika kabisa')
