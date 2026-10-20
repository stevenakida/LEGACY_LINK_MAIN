"""Home's profile-strength card and stat row are a compact strip (CEO/UX request):
four tappable number+label cells in one panel, no per-cell icon tiles."""
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


@FAST_HASH
class HomeStatsStripTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone_or_email='+255744610001', password='x', full_name='Strip Person')
        self.client.force_login(self.user)

    def test_stats_are_one_panel_of_four_links_with_number_and_label(self):
        page = self.client.get(reverse('dashboard')).content.decode()
        panel = page[page.index('class="stats-panel"'):page.index('Home feed')]
        self.assertEqual(panel.count('class="stats-card'), 4)
        for href in ('/connections/"', '/connections/?tab=pending"', '/opportunities/"', '/opportunities/?type=event"'):
            self.assertIn(f'href="{href}', panel)
        for label in ('Connections', 'Pending', 'Opportunities', 'Events'):
            self.assertIn(f'<span>{label}</span>', panel)
        self.assertNotIn('material-symbols-rounded', panel)       # no icon tile per stat

    def test_home_strength_card_is_the_compact_variant_but_profile_keeps_the_full_ring(self):
        home = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('card strength-card', home)
        self.assertNotIn('strength-card', self.client.get(reverse('profile')).content.decode())
