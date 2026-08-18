import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from alumni.models import School
from connections.models import Connection
from media_assets.models import MediaAsset

from .models import Post
from .views import get_feed_for_user


def make_user(identifier, full_name='Test User', **kwargs):
    return User.objects.create_user(phone_or_email=identifier, password='Testing2026!', full_name=full_name, **kwargs)


def make_school(name='Test Secondary', school_type='secondary'):
    return School.objects.create(name=name, slug=name.lower().replace(' ', '-'), school_type=school_type)


def make_asset(owner, status=MediaAsset.Status.READY, moderation_hold=False):
    # storage_key/quarantine_storage_key are unique=True — a fixed
    # per-owner path collides the moment a test creates more than one
    # asset for the same owner (setUp + the test body, or two assets in
    # one test), so give each call its own random token like the real
    # media_assets pipeline does.
    token = uuid.uuid4().hex
    return MediaAsset.objects.create(
        owner=owner,
        category=MediaAsset.Category.IMAGE,
        original_filename='photo.jpg',
        sanitized_filename='photo.jpg',
        declared_size_bytes=1024,
        quarantine_storage_key=f'quarantine/{owner.id}/{token}.jpg',
        storage_key=f'ready/{owner.id}/{token}.jpg',
        status=status,
        moderation_hold=moderation_hold,
    )


