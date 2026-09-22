import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from connections.models import Connection
from media_assets.models import MediaAsset
from messaging.models import Conversation, ConversationMember, Message
from notifications.models import Notification
from posts.models import Post


def make_user(identifier, full_name='Test User'):
    return User.objects.create_user(phone_or_email=identifier, password='Testing2026!', full_name=full_name)


def connect(a, b):
    Connection.objects.create(requester=a, receiver=b, status='accepted')


def make_asset(owner, status=MediaAsset.Status.READY, moderation_hold=False):
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
        is_attached=True,
    )


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class SharePostTests(TestCase):
    """config.views.share_post — sends a post into a chat with an accepted
    connection (Instagram's "send in a DM" pattern), see that view's
    docstring for why it lives in config.views rather than posts.views."""

    def setUp(self):
        self.alice = make_user('+255700000901', 'Alice')
        self.bob = make_user('+255700000902', 'Bob')
        self.stranger = make_user('+255700000903', 'Stranger')
        connect(self.alice, self.bob)
        self.post = Post.objects.create(author=self.alice, body='hello everyone', audience=Post.Audience.CONNECTIONS)

    def test_requires_authentication(self):
        response = self.client.post(reverse('share_post', args=[self.post.id]), {'user_id': str(self.bob.id)})
        self.assertEqual(response.status_code, 401)

    def test_cannot_share_a_post_you_cannot_see(self):
        # Carol (stranger) is not connected to Alice, so a Connections-
        # audience post is invisible to her -- can_view_post fails closed.
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('share_post', args=[self.post.id]), {'user_id': str(self.bob.id)})
        self.assertEqual(response.status_code, 404)

    def test_cannot_share_with_a_non_connection(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('share_post', args=[self.post.id]), {'user_id': str(self.stranger.id)})
        self.assertEqual(response.status_code, 400)

    def test_share_creates_conversation_and_message(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('share_post', args=[self.post.id]), {'user_id': str(self.bob.id)})
        self.assertEqual(response.status_code, 200)

        conversation = Conversation.objects.get(id=response.json()['conversation_id'])
        self.assertTrue(ConversationMember.objects.filter(conversation=conversation, user=self.alice).exists())
        self.assertTrue(ConversationMember.objects.filter(conversation=conversation, user=self.bob).exists())

        message = Message.objects.get(conversation=conversation)
        self.assertEqual(message.sender, self.alice)
        self.assertIn('hello everyone', message.body)
        self.assertTrue(Notification.objects.filter(recipient=self.bob, verb=Notification.Verb.NEW_MESSAGE).exists())

    def test_share_reuses_existing_conversation(self):
        key = Conversation.direct_key_for(self.alice, self.bob)
        existing = Conversation.objects.create(type=Conversation.ConversationType.DIRECT, direct_key=key)
        ConversationMember.objects.create(conversation=existing, user=self.alice)
        ConversationMember.objects.create(conversation=existing, user=self.bob)

        self.client.force_login(self.alice)
        response = self.client.post(reverse('share_post', args=[self.post.id]), {'user_id': str(self.bob.id)})
        self.assertEqual(response.json()['conversation_id'], str(existing.id))
        self.assertEqual(Conversation.objects.count(), 1)

    def test_share_reattaches_the_posts_media_asset(self):
        asset = make_asset(self.alice)
        post = Post.objects.create(author=self.alice, media_asset=asset, audience=Post.Audience.CONNECTIONS)

        self.client.force_login(self.alice)
        response = self.client.post(reverse('share_post', args=[post.id]), {'user_id': str(self.bob.id)})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()['image_url'])

        message = Message.objects.get(conversation_id=response.json()['conversation_id'])
        self.assertEqual(message.attachment.media_asset_id, asset.id)

    def test_sharing_own_post_uses_the_my_post_wording(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('share_post', args=[self.post.id]), {'user_id': str(self.bob.id)})
        message = Message.objects.get(conversation_id=response.json()['conversation_id'])
        self.assertIn('Shared my post', message.body)
