from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from messaging.models import Conversation, ConversationMember

from .models import Connection, UserRelationshipOverride


def make_user(identifier, full_name='Test User'):
    return User.objects.create_user(phone_or_email=identifier, password='Testing2026!', full_name=full_name)


class UserRelationshipOverrideModelTests(TestCase):
    def setUp(self):
        self.a = make_user('+255700000201', 'Alice')
        self.b = make_user('+255700000202', 'Bob')
        self.c = make_user('+255700000203', 'Carol')

    def test_is_blocked_true_regardless_of_which_side_blocked(self):
        UserRelationshipOverride.objects.create(actor=self.a, target=self.b, type=UserRelationshipOverride.Type.BLOCK)
        self.assertTrue(UserRelationshipOverride.is_blocked(self.a, self.b))
        self.assertTrue(UserRelationshipOverride.is_blocked(self.b, self.a))

    def test_is_blocked_false_for_unrelated_pair(self):
        UserRelationshipOverride.objects.create(actor=self.a, target=self.b, type=UserRelationshipOverride.Type.BLOCK)
        self.assertFalse(UserRelationshipOverride.is_blocked(self.a, self.c))

    def test_blocked_partner_ids_includes_both_directions(self):
        UserRelationshipOverride.objects.create(actor=self.a, target=self.b, type=UserRelationshipOverride.Type.BLOCK)
        UserRelationshipOverride.objects.create(actor=self.c, target=self.a, type=UserRelationshipOverride.Type.BLOCK)
        self.assertEqual(UserRelationshipOverride.blocked_partner_ids(self.a), {self.b.id, self.c.id})

    def test_muted_author_ids_is_one_directional(self):
        UserRelationshipOverride.objects.create(actor=self.a, target=self.b, type=UserRelationshipOverride.Type.MUTE)
        self.assertEqual(UserRelationshipOverride.muted_author_ids(self.a), {self.b.id})
        self.assertEqual(UserRelationshipOverride.muted_author_ids(self.b), set())

    def test_mute_does_not_count_as_block(self):
        UserRelationshipOverride.objects.create(actor=self.a, target=self.b, type=UserRelationshipOverride.Type.MUTE)
        self.assertFalse(UserRelationshipOverride.is_blocked(self.a, self.b))


