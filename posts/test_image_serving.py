"""The feed, chat bubbles and lightbox serve the full-resolution image; the
320px-era thumbnail is an explicit opt-in for tiny tiles only."""
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from connections.models import Connection
from media_assets import services as media_services
from media_assets.storage import LocalMediaBackend
from messaging.models import Message, MessageAttachment
from messaging.tests import make_asset as make_chat_asset
from messaging.tests import make_direct_conversation

from .models import Post
from .tests import make_asset

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
SIGNED = 'https://signed.example/object'


def person(ident, name):
    return User.objects.create_user(phone_or_email=ident, password='x', full_name=name)


def with_thumbnail(asset):
    asset.thumbnail_storage_key = 'private/thumbnails/%s.jpg' % asset.id
    asset.save(update_fields=['thumbnail_storage_key'])
    return asset


def signed_key(url):
    token = parse_qs(urlparse(url).query)['token'][0]
    return LocalMediaBackend.unsign_download_token(token, max_age=300)['key']


@FAST_HASH
@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ServiceVariantTests(TestCase):
    """get_preview_url really does pick different stored objects."""

    def test_full_returns_the_processed_image_and_thumb_the_thumbnail(self):
        owner = person('+255766000001', 'Owner')
        asset = with_thumbnail(make_asset(owner))
        self.assertEqual(signed_key(media_services.get_preview_url(asset, full=True)), asset.storage_key)
        self.assertEqual(signed_key(media_services.get_preview_url(asset, full=False)), asset.thumbnail_storage_key)


@FAST_HASH
@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class FeedImageQualityTests(TestCase):
    def setUp(self):
        self.author = person('+255766000010', 'Author')
        self.friend = person('+255766000011', 'Friend')
        Connection.objects.create(requester=self.author, receiver=self.friend, status='accepted')
        self.asset = with_thumbnail(make_asset(self.author))
        self.post = Post.objects.create(author=self.author, body='holiday', media_asset=self.asset)
        self.url = reverse('post_image', kwargs={'post_id': self.post.id})

    def variant_served(self, who, query=''):
        self.client.force_login(who)
        with mock.patch('media_assets.services.get_preview_url', return_value=SIGNED) as spy:
            response = self.client.get(self.url + query)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, SIGNED)
        return spy.call_args.kwargs['full']

    def test_feed_image_is_full_resolution_by_default_for_author_and_viewers(self):
        self.assertTrue(self.variant_served(self.author))
        self.assertTrue(self.variant_served(self.friend))

    def test_thumbnail_is_only_served_when_explicitly_requested(self):
        self.assertFalse(self.variant_served(self.author, '?size=thumb'))

    def test_unknown_size_values_do_not_downgrade_quality(self):
        self.assertTrue(self.variant_served(self.author, '?size=tiny'))
        self.assertTrue(self.variant_served(self.author, '?size='))

    def test_real_redirect_points_at_the_full_object_not_the_thumbnail(self):
        self.client.force_login(self.friend)
        self.assertEqual(signed_key(self.client.get(self.url).url), self.asset.storage_key)
        self.assertEqual(signed_key(self.client.get(self.url + '?size=thumb').url), self.asset.thumbnail_storage_key)

    def test_size_option_does_not_bypass_authorization(self):
        stranger = person('+255766000012', 'Stranger')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url + '?size=thumb').status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_home_feed_markup_asks_for_the_full_image(self):
        self.client.force_login(self.author)
        html = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn(self.url, html)
        self.assertNotIn('size=thumb', html)

    def test_profile_grid_tiles_ask_for_the_thumbnail(self):
        self.client.force_login(self.author)
        self.assertIn(self.url + '?size=thumb', self.client.get(reverse('profile')).content.decode())


@FAST_HASH
@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ChatImageQualityTests(TestCase):
    def setUp(self):
        self.alice = person('+255766000020', 'Alice')
        self.bob = person('+255766000021', 'Bob')
        self.conv = make_direct_conversation(self.alice, self.bob)
        self.asset = with_thumbnail(make_chat_asset(self.alice))
        self.message = Message.objects.create(conversation=self.conv, sender=self.alice, body='pic')
        MessageAttachment.objects.create(message=self.message, media_asset=self.asset)
        self.url = reverse('message_attachment_image', args=[self.message.id])

    def variant_served(self, query=''):
        self.client.force_login(self.bob)
        with mock.patch('media_assets.services.get_preview_url', return_value=SIGNED) as spy:
            response = self.client.get(self.url + query)
        self.assertEqual(response.status_code, 302)
        return spy.call_args.kwargs['full']

    def test_bubbles_get_the_full_image_by_default(self):
        self.assertTrue(self.variant_served())

    def test_legacy_full_flag_still_works(self):
        self.assertTrue(self.variant_served('?full=1'))

    def test_thumbnail_is_opt_in(self):
        self.assertFalse(self.variant_served('?size=thumb'))

    def test_real_redirect_points_at_the_full_object(self):
        self.client.force_login(self.bob)
        self.assertEqual(signed_key(self.client.get(self.url).url), self.asset.storage_key)

    def test_thread_page_bubble_markup_uses_the_plain_url(self):
        self.client.force_login(self.alice)
        html = self.client.get(reverse('messages_thread', args=[self.conv.id])).content.decode()
        self.assertIn('src="%s"' % self.url, html)
        self.assertNotIn('size=thumb', html)

    def test_non_participants_still_cannot_fetch_any_variant(self):
        stranger = person('+255766000022', 'Stranger')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(self.url + '?size=thumb').status_code, 404)