def connect(a, b):
    Connection.objects.create(requester=a, receiver=b, status='accepted')


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class FeedVisibilityTests(TestCase):
    def setUp(self):
        self.a = make_user('+255700000001', 'Alice')
        self.b = make_user('+255700000002', 'Bob')
        self.c = make_user('+255700000003', 'Carol')  # stranger, not connected
        connect(self.a, self.b)

        self.post_a = Post.objects.create(author=self.a, body='hello from Alice')
        self.post_b = Post.objects.create(author=self.b, body='hello from Bob')
        self.post_c = Post.objects.create(author=self.c, body='hello from Carol')

    def test_feed_includes_self_and_accepted_connections_only(self):
        feed = get_feed_for_user(self.a)
        self.assertIn(self.post_a, feed)
        self.assertIn(self.post_b, feed)
        self.assertNotIn(self.post_c, feed)

    def test_pending_connection_is_not_visible(self):
        Connection.objects.create(requester=self.c, receiver=self.a, status='pending')
        feed = get_feed_for_user(self.a)
        self.assertNotIn(self.post_c, feed)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class CohortAudienceTests(TestCase):
    def setUp(self):
        self.school = make_school()
        # Alice and Bob share the same school+year — cohort-mates, but NOT
        # connected. Carol shares neither.
        self.alice = make_user('+255700000101', 'Alice', secondary_school=self.school, secondary_completion_year=2015)
        self.bob = make_user('+255700000102', 'Bob', secondary_school=self.school, secondary_completion_year=2015)
        self.carol = make_user('+255700000103', 'Carol', secondary_school=self.school, secondary_completion_year=2019)

    def test_cohort_post_visible_to_cohort_mate_without_a_connection(self):
        post = Post.objects.create(author=self.alice, body='cohort news', audience=Post.Audience.COHORT)
        feed = get_feed_for_user(self.bob)
        self.assertIn(post, feed)

    def test_cohort_post_not_visible_to_different_year(self):
        post = Post.objects.create(author=self.alice, body='cohort news', audience=Post.Audience.COHORT)
        feed = get_feed_for_user(self.carol)
        self.assertNotIn(post, feed)

    def test_connections_post_not_visible_to_cohort_mate_without_connection(self):
        post = Post.objects.create(author=self.alice, body='just for connections', audience=Post.Audience.CONNECTIONS)
        feed = get_feed_for_user(self.bob)
        self.assertNotIn(post, feed)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class PublicAudienceApprovalTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000201', 'Author')
        self.other = make_user('+255700000202', 'Other')  # not connected, no shared cohort

    def test_pending_public_post_visible_only_to_author(self):
        post = Post.objects.create(
            author=self.author, body='pending public', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.PENDING,
        )
        self.assertIn(post, get_feed_for_user(self.author))
        self.assertNotIn(post, get_feed_for_user(self.other))

    def test_rejected_public_post_visible_only_to_author(self):
        post = Post.objects.create(
            author=self.author, body='rejected public', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.REJECTED,
        )
        self.assertIn(post, get_feed_for_user(self.author))
        self.assertNotIn(post, get_feed_for_user(self.other))

    def test_approved_public_post_visible_to_everyone(self):
        post = Post.objects.create(
            author=self.author, body='approved public', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.APPROVED,
        )
        self.assertIn(post, get_feed_for_user(self.other))

    def test_create_post_with_public_audience_starts_pending(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('create_post'), {'body': 'going public', 'audience': 'public'})
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.audience, Post.Audience.PUBLIC)
        self.assertEqual(post.approval_status, Post.ApprovalStatus.PENDING)

    def test_create_post_with_connections_audience_needs_no_approval(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('create_post'), {'body': 'friends only', 'audience': 'connections'})
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.approval_status, Post.ApprovalStatus.NOT_REQUIRED)

    def test_admin_approve_action_makes_post_visible(self):
        from posts.admin import approve_posts
        post = Post.objects.create(
            author=self.author, body='pending public', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.PENDING,
        )
        approve_posts(None, None, Post.objects.filter(pk=post.pk))
        post.refresh_from_db()
        self.assertEqual(post.approval_status, Post.ApprovalStatus.APPROVED)
        self.assertIn(post, get_feed_for_user(self.other))

    def test_admin_reject_action_keeps_post_hidden(self):
        from posts.admin import reject_posts
        post = Post.objects.create(
            author=self.author, body='pending public', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.PENDING,
        )
        reject_posts(None, None, Post.objects.filter(pk=post.pk))
        post.refresh_from_db()
        self.assertEqual(post.approval_status, Post.ApprovalStatus.REJECTED)
        self.assertNotIn(post, get_feed_for_user(self.other))


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class CreatePostTests(TestCase):
    def setUp(self):
        self.user = make_user('+255700000010', 'Owner')
        self.other = make_user('+255700000020', 'Other')
        self.client.force_login(self.user)

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(reverse('create_post'), {'body': 'hi'})
        self.assertEqual(response.status_code, 401)

    def test_rejects_empty_post(self):
        response = self.client.post(reverse('create_post'), {'body': '  '})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Post.objects.count(), 0)

    def test_creates_text_only_post_default_audience(self):
        response = self.client.post(reverse('create_post'), {'body': 'Just text'})
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.author, self.user)
        self.assertEqual(post.body, 'Just text')
        self.assertIsNone(post.media_asset)
        self.assertEqual(post.audience, Post.Audience.CONNECTIONS)

    def test_attaches_own_ready_asset_and_marks_it_attached(self):
        asset = make_asset(self.user)
        response = self.client.post(reverse('create_post'), {'body': 'with photo', 'media_id': str(asset.id)})
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.media_asset_id, asset.id)
        asset.refresh_from_db()
        self.assertTrue(asset.is_attached)

    def test_rejects_attaching_another_users_asset(self):
        asset = make_asset(self.other)
        response = self.client.post(reverse('create_post'), {'body': 'sneaky', 'media_id': str(asset.id)})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Post.objects.count(), 0)
        asset.refresh_from_db()
        self.assertFalse(asset.is_attached)

    def test_rejects_attaching_a_not_ready_asset(self):
        asset = make_asset(self.user, status=MediaAsset.Status.PROCESSING)
        response = self.client.post(reverse('create_post'), {'body': 'too soon', 'media_id': str(asset.id)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Post.objects.count(), 0)

    def test_rejects_attaching_a_moderation_held_asset(self):
        asset = make_asset(self.user, moderation_hold=True)
        response = self.client.post(reverse('create_post'), {'body': 'held', 'media_id': str(asset.id)})
        self.assertEqual(response.status_code, 400)

    def test_invalid_audience_value_falls_back_to_connections(self):
        response = self.client.post(reverse('create_post'), {'body': 'weird audience', 'audience': 'everyone-on-earth'})
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.audience, Post.Audience.CONNECTIONS)

    def test_can_choose_cohort_audience(self):
        response = self.client.post(reverse('create_post'), {'body': 'cohort post', 'audience': 'cohort'})
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.audience, Post.Audience.COHORT)
        self.assertEqual(post.approval_status, Post.ApprovalStatus.NOT_REQUIRED)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class PostImageAuthorizationTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000030', 'Author')
        self.friend = make_user('+255700000040', 'Friend')
        self.stranger = make_user('+255700000050', 'Stranger')
        connect(self.author, self.friend)

        asset = make_asset(self.author)
        self.post = Post.objects.create(author=self.author, body='pic post', media_asset=asset)

    def test_requires_authentication(self):
        response = self.client.get(reverse('post_image', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 401)

    def test_stranger_cannot_view_image(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('post_image', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 404)

    def test_author_can_view_own_image(self):
        self.client.force_login(self.author)
        response = self.client.get(reverse('post_image', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 302)

    def test_accepted_connection_can_view_image(self):
        self.client.force_login(self.friend)
        response = self.client.get(reverse('post_image', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 302)

    def test_stranger_cannot_view_pending_public_image(self):
        asset = make_asset(self.author)
        post = Post.objects.create(
            author=self.author, body='pending pic', media_asset=asset,
            audience=Post.Audience.PUBLIC, approval_status=Post.ApprovalStatus.PENDING,
        )
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('post_image', kwargs={'post_id': post.id}))
        self.assertEqual(response.status_code, 404)

    def test_stranger_can_view_approved_public_image(self):
        asset = make_asset(self.author)
        post = Post.objects.create(
            author=self.author, body='approved pic', media_asset=asset,
            audience=Post.Audience.PUBLIC, approval_status=Post.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('post_image', kwargs={'post_id': post.id}))
        self.assertEqual(response.status_code, 302)