class BlockUserWebTests(TestCase):
    def setUp(self):
        self.user = make_user('+255700000210', 'User')
        self.other = make_user('+255700000220', 'Other')
        self.client.force_login(self.user)

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(reverse('block_user_web', args=[self.other.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserRelationshipOverride.objects.filter(type=UserRelationshipOverride.Type.BLOCK).exists())

    def test_cannot_block_self(self):
        response = self.client.post(reverse('block_user_web', args=[self.user.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserRelationshipOverride.objects.filter(type=UserRelationshipOverride.Type.BLOCK).exists())

    def test_block_creates_override_row(self):
        response = self.client.post(reverse('block_user_web', args=[self.other.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            UserRelationshipOverride.objects.filter(
                actor=self.user, target=self.other, type=UserRelationshipOverride.Type.BLOCK
            ).exists()
        )

    def test_block_is_idempotent(self):
        self.client.post(reverse('block_user_web', args=[self.other.id]))
        self.client.post(reverse('block_user_web', args=[self.other.id]))
        self.assertEqual(
            UserRelationshipOverride.objects.filter(
                actor=self.user, target=self.other, type=UserRelationshipOverride.Type.BLOCK
            ).count(),
            1,
        )

    def test_block_severs_existing_accepted_connection(self):
        Connection.objects.create(requester=self.user, receiver=self.other, status='accepted')
        self.client.post(reverse('block_user_web', args=[self.other.id]))
        self.assertFalse(
            Connection.objects.filter(requester=self.user, receiver=self.other).exists()
        )

    def test_block_severs_existing_pending_connection_either_direction(self):
        Connection.objects.create(requester=self.other, receiver=self.user, status='pending')
        self.client.post(reverse('block_user_web', args=[self.other.id]))
        self.assertFalse(
            Connection.objects.filter(requester=self.other, receiver=self.user).exists()
        )

    def test_unblock_removes_only_this_users_row(self):
        UserRelationshipOverride.objects.create(actor=self.user, target=self.other, type=UserRelationshipOverride.Type.BLOCK)
        UserRelationshipOverride.objects.create(actor=self.other, target=self.user, type=UserRelationshipOverride.Type.BLOCK)
        self.client.post(reverse('unblock_user_web', args=[self.other.id]))
        self.assertFalse(
            UserRelationshipOverride.objects.filter(actor=self.user, target=self.other, type=UserRelationshipOverride.Type.BLOCK).exists()
        )
        self.assertTrue(
            UserRelationshipOverride.objects.filter(actor=self.other, target=self.user, type=UserRelationshipOverride.Type.BLOCK).exists()
        )
        # the other side's block row is untouched, so the block is still in effect
        self.assertTrue(UserRelationshipOverride.is_blocked(self.user, self.other))


class MuteUserWebTests(TestCase):
    def setUp(self):
        self.user = make_user('+255700000230', 'User')
        self.other = make_user('+255700000240', 'Other')
        self.client.force_login(self.user)

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(reverse('mute_user_web', args=[self.other.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserRelationshipOverride.objects.filter(type=UserRelationshipOverride.Type.MUTE).exists())

    def test_cannot_mute_self(self):
        response = self.client.post(reverse('mute_user_web', args=[self.user.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserRelationshipOverride.objects.filter(type=UserRelationshipOverride.Type.MUTE).exists())

    def test_mute_does_not_touch_connection(self):
        Connection.objects.create(requester=self.user, receiver=self.other, status='accepted')
        self.client.post(reverse('mute_user_web', args=[self.other.id]))
        self.assertTrue(Connection.objects.filter(requester=self.user, receiver=self.other, status='accepted').exists())

    def test_unmute_removes_row(self):
        self.client.post(reverse('mute_user_web', args=[self.other.id]))
        self.client.post(reverse('unmute_user_web', args=[self.other.id]))
        self.assertFalse(
            UserRelationshipOverride.objects.filter(actor=self.user, target=self.other, type=UserRelationshipOverride.Type.MUTE).exists()
        )


class SendConnectionBlockedTests(TestCase):
    """Both the web view (send_connection_web) and the DRF API view
    (SendConnectionView) must refuse a connection request between a blocked
    pair — checked in each app's own test module in normal circumstances,
    but both entry points are exercised here since block enforcement is the
    point of this test class."""

    def setUp(self):
        self.user = make_user('+255700000250', 'User')
        self.other = make_user('+255700000260', 'Other')
        UserRelationshipOverride.objects.create(actor=self.other, target=self.user, type=UserRelationshipOverride.Type.BLOCK)

    def test_web_view_rejects_blocked_connection_request(self):
        self.client.force_login(self.user)
        self.client.post(reverse('send_connection_web', args=[self.other.id]))
        self.assertFalse(Connection.objects.filter(requester=self.user, receiver=self.other).exists())

    def test_api_view_rejects_blocked_connection_request(self):
        # SendConnectionView is JWT-only (DEFAULT_AUTHENTICATION_CLASSES in
        # settings.py) — self.client.force_login is session-based and
        # wouldn't authenticate here at all, so use APIClient.force_authenticate
        # to actually exercise the block check rather than just hitting 401.
        api_client = APIClient()
        api_client.force_authenticate(user=self.user)
        response = api_client.post(reverse('send', args=[self.other.id]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Connection.objects.filter(requester=self.user, receiver=self.other).exists())


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class MessagingBlockedTests(TestCase):
    def setUp(self):
        self.user = make_user('+255700000270', 'User')
        self.other = make_user('+255700000280', 'Other')
        Connection.objects.create(requester=self.user, receiver=self.other, status='accepted')
        self.conv = Conversation.objects.create(
            type=Conversation.ConversationType.DIRECT,
            direct_key=Conversation.direct_key_for(self.user, self.other),
        )
        ConversationMember.objects.create(conversation=self.conv, user=self.user)
        ConversationMember.objects.create(conversation=self.conv, user=self.other)

    def test_cannot_start_new_conversation_once_blocked(self):
        UserRelationshipOverride.objects.create(actor=self.user, target=self.other, type=UserRelationshipOverride.Type.BLOCK)
        # block_user_web severs the Connection, which messages_start relies
        # on — simulate that here directly since this test only cares about
        # messages_start's own gate, not block_user_web's side effects.
        Connection.objects.filter(requester=self.user, receiver=self.other).delete()
        self.client.force_login(self.user)
        response = self.client.post(reverse('messages_start', args=[self.other.id]))
        self.assertRedirects(response, reverse('connections'))
        self.assertFalse(Conversation.objects.exclude(pk=self.conv.pk).exists())

    def test_cannot_send_in_existing_conversation_once_blocked(self):
        UserRelationshipOverride.objects.create(actor=self.user, target=self.other, type=UserRelationshipOverride.Type.BLOCK)
        self.client.force_login(self.user)
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': 'hi'})
        self.assertEqual(response.status_code, 403)

    def test_can_still_send_when_not_blocked(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('messages_send', args=[self.conv.id]), {'body': 'hi'})
        self.assertEqual(response.status_code, 200)
