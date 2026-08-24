import os
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from urbanfoods.models import Order, PaymentAttempt, Store, User
from urbanfoods.payment_backpressure import PaymentBackpressure


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'payment-backpressure-tests',
    }
})
class PaymentBackpressureTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='backpressure-user')
        self.store = Store.objects.create(owner=self.user, name='Backpressure Store')
        self.order = Order.objects.create(
            user=self.user, store=self.store, phone_number='0712345678',
            subtotal=Decimal('10.00'), total=Decimal('10.00'),
        )
        self.attempt = PaymentAttempt.objects.create(
            order=self.order,
            payment_type=PaymentAttempt.PaymentType.ORDER,
            expected_amount=self.order.total,
            status=PaymentAttempt.Status.PENDING,
        )

    def tearDown(self):
        cache.clear()

    @patch.dict(os.environ, {'MPESA_INITIATION_RATE_PER_MINUTE': '1'})
    def test_provider_rate_admission_is_bounded(self):
        self.assertEqual(PaymentBackpressure.admit_provider_call(self.attempt.id), (True, None))
        self.assertEqual(
            PaymentBackpressure.admit_provider_call(self.attempt.id),
            (False, 'provider_rate_limited'),
        )

    @patch.dict(os.environ, {'MPESA_CIRCUIT_FAILURE_THRESHOLD': '2', 'MPESA_CIRCUIT_OPEN_SECONDS': '60'})
    def test_repeated_provider_failures_open_circuit(self):
        failure = {'success': False, 'message': 'Payment provider unavailable'}
        PaymentBackpressure.record_provider_result(failure)
        self.assertFalse(PaymentBackpressure.circuit_open())
        PaymentBackpressure.record_provider_result(failure)
        self.assertTrue(PaymentBackpressure.circuit_open())

    def test_success_resets_provider_failure_counter(self):
        PaymentBackpressure.record_provider_result(
            {'success': False, 'message': 'Provider timeout'}
        )
        PaymentBackpressure.record_provider_result({'success': True})
        self.assertFalse(PaymentBackpressure.circuit_open())

    def test_retry_delay_is_exponential_and_jittered_with_cap(self):
        with patch('urbanfoods.payment_backpressure.random.uniform', return_value=0):
            self.assertEqual(PaymentBackpressure.retry_delay(0), 5)
            self.assertEqual(PaymentBackpressure.retry_delay(4), 80)
            self.assertEqual(PaymentBackpressure.retry_delay(10), 120)

    @override_settings(CELERY_TASK_ROUTES={
        'urbanfoods.tasks.initiate_payment_attempt_task': {'queue': 'payment_initiation'},
        'urbanfoods.tasks.reconcile_payment_attempt_task': {'queue': 'payment_reconciliation'},
        'urbanfoods.tasks.process_outbox_event': {'queue': 'payment_notifications'},
    })
    def test_queue_routes_are_separated(self):
        from django.conf import settings
        self.assertEqual(settings.CELERY_TASK_ROUTES['urbanfoods.tasks.initiate_payment_attempt_task']['queue'], 'payment_initiation')
        self.assertEqual(settings.CELERY_TASK_ROUTES['urbanfoods.tasks.reconcile_payment_attempt_task']['queue'], 'payment_reconciliation')
        self.assertEqual(settings.CELERY_TASK_ROUTES['urbanfoods.tasks.process_outbox_event']['queue'], 'payment_notifications')
