from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from accounts.models import User

from .models import ModerationHold


def make_user(identifier, full_name='Test User'):
    return User.objects.create_user(phone_or_email=identifier, password='Testing2026!', full_name=full_name)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ModerationHoldModelTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000300', 'Author')
        self.staff = make_user('+255700000301', 'Staff')

    def _make_post(self):
        from posts.models import Post
        return Post.objects.create(author=self.author, body='hello', audience=Post.Audience.PUBLIC)

    def test_open_or_reopen_creates_a_pending_hold(self):
        post = self._make_post()
        hold = ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)
        self.assertEqual(hold.status, ModerationHold.Status.PENDING)
        self.assertEqual(hold.reason, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)
        self.assertEqual(hold.content_type, ContentType.objects.get_for_model(post))
        self.assertEqual(hold.object_id, post.pk)

    def test_open_or_reopen_is_idempotent_per_target(self):
        post = self._make_post()
        ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)
        ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)
        self.assertEqual(ModerationHold.objects.count(), 1)

    def test_reopening_a_resolved_hold_clears_resolution(self):
        post = self._make_post()
        hold = ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)
        hold.resolve(ModerationHold.Status.APPROVED, by=self.staff)

        reopened = ModerationHold.open_or_reopen(post, ModerationHold.Reason.USER_REPORT)
        self.assertEqual(reopened.pk, hold.pk)
        self.assertEqual(reopened.status, ModerationHold.Status.PENDING)
        self.assertEqual(reopened.reason, ModerationHold.Reason.USER_REPORT)
        self.assertIsNone(reopened.resolved_at)
        self.assertIsNone(reopened.resolved_by)

    def test_resolve_sets_status_timestamp_and_resolver(self):
        post = self._make_post()
        hold = ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)
        hold.resolve(ModerationHold.Status.REJECTED, by=self.staff)
        self.assertEqual(hold.status, ModerationHold.Status.REJECTED)
        self.assertIsNotNone(hold.resolved_at)
        self.assertEqual(hold.resolved_by, self.staff)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class PostModerationHoldIntegrationTests(TestCase):
    """Confirms posts/views.py and posts/admin.py stay in sync with the
    generalized ModerationHold table introduced in Phase 4 Step 3, without
    duplicating posts/tests.py's own approval_status coverage."""

    def setUp(self):
        from posts.models import Post
        self.Post = Post
        self.author = make_user('+255700000310', 'Author')
        self.staff = make_user('+255700000311', 'Staff')
        self.staff.is_staff = True
        self.staff.save(update_fields=['is_staff'])

    def test_creating_a_public_post_opens_a_hold(self):
        self.client.force_login(self.author)
        from django.urls import reverse
        response = self.client.post(reverse('create_post'), {'body': 'going public', 'audience': 'public'})
        self.assertEqual(response.status_code, 200)

        post = self.Post.objects.get()
        hold = ModerationHold.objects.get(content_type=ContentType.objects.get_for_model(self.Post), object_id=post.pk)
        self.assertEqual(hold.status, ModerationHold.Status.PENDING)
        self.assertEqual(hold.reason, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)

    def test_creating_a_connections_post_opens_no_hold(self):
        self.client.force_login(self.author)
        from django.urls import reverse
        self.client.post(reverse('create_post'), {'body': 'friends only', 'audience': 'connections'})
        self.assertEqual(ModerationHold.objects.count(), 0)

    def test_admin_approve_action_resolves_the_hold(self):
        from posts.admin import approve_posts
        post = self.Post.objects.create(
            author=self.author, body='pending', audience=self.Post.Audience.PUBLIC,
            approval_status=self.Post.ApprovalStatus.PENDING,
        )
        hold = ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)

        class FakeRequest:
            user = self.staff

        approve_posts(None, FakeRequest(), self.Post.objects.filter(pk=post.pk))

        hold.refresh_from_db()
        self.assertEqual(hold.status, ModerationHold.Status.APPROVED)
        self.assertEqual(hold.resolved_by, self.staff)
        self.assertIsNotNone(hold.resolved_at)

    def test_admin_reject_action_resolves_the_hold(self):
        from posts.admin import reject_posts
        post = self.Post.objects.create(
            author=self.author, body='pending', audience=self.Post.Audience.PUBLIC,
            approval_status=self.Post.ApprovalStatus.PENDING,
        )
        hold = ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)

        class FakeRequest:
            user = self.staff

        reject_posts(None, FakeRequest(), self.Post.objects.filter(pk=post.pk))

        hold.refresh_from_db()
        self.assertEqual(hold.status, ModerationHold.Status.REJECTED)
        self.assertEqual(hold.resolved_by, self.staff)

    def test_admin_action_with_no_request_still_resolves_status_only(self):
        """Matches posts/tests.py's existing pattern of calling the action
        with request=None — must not crash when there's no acting user to
        record."""
        from posts.admin import approve_posts
        post = self.Post.objects.create(
            author=self.author, body='pending', audience=self.Post.Audience.PUBLIC,
            approval_status=self.Post.ApprovalStatus.PENDING,
        )
        hold = ModerationHold.open_or_reopen(post, ModerationHold.Reason.PUBLIC_AUDIENCE_REVIEW)

        approve_posts(None, None, self.Post.objects.filter(pk=post.pk))

        hold.refresh_from_db()
        self.assertEqual(hold.status, ModerationHold.Status.APPROVED)
        self.assertIsNone(hold.resolved_by)
