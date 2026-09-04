from django.test import TestCase
from django.utils import timezone

from accounts.models import User

from .models import RateLimitHit
from .services import is_rate_limited


def make_user(identifier, full_name='Test User'):
    return User.objects.create_user(phone_or_email=identifier, password='Testing2026!', full_name=full_name)


class IsRateLimitedTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700000901', 'Alice')
        self.bob = make_user('+255700000902', 'Bob')

    def test_allows_first_hit(self):
        self.assertFalse(is_rate_limited(self.alice, 'test_scope', limit=1, window_seconds=60))

    def test_records_a_hit_on_success(self):
        is_rate_limited(self.alice, 'test_scope', limit=5, window_seconds=60)
        self.assertEqual(RateLimitHit.objects.filter(scope='test_scope', actor=self.alice).count(), 1)

    def test_blocks_once_limit_reached(self):
        for _ in range(3):
            self.assertFalse(is_rate_limited(self.alice, 'test_scope', limit=3, window_seconds=60))
        self.assertTrue(is_rate_limited(self.alice, 'test_scope', limit=3, window_seconds=60))

    def test_blocked_attempt_does_not_record_a_hit(self):
        for _ in range(2):
            is_rate_limited(self.alice, 'test_scope', limit=2, window_seconds=60)
        is_rate_limited(self.alice, 'test_scope', limit=2, window_seconds=60)  # blocked
        self.assertEqual(RateLimitHit.objects.filter(scope='test_scope', actor=self.alice).count(), 2)

    def test_old_hits_outside_window_do_not_count(self):
        old_hit = RateLimitHit.objects.create(scope='test_scope', actor=self.alice)
        RateLimitHit.objects.filter(pk=old_hit.pk).update(created_at=timezone.now() - timezone.timedelta(seconds=120))
        self.assertFalse(is_rate_limited(self.alice, 'test_scope', limit=1, window_seconds=60))

    def test_scopes_are_independent(self):
        for _ in range(2):
            is_rate_limited(self.alice, 'scope_a', limit=2, window_seconds=60)
        self.assertTrue(is_rate_limited(self.alice, 'scope_a', limit=2, window_seconds=60))
        self.assertFalse(is_rate_limited(self.alice, 'scope_b', limit=2, window_seconds=60))

    def test_users_are_independent(self):
        for _ in range(2):
            is_rate_limited(self.alice, 'test_scope', limit=2, window_seconds=60)
        self.assertTrue(is_rate_limited(self.alice, 'test_scope', limit=2, window_seconds=60))
        self.assertFalse(is_rate_limited(self.bob, 'test_scope', limit=2, window_seconds=60))
