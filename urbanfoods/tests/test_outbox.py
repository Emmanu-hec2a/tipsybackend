from unittest.mock import patch

from django.test import TestCase

from urbanfoods.models import OutboxEvent, User
from urbanfoods.outbox_service import create_outbox_event
from urbanfoods.tasks import process_outbox_event


class OutboxTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='outbox-user')

    def test_event_is_unique_for_an_aggregate(self):
        first = create_outbox_event(
            'payment.failed', 'payment_attempt', 'attempt-1', {'user_id': self.user.id}
        )
        second = create_outbox_event(
            'payment.failed', 'payment_attempt', 'attempt-1', {'user_id': self.user.id}
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(OutboxEvent.objects.count(), 1)

    def test_failed_event_is_processed_once(self):
        event = create_outbox_event(
            'payment.failed', 'payment_attempt', 'attempt-2',
            {'user_id': self.user.id, 'payment_id': 'payment-2'}
        )
        with patch('urbanfoods.tasks.send_lifecycle_notification_task.run') as notify:
            self.assertEqual(process_outbox_event.run(event.id), 'processed')
            self.assertEqual(process_outbox_event.run(event.id), 'already_processed')
        notify.assert_called_once()
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxEvent.Status.PROCESSED)

    def test_failed_event_is_retryable(self):
        event = create_outbox_event(
            'payment.failed', 'payment_attempt', 'attempt-3',
            {'user_id': self.user.id, 'payment_id': 'payment-3'}
        )
        with patch('urbanfoods.tasks.send_lifecycle_notification_task.run', side_effect=RuntimeError('provider down')):
            self.assertEqual(process_outbox_event.run(event.id), 'retry')
        event.refresh_from_db()
        self.assertEqual(event.status, OutboxEvent.Status.RETRY)
        self.assertIn('provider down', event.last_error)
