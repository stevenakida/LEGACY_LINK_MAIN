from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from connections.models import Connection

from .models import Notification
from .services import notify


def make_user(identifier, full_name='Test User'):
    return User.objects.create_user(phone_or_email=identifier, password='Testing2026!', full_name=full_name)


class NotifyServiceTests(TestCase):
    def setUp(self):
        self.recipient = make_user('+255700000500', 'Recipient')
        self.actor = make_user('+255700000501', 'Actor')

    def test_creates_a_notification_row(self):
        conn = Connection.objects.create(requester=self.actor, receiver=self.recipient)
        notification = notify(self.recipient, Notification.Verb.CONNECTION_REQUEST, actor=self.actor, target=conn)
        self.assertEqual(notification.recipient, self.recipient)
        self.assertEqual(notification.actor, self.actor)
        self.assertEqual(notification.verb, Notification.Verb.CONNECTION_REQUEST)
        self.assertEqual(notification.target, conn)
        self.assertIsNone(notification.read_at)

    def test_works_with_no_actor_or_target(self):
        # Matches posts.admin's request=None call sites (existing tests
        # already call approve_posts(None, None, qs)) — actor can be None.
        notification = notify(self.recipient, Notification.Verb.POST_APPROVED, actor=None, target=None)
        self.assertIsNone(notification.actor)
        self.assertIsNone(notification.target)

    def test_does_not_raise_when_push_not_configured(self):
        # No FIREBASE_SERVICE_ACCOUNT_JSON in the test environment —
        # send_push_to_user no-ops silently (see notifications/push.py);
        # notify() must not raise even when push_title/push_body are given.
        notify(
            self.recipient, Notification.Verb.NEW_MESSAGE, actor=self.actor,
            push_title='Actor', push_body='hello',
        )
        self.assertEqual(Notification.objects.count(), 1)


class NotificationsListViewTests(TestCase):
    def setUp(self):
        self.user = make_user('+255700000510', 'User')
        self.other = make_user('+255700000511', 'Other')

    def test_requires_authentication(self):
        response = self.client.get(reverse('notifications_list'))
        self.assertEqual(response.status_code, 302)

    def test_only_shows_own_notifications(self):
        mine = notify(self.user, Notification.Verb.CONNECTION_REQUEST, actor=self.other)
        theirs = notify(self.other, Notification.Verb.CONNECTION_REQUEST, actor=self.user)

        self.client.force_login(self.user)
        response = self.client.get(reverse('notifications_list'))
        self.assertEqual(response.status_code, 200)
        shown = list(response.context['notifications'])
        self.assertIn(mine, shown)
        self.assertNotIn(theirs, shown)

    def test_visiting_marks_unread_notifications_read(self):
        notify(self.user, Notification.Verb.CONNECTION_REQUEST, actor=self.other)
        self.client.force_login(self.user)
        self.client.get(reverse('notifications_list'))
        notification = Notification.objects.get()
        self.assertIsNotNone(notification.read_at)
