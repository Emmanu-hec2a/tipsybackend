from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from urbanfoods.models import Order, PaymentAttempt, Store, User
from urbanfoods.payment_initiation import InitiatePaymentService, PaymentInitiationConflict


class PaymentInitiationServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='initiation-user')
        self.store = Store.objects.create(owner=self.user, name='Initiation Store')
        self.order = Order.objects.create(
            user=self.user,
            store=self.store,
            phone_number='0712345678',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
        )

    def test_same_key_reuses_attempt_and_enqueues_pending_attempt(self):
        with patch.object(InitiatePaymentService, 'enqueue') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                first, created = InitiatePaymentService.create_or_get_for_order(
                    self.order, '0712345678', 'order-key-1'
                )
                second, created_again = InitiatePaymentService.create_or_get_for_order(
                    self.order, '0712345678', 'order-key-1'
                )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.assertEqual(enqueue.call_count, 2)

    def test_key_cannot_be_reused_for_another_order(self):
        other = Order.objects.create(
            user=self.user,
            store=self.store,
            phone_number='0712345678',
            subtotal=Decimal('50.00'),
            total=Decimal('50.00'),
        )
        with patch.object(InitiatePaymentService, 'enqueue'):
            InitiatePaymentService.create_or_get_for_order(self.order, '0712345678', 'shared-key')
            with self.assertRaises(PaymentInitiationConflict):
                InitiatePaymentService.create_or_get_for_order(other, '0712345678', 'shared-key')

    def test_provider_is_not_called_again_after_checkout_is_persisted(self):
        with patch.object(InitiatePaymentService, 'enqueue'):
            attempt, _ = InitiatePaymentService.create_or_get_for_order(
                self.order, '0712345678', 'provider-key'
            )

        with patch.object(InitiatePaymentService, '_send_to_provider', return_value={
            'success': True,
            'checkout_request_id': 'ws_CO_once',
        }) as provider:
            InitiatePaymentService.initiate_attempt(attempt.id)
            InitiatePaymentService.initiate_attempt(attempt.id)

        self.assertEqual(provider.call_count, 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.PENDING)
        self.assertEqual(attempt.checkout_request_id, 'ws_CO_once')

    def test_initiating_attempt_is_not_sent_again_after_worker_delay(self):
        with patch.object(InitiatePaymentService, 'enqueue'):
            attempt, _ = InitiatePaymentService.create_or_get_for_order(
                self.order, '0712345678', 'stale-initiation-key'
            )
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentAttempt.Status.INITIATING,
            initiation_started_at=timezone.now() - timezone.timedelta(minutes=10),
        )
        with patch.object(InitiatePaymentService, '_send_to_provider') as provider:
            result = InitiatePaymentService.initiate_attempt(attempt.id)
        self.assertTrue(result['in_progress'])
        provider.assert_not_called()
