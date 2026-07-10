import time
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.models import User
from feedback.models import Feedback


class SubmitFeedbackTimingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('feedback_test@example.com', 'pass1234', full_name='Test User')
        self.client.force_login(self.user)

    @override_settings(FEEDBACK_NOTIFY_EMAIL='team@example.com')
    def test_response_returns_before_slow_email_send(self):
        with patch('config.views.send_mail', side_effect=lambda **kw: time.sleep(5)):
            start = time.monotonic()
            response = self.client.post('/feedback/submit/', {'message': 'hi', 'category': 'bug'})
            elapsed = time.monotonic() - start

        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(Feedback.objects.count(), 1)
