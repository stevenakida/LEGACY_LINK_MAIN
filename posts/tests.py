import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from alumni.models import School
from connections.models import Connection, UserRelationshipOverride
from media_assets.models import MediaAsset
from moderation.models import ContentReport, ModerationHold
from notifications.models import Notification

from .models import Post, PostHiddenFor
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
class FeedBlockButtonTests(TestCase):
    """New Block entry point added directly to each non-author feed post
    card (previously Block was only reachable from public_profile.html) —
    a plain <form> POST to the existing block_user_web view, not a new
    endpoint, mirroring public_profile.html's own Block form exactly."""

    def setUp(self):
        self.alice = make_user('+255700000801', 'Alice')
        self.bob = make_user('+255700000802', 'Bob')
        connect(self.alice, self.bob)
        self.post_bob = Post.objects.create(author=self.bob, body='hello from Bob')
        self.client.force_login(self.alice)

    def test_others_post_shows_block_form(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, reverse('block_user_web', args=[self.bob.id]))

    def test_own_post_does_not_show_block_form(self):
        Post.objects.create(author=self.alice, body='hello from me')
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, reverse('block_user_web', args=[self.alice.id]))


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


@override_settings(MEDIA_ASSETS_S3_ENABLED=False, FEATURE_PUBLIC_POST_REVIEW_REQUIRED=True)
class PublicAudienceApprovalTests(TestCase):
    """The review-required mechanism itself (admin approve/reject, the
    moderation hold, notifications) — exercised with the flag forced on
    regardless of its suspended-by-default value, since admins can still
    flip it back on and moderation.services.file_report can still pull any
    Public post under review independent of this flag. See
    PublicAudienceReviewSuspendedTests below for the actual current
    default behavior."""

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


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class PublicAudienceReviewSuspendedTests(TestCase):
    """FEATURE_PUBLIC_POST_REVIEW_REQUIRED's actual current default
    (suspended 2026-09-04 at the user's request) — no override here, so
    this exercises the real out-of-the-box behavior: a Public post is
    treated like Connections/Cohort, visible immediately with no admin
    step. Doesn't duplicate PublicAudienceApprovalTests' mechanism
    coverage (that stays valid for whenever the flag is switched back on)."""

    def setUp(self):
        self.author = make_user('+255700000211', 'Author')
        self.other = make_user('+255700000212', 'Other')  # not connected, no shared cohort

    def test_create_post_with_public_audience_is_not_required_by_default(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('create_post'), {'body': 'going public', 'audience': 'public'})
        self.assertEqual(response.status_code, 200)
        post = Post.objects.get()
        self.assertEqual(post.audience, Post.Audience.PUBLIC)
        self.assertEqual(post.approval_status, Post.ApprovalStatus.NOT_REQUIRED)

    def test_public_post_is_immediately_visible_to_a_stranger_by_default(self):
        self.client.force_login(self.author)
        self.client.post(reverse('create_post'), {'body': 'going public', 'audience': 'public'})
        post = Post.objects.get()
        self.assertIn(post, get_feed_for_user(self.other))

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

    def test_admin_approve_action_notifies_the_author(self):
        from posts.admin import approve_posts
        post = Post.objects.create(
            author=self.author, body='pending public', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.PENDING,
        )
        approve_posts(None, None, Post.objects.filter(pk=post.pk))
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.author)
        self.assertEqual(notification.verb, Notification.Verb.POST_APPROVED)
        self.assertIsNone(notification.actor)  # admin action called with request=None
        self.assertEqual(notification.target, post)

    def test_admin_reject_action_notifies_the_author(self):
        from posts.admin import reject_posts
        post = Post.objects.create(
            author=self.author, body='pending public', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.PENDING,
        )
        reject_posts(None, None, Post.objects.filter(pk=post.pk))
        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.author)
        self.assertEqual(notification.verb, Notification.Verb.POST_REJECTED)

    def test_approve_action_does_not_notify_already_resolved_posts(self):
        from posts.admin import approve_posts
        post = Post.objects.create(
            author=self.author, body='already approved', audience=Post.Audience.PUBLIC,
            approval_status=Post.ApprovalStatus.APPROVED,
        )
        approve_posts(None, None, Post.objects.filter(pk=post.pk))
        self.assertEqual(Notification.objects.count(), 0)  # not PENDING, action's own filter excludes it


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


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class EditPostTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000060', 'Author')
        self.stranger = make_user('+255700000070', 'Stranger')
        self.post = Post.objects.create(author=self.author, body='original text')

    def test_requires_authentication(self):
        response = self.client.post(reverse('edit_post', kwargs={'post_id': self.post.id}), {'body': 'new text'})
        self.assertEqual(response.status_code, 401)

    def test_author_can_edit_body(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('edit_post', kwargs={'post_id': self.post.id}), {'body': 'updated text'})
        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.body, 'updated text')
        self.assertIsNotNone(self.post.edited_at)

    def test_non_author_cannot_edit(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('edit_post', kwargs={'post_id': self.post.id}), {'body': 'hijacked'})
        self.assertEqual(response.status_code, 404)
        self.post.refresh_from_db()
        self.assertEqual(self.post.body, 'original text')
        self.assertIsNone(self.post.edited_at)

    def test_edit_to_empty_body_rejected_when_no_media(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('edit_post', kwargs={'post_id': self.post.id}), {'body': '   '})
        self.assertEqual(response.status_code, 400)
        self.post.refresh_from_db()
        self.assertEqual(self.post.body, 'original text')

    def test_edit_to_empty_body_allowed_when_post_has_media(self):
        asset = make_asset(self.author)
        post = Post.objects.create(author=self.author, body='caption', media_asset=asset)
        self.client.force_login(self.author)
        response = self.client.post(reverse('edit_post', kwargs={'post_id': post.id}), {'body': ''})
        self.assertEqual(response.status_code, 200)
        post.refresh_from_db()
        self.assertEqual(post.body, '')


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class DeletePostTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000080', 'Author')
        self.stranger = make_user('+255700000090', 'Stranger')
        self.post = Post.objects.create(author=self.author, body='doomed post')

    def test_requires_authentication(self):
        response = self.client.post(reverse('delete_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 401)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())

    def test_author_can_delete_own_post(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('delete_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=self.post.pk).exists())

    def test_non_author_cannot_delete(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('delete_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())

    def test_deleting_post_leaves_attached_media_asset_intact(self):
        asset = make_asset(self.author)
        post = Post.objects.create(author=self.author, body='with photo', media_asset=asset)
        self.client.force_login(self.author)
        response = self.client.post(reverse('delete_post', kwargs={'post_id': post.id}))
        self.assertEqual(response.status_code, 200)
        asset.refresh_from_db()  # SET_NULL on Post.media_asset — the row survives


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class HidePostTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000100', 'Author')
        self.viewer = make_user('+255700000110', 'Viewer')
        self.stranger = make_user('+255700000120', 'Stranger')  # not connected, no shared cohort
        connect(self.author, self.viewer)
        self.post = Post.objects.create(author=self.author, body='hide me maybe')

    def test_requires_authentication(self):
        response = self.client.post(reverse('hide_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 401)

    def test_viewer_can_hide_a_visible_post(self):
        self.client.force_login(self.viewer)
        response = self.client.post(reverse('hide_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PostHiddenFor.objects.filter(post=self.post, user=self.viewer).exists())

    def test_hidden_post_excluded_from_that_viewers_feed_only(self):
        PostHiddenFor.objects.create(post=self.post, user=self.viewer)
        self.assertNotIn(self.post, get_feed_for_user(self.viewer))
        self.assertIn(self.post, get_feed_for_user(self.author))

    def test_cannot_hide_a_post_you_cannot_see(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('hide_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(PostHiddenFor.objects.filter(post=self.post, user=self.stranger).exists())

    def test_hiding_already_hidden_post_is_idempotent(self):
        self.client.force_login(self.viewer)
        first = self.client.post(reverse('hide_post', kwargs={'post_id': self.post.id}))
        second = self.client.post(reverse('hide_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PostHiddenFor.objects.filter(post=self.post, user=self.viewer).count(), 1)

    def test_hiding_own_post_removes_it_from_own_feed(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('hide_post', kwargs={'post_id': self.post.id}))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.post, get_feed_for_user(self.author))


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class BlockedAndMutedVisibilityTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000130', 'Author')
        self.other = make_user('+255700000140', 'Other')
        connect(self.author, self.other)
        self.post = Post.objects.create(author=self.author, body='visible to connections')

    def test_block_by_viewer_hides_authors_posts(self):
        UserRelationshipOverride.objects.create(
            actor=self.other, target=self.author, type=UserRelationshipOverride.Type.BLOCK
        )
        self.assertNotIn(self.post, get_feed_for_user(self.other))

    def test_block_by_author_hides_their_posts_from_the_blocked_user(self):
        # Same effect regardless of who initiated the block — is_blocked is symmetric.
        UserRelationshipOverride.objects.create(
            actor=self.author, target=self.other, type=UserRelationshipOverride.Type.BLOCK
        )
        self.assertNotIn(self.post, get_feed_for_user(self.other))

    def test_block_also_removes_post_image_authorization(self):
        asset = make_asset(self.author)
        post = Post.objects.create(author=self.author, body='pic', media_asset=asset)
        UserRelationshipOverride.objects.create(
            actor=self.other, target=self.author, type=UserRelationshipOverride.Type.BLOCK
        )
        self.client.force_login(self.other)
        response = self.client.get(reverse('post_image', kwargs={'post_id': post.id}))
        self.assertEqual(response.status_code, 404)

    def test_author_still_sees_own_posts_after_being_blocked(self):
        UserRelationshipOverride.objects.create(
            actor=self.other, target=self.author, type=UserRelationshipOverride.Type.BLOCK
        )
        self.assertIn(self.post, get_feed_for_user(self.author))

    def test_mute_hides_authors_posts_from_muter_only(self):
        UserRelationshipOverride.objects.create(
            actor=self.other, target=self.author, type=UserRelationshipOverride.Type.MUTE
        )
        self.assertNotIn(self.post, get_feed_for_user(self.other))
        self.assertIn(self.post, get_feed_for_user(self.author))

    def test_mute_does_not_block_post_image_authorization(self):
        asset = make_asset(self.author)
        post = Post.objects.create(author=self.author, body='pic', media_asset=asset)
        UserRelationshipOverride.objects.create(
            actor=self.other, target=self.author, type=UserRelationshipOverride.Type.MUTE
        )
        self.client.force_login(self.other)
        response = self.client.get(reverse('post_image', kwargs={'post_id': post.id}))
        self.assertEqual(response.status_code, 302)  # muted, not blocked — image still viewable


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ReportPostTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000150', 'Author')
        self.viewer = make_user('+255700000160', 'Viewer')
        self.stranger = make_user('+255700000170', 'Stranger')  # not connected, no shared cohort
        connect(self.author, self.viewer)
        self.post = Post.objects.create(author=self.author, body='reportable post')

    def test_requires_authentication(self):
        response = self.client.post(reverse('report_post', kwargs={'post_id': self.post.id}), {'category': 'spam'})
        self.assertEqual(response.status_code, 401)

    def test_cannot_report_a_post_you_cannot_see(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('report_post', kwargs={'post_id': self.post.id}), {'category': 'spam'})
        self.assertEqual(response.status_code, 404)

    def test_cannot_report_own_post(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('report_post', kwargs={'post_id': self.post.id}), {'category': 'spam'})
        self.assertEqual(response.status_code, 400)

    def test_missing_category_rejected(self):
        self.client.force_login(self.viewer)
        response = self.client.post(reverse('report_post', kwargs={'post_id': self.post.id}), {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ContentReport.objects.count(), 0)

    def test_report_puts_connections_post_under_review_and_hides_it(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse('report_post', kwargs={'post_id': self.post.id}),
            {'category': 'harassment', 'description': 'targeted at me'},
        )
        self.assertEqual(response.status_code, 200)

        self.post.refresh_from_db()
        self.assertEqual(self.post.approval_status, Post.ApprovalStatus.PENDING)
        self.assertNotIn(self.post, get_feed_for_user(self.viewer))
        self.assertIn(self.post, get_feed_for_user(self.author))  # author still sees own post

        report = ContentReport.objects.get()
        self.assertEqual(report.reporter, self.viewer)
        self.assertEqual(report.category, ContentReport.Category.HARASSMENT)

    def test_report_opens_a_user_report_hold(self):
        self.client.force_login(self.viewer)
        self.client.post(reverse('report_post', kwargs={'post_id': self.post.id}), {'category': 'spam'})
        hold = ModerationHold.objects.get()
        self.assertEqual(hold.reason, ModerationHold.Reason.USER_REPORT)
        self.assertEqual(hold.status, ModerationHold.Status.PENDING)

    def test_admin_approve_restores_visibility_after_report(self):
        from posts.admin import approve_posts
        self.client.force_login(self.viewer)
        self.client.post(reverse('report_post', kwargs={'post_id': self.post.id}), {'category': 'spam'})

        approve_posts(None, None, Post.objects.filter(pk=self.post.pk))
        self.post.refresh_from_db()
        self.assertEqual(self.post.approval_status, Post.ApprovalStatus.APPROVED)
        self.assertIn(self.post, get_feed_for_user(self.viewer))

    def test_admin_reject_keeps_it_hidden_after_report(self):
        from posts.admin import reject_posts
        self.client.force_login(self.viewer)
        self.client.post(reverse('report_post', kwargs={'post_id': self.post.id}), {'category': 'spam'})

        reject_posts(None, None, Post.objects.filter(pk=self.post.pk))
        self.post.refresh_from_db()
        self.assertEqual(self.post.approval_status, Post.ApprovalStatus.REJECTED)
        self.assertNotIn(self.post, get_feed_for_user(self.viewer))
        self.assertIn(self.post, get_feed_for_user(self.author))


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ReportPostMediaTests(TestCase):
    def setUp(self):
        self.author = make_user('+255700000180', 'Author')
        self.viewer = make_user('+255700000190', 'Viewer')
        self.stranger = make_user('+255700000200', 'Stranger')
        connect(self.author, self.viewer)
        self.asset = make_asset(self.author)
        self.post = Post.objects.create(author=self.author, body='pic post', media_asset=self.asset)

    def test_requires_authentication(self):
        response = self.client.post(reverse('report_post_media', kwargs={'post_id': self.post.id}), {'category': 'nudity'})
        self.assertEqual(response.status_code, 401)

    def test_cannot_report_media_on_a_post_you_cannot_see(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('report_post_media', kwargs={'post_id': self.post.id}), {'category': 'nudity'})
        self.assertEqual(response.status_code, 404)

    def test_cannot_report_own_media(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('report_post_media', kwargs={'post_id': self.post.id}), {'category': 'nudity'})
        self.assertEqual(response.status_code, 400)

    def test_post_with_no_media_404s(self):
        text_post = Post.objects.create(author=self.author, body='no photo here')
        self.client.force_login(self.viewer)
        response = self.client.post(reverse('report_post_media', kwargs={'post_id': text_post.id}), {'category': 'nudity'})
        self.assertEqual(response.status_code, 404)

    def test_report_holds_the_media_but_leaves_the_post_visible(self):
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse('report_post_media', kwargs={'post_id': self.post.id}), {'category': 'nudity'}
        )
        self.assertEqual(response.status_code, 200)

        self.asset.refresh_from_db()
        self.assertTrue(self.asset.moderation_hold)
        self.assertFalse(self.asset.is_downloadable)

        self.post.refresh_from_db()
        self.assertEqual(self.post.approval_status, Post.ApprovalStatus.NOT_REQUIRED)
        self.assertIn(self.post, get_feed_for_user(self.viewer))  # post itself stays visible

        image_response = self.client.get(reverse('post_image', kwargs={'post_id': self.post.id}))
        self.assertEqual(image_response.status_code, 404)  # but the image is now held


@override_settings(MEDIA_ASSETS_S3_ENABLED=False, RATE_LIMIT_CREATE_POST_MAX=2, RATE_LIMIT_CREATE_POST_WINDOW_SECONDS=60)
class CreatePostRateLimitTests(TestCase):
    """Phase 6: create_post's rate limit, scoped to post creation only per
    the user's 2026-09-04 decision — see ratelimiting/tests.py for the
    underlying is_rate_limited() unit tests. Limit forced down to 2/60s
    here so tests don't need to actually create 5+ posts."""

    def setUp(self):
        self.author = make_user('+255700000221', 'Author')
        self.client.force_login(self.author)

    def test_allows_up_to_the_limit(self):
        for _ in range(2):
            response = self.client.post(reverse('create_post'), {'body': 'hello', 'audience': 'connections'})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Post.objects.count(), 2)

    def test_blocks_once_over_the_limit(self):
        for _ in range(2):
            self.client.post(reverse('create_post'), {'body': 'hello', 'audience': 'connections'})
        response = self.client.post(reverse('create_post'), {'body': 'one too many', 'audience': 'connections'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(Post.objects.count(), 2)  # the blocked attempt created no post

    def test_failed_attempt_does_not_count_against_the_limit(self):
        # An empty post (no body, no media) fails validation before the
        # rate-limit check even runs — see create_post's ordering — so it
        # must not eat into the user's quota.
        for _ in range(3):
            response = self.client.post(reverse('create_post'), {'body': '', 'audience': 'connections'})
            self.assertEqual(response.status_code, 400)

        response = self.client.post(reverse('create_post'), {'body': 'real post', 'audience': 'connections'})
        self.assertEqual(response.status_code, 200)

    def test_limit_is_per_user(self):
        for _ in range(2):
            self.client.post(reverse('create_post'), {'body': 'hello', 'audience': 'connections'})

        other = make_user('+255700000222', 'Other')
        self.client.force_login(other)
        response = self.client.post(reverse('create_post'), {'body': 'hi from other', 'audience': 'connections'})
        self.assertEqual(response.status_code, 200)
