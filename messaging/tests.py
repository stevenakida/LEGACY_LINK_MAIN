import os
import shutil
import tempfile
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from connections.models import Connection
from media_assets.models import MediaAsset

from .models import Conversation, ConversationMember, Message, MessageAttachment, MessageHiddenFor


def make_user(identifier, full_name='Test User'):
    return User.objects.create_user(phone_or_email=identifier, password='Testing2026!', full_name=full_name)


def make_asset(owner, status=MediaAsset.Status.READY, moderation_hold=False):
    # storage_key/quarantine_storage_key are unique=True — a fixed
    # per-owner path collides the moment a test creates more than one
    # asset for the same owner, so give each call its own random token
    # like the real media_assets pipeline does.
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


def make_direct_conversation(a, b):
    Connection.objects.create(requester=a, receiver=b, status='accepted')
    conv = Conversation.objects.create(
        type=Conversation.ConversationType.DIRECT, direct_key=Conversation.direct_key_for(a, b)
    )
    ConversationMember.objects.create(conversation=conv, user=a)
    ConversationMember.objects.create(conversation=conv, user=b)
    return conv


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class MessagesSendAttachmentTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700000301', 'Alice')
        self.bob = make_user('+255700000302', 'Bob')
        self.stranger = make_user('+255700000303', 'Stranger')
        self.conv = make_direct_conversation(self.alice, self.bob)
        self.client.force_login(self.alice)

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': 'hi'})
        self.assertEqual(response.status_code, 401)

    def test_non_participant_cannot_send(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': 'hi'})
        self.assertEqual(response.status_code, 404)

    def test_rejects_empty_message_with_no_attachment(self):
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': '  '})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), 0)

    def test_text_only_message_still_works(self):
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': 'hello'})
        self.assertEqual(response.status_code, 200)
        message = Message.objects.get()
        self.assertEqual(message.body, 'hello')
        self.assertFalse(message.has_attachment)

    def test_image_only_message_allowed(self):
        asset = make_asset(self.alice)
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': '', 'media_id': str(asset.id)})
        self.assertEqual(response.status_code, 200)
        message = Message.objects.get()
        self.assertEqual(message.body, '')
        self.assertTrue(message.has_attachment)
        asset.refresh_from_db()
        self.assertTrue(asset.is_attached)

    def test_rejects_attaching_another_users_asset(self):
        asset = make_asset(self.bob)
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': 'sneaky', 'media_id': str(asset.id)})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Message.objects.count(), 0)

    def test_rejects_attaching_a_not_ready_asset(self):
        asset = make_asset(self.alice, status=MediaAsset.Status.PROCESSING)
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': 'too soon', 'media_id': str(asset.id)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Message.objects.count(), 0)

    def test_one_attachment_per_message_enforced_at_db_level(self):
        asset = make_asset(self.alice)
        message = Message.objects.create(conversation=self.conv, sender=self.alice, body='pic')
        MessageAttachment.objects.create(message=message, media_asset=asset)
        with self.assertRaises(Exception):
            MessageAttachment.objects.create(message=message, media_asset=make_asset(self.alice))


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class MessageAttachmentImageAuthorizationTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700000401', 'Alice')
        self.bob = make_user('+255700000402', 'Bob')
        self.stranger = make_user('+255700000403', 'Stranger')
        self.conv = make_direct_conversation(self.alice, self.bob)

        asset = make_asset(self.alice)
        self.message = Message.objects.create(conversation=self.conv, sender=self.alice, body='pic')
        MessageAttachment.objects.create(message=self.message, media_asset=asset)

    def test_requires_authentication(self):
        response = self.client.get(reverse('message_attachment_image', args=[self.message.id]))
        self.assertEqual(response.status_code, 401)

    def test_non_participant_cannot_view(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('message_attachment_image', args=[self.message.id]))
        self.assertEqual(response.status_code, 404)

    def test_sender_can_view(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse('message_attachment_image', args=[self.message.id]))
        self.assertEqual(response.status_code, 302)

    def test_other_participant_can_view(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse('message_attachment_image', args=[self.message.id]))
        self.assertEqual(response.status_code, 302)

    def test_message_with_no_attachment_404s(self):
        plain_message = Message.objects.create(conversation=self.conv, sender=self.alice, body='no pic')
        self.client.force_login(self.bob)
        response = self.client.get(reverse('message_attachment_image', args=[plain_message.id]))
        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class MessageAttachmentDownloadTests(TestCase):
    def setUp(self):
        self._local_root = tempfile.mkdtemp(prefix='messaging_download_test_')
        self._root_override = override_settings(MEDIA_ASSETS_LOCAL_ROOT=self._local_root)
        self._root_override.enable()
        self.addCleanup(self._root_override.disable)
        self.addCleanup(shutil.rmtree, self._local_root, ignore_errors=True)

        self.alice = make_user('+255700000501', 'Alice')
        self.bob = make_user('+255700000502', 'Bob')
        self.stranger = make_user('+255700000503', 'Stranger')
        self.conv = make_direct_conversation(self.alice, self.bob)

        asset = make_asset(self.alice)
        # message_attachment_download's 302 target is a *real* file-backed
        # download proxy (LocalDownloadProxyView) — it 404s unless the
        # bytes actually exist at the asset's storage_key, same as the
        # real upload pipeline would have written. make_asset() only
        # creates the DB row, so write the file it points at directly.
        asset_path = os.path.join(self._local_root, asset.storage_key)
        os.makedirs(os.path.dirname(asset_path), exist_ok=True)
        with open(asset_path, 'wb') as f:
            f.write(b'fake-jpeg-bytes')
        self.message = Message.objects.create(conversation=self.conv, sender=self.alice, body='pic')
        MessageAttachment.objects.create(message=self.message, media_asset=asset)

    def test_requires_authentication(self):
        response = self.client.get(reverse('message_attachment_download', args=[self.message.id]))
        self.assertEqual(response.status_code, 401)

    def test_non_participant_cannot_download(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('message_attachment_download', args=[self.message.id]))
        self.assertEqual(response.status_code, 404)

    def test_participant_download_redirects_to_attachment_disposition_url(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse('message_attachment_download', args=[self.message.id]))
        self.assertEqual(response.status_code, 302)
        # Local backend encodes the signed token as a query string on the
        # local-proxy URL; following it should yield a real download
        # response with Content-Disposition: attachment.
        download_response = self.client.get(response.url)
        self.assertEqual(download_response.status_code, 200)
        self.assertIn('attachment', download_response['Content-Disposition'])


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class DeleteForMeTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700000601', 'Alice')
        self.bob = make_user('+255700000602', 'Bob')
        self.stranger = make_user('+255700000603', 'Stranger')
        self.conv = make_direct_conversation(self.alice, self.bob)
        # A distinctive body, not the word "hello" — the chat thread's own
        # empty-state copy ("Say hello 👋 — you're now connected...")
        # contains that substring, so assertNotContains(resp, 'hello')
        # would false-negative against unrelated UI text once this message
        # is actually hidden and the empty state re-appears.
        self.message = Message.objects.create(conversation=self.conv, sender=self.alice, body='xyzzy-marker-message')

    def test_requires_authentication(self):
        response = self.client.post(reverse('messages_delete_for_me', args=[self.message.id]))
        self.assertEqual(response.status_code, 401)

    def test_non_participant_cannot_hide(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('messages_delete_for_me', args=[self.message.id]))
        self.assertEqual(response.status_code, 404)

    def test_hides_message_for_requester_only(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse('messages_delete_for_me', args=[self.message.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MessageHiddenFor.objects.filter(message=self.message, user=self.alice).exists())

        self.client.force_login(self.alice)
        thread_resp = self.client.get(reverse('messages_thread', args=[self.conv.id]))
        self.assertNotContains(thread_resp, 'xyzzy-marker-message')

        self.client.force_login(self.bob)
        thread_resp = self.client.get(reverse('messages_thread', args=[self.conv.id]))
        self.assertContains(thread_resp, 'xyzzy-marker-message')

    def test_hiding_twice_is_idempotent(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('messages_delete_for_me', args=[self.message.id]))
        response = self.client.post(reverse('messages_delete_for_me', args=[self.message.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MessageHiddenFor.objects.filter(message=self.message, user=self.alice).count(), 1)

    def test_hidden_message_excluded_from_poll(self):
        MessageHiddenFor.objects.create(message=self.message, user=self.alice)
        self.client.force_login(self.alice)
        response = self.client.get(reverse('messages_poll', args=[self.conv.id]))
        ids = [m['id'] for m in response.json()['messages']]
        self.assertNotIn(str(self.message.id), ids)


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ReplyTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700000701', 'Alice')
        self.bob = make_user('+255700000702', 'Bob')
        self.conv = make_direct_conversation(self.alice, self.bob)
        self.other_user = make_user('+255700000703', 'Carol')
        self.other_conv = make_direct_conversation(self.alice, self.other_user)
        self.original = Message.objects.create(conversation=self.conv, sender=self.bob, body='original message')
        self.client.force_login(self.alice)

    def test_reply_within_same_conversation(self):
        response = self.client.post(
            reverse('messages_send', args=[self.conv.id]),
            {'body': 'replying', 'reply_to': str(self.original.id)},
        )
        self.assertEqual(response.status_code, 200)
        message = Message.objects.get(body='replying')
        self.assertEqual(message.reply_to_id, self.original.id)
        self.assertEqual(response.json()['reply_to']['sender_name'], 'Bob')

    def test_reply_to_message_from_another_conversation_rejected(self):
        foreign_message = Message.objects.create(conversation=self.other_conv, sender=self.other_user, body='elsewhere')
        response = self.client.post(
            reverse('messages_send', args=[self.conv.id]),
            {'body': 'sneaky reply', 'reply_to': str(foreign_message.id)},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(body='sneaky reply').exists())


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class ForwardTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700000801', 'Alice')
        self.bob = make_user('+255700000802', 'Bob')
        self.carol = make_user('+255700000803', 'Carol')
        self.stranger = make_user('+255700000804', 'Stranger')
        self.conv_ab = make_direct_conversation(self.alice, self.bob)
        self.conv_ac = make_direct_conversation(self.alice, self.carol)
        asset = make_asset(self.bob)
        self.original = Message.objects.create(conversation=self.conv_ab, sender=self.bob, body='forward me')
        MessageAttachment.objects.create(message=self.original, media_asset=asset)

    def test_requires_authentication(self):
        response = self.client.post(reverse('messages_forward', args=[self.original.id]))
        self.assertEqual(response.status_code, 401)

    def test_non_participant_of_source_cannot_forward(self):
        self.client.force_login(self.stranger)
        response = self.client.post(
            reverse('messages_forward', args=[self.original.id]),
            {'target_conversation_id': str(self.conv_ac.id)},
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_forward_into_a_conversation_not_a_participant_of(self):
        other_conv = make_direct_conversation(self.bob, self.carol)
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse('messages_forward', args=[self.original.id]),
            {'target_conversation_id': str(other_conv.id)},
        )
        self.assertEqual(response.status_code, 404)

    def test_forward_succeeds_without_owning_the_attached_asset(self):
        """Alice didn't upload Bob's photo, but she saw it via the message
        she's forwarding — that's the deliberately narrower-but-different
        authorization boundary documented on messages_forward."""
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse('messages_forward', args=[self.original.id]),
            {'target_conversation_id': str(self.conv_ac.id)},
        )
        self.assertEqual(response.status_code, 200)
        forwarded = Message.objects.get(conversation=self.conv_ac)
        self.assertEqual(forwarded.sender, self.alice)
        self.assertEqual(forwarded.body, 'forward me')
        self.assertEqual(forwarded.forwarded_from_id, self.original.id)
        self.assertTrue(forwarded.has_attachment)
        self.assertEqual(forwarded.attachment.media_asset_id, self.original.attachment.media_asset_id)

    def test_forwarding_a_moderation_held_asset_drops_the_image_not_the_message(self):
        held_asset = make_asset(self.bob, moderation_hold=True)
        held_message = Message.objects.create(conversation=self.conv_ab, sender=self.bob, body='held photo')
        MessageAttachment.objects.create(message=held_message, media_asset=held_asset)

        self.client.force_login(self.alice)
        response = self.client.post(
            reverse('messages_forward', args=[held_message.id]),
            {'target_conversation_id': str(self.conv_ac.id)},
        )
        self.assertEqual(response.status_code, 200)
        forwarded = Message.objects.get(conversation=self.conv_ac, body='held photo')
        self.assertFalse(forwarded.has_attachment)
        self.assertIsNone(response.json()['image_url'])

    def test_forwarded_message_visible_only_in_target_conversation(self):
        self.client.force_login(self.alice)
        self.client.post(
            reverse('messages_forward', args=[self.original.id]),
            {'target_conversation_id': str(self.conv_ac.id)},
        )
        self.client.force_login(self.carol)
        response = self.client.get(reverse('messages_thread', args=[self.conv_ac.id]))
        self.assertContains(response, 'forward me')

        self.client.force_login(self.stranger)
        # stranger isn't a participant of conv_ac at all
        response = self.client.get(reverse('messages_thread', args=[self.conv_ac.id]))
        self.assertEqual(response.status_code, 302)  # redirected away, not a participant
