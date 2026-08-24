from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from urbanfoods.models import Order, PaymentAttempt, Store, User
from urbanfoods.payment_status import (
    TERMINAL_PAYMENT_STATUSES,
    cache_status,
    get_cached_status,
    next_poll_after,
    retry_after,
)


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'payment-status-tests',
    }
})
class PaymentStatusTest(TestCase):
    def setUp(self):
        cache.clear()
        user = User.objects.create_user(username='status-user')
        store = Store.objects.create(owner=user, name='Status Store')
        order = Order.objects.create(
            user=user, store=store, phone_number='0712345678',
            subtotal=Decimal('10.00'), total=Decimal('10.00'),
        )
        self.attempt = PaymentAttempt.objects.create(
            order=order,
            payment_type=PaymentAttempt.PaymentType.ORDER,
            expected_amount=order.total,
            status=PaymentAttempt.Status.PENDING,
        )

    def test_poll_interval_increases_for_long_pending_attempts(self):
        self.assertEqual(next_poll_after(self.attempt), 5)
        self.attempt.created_at = timezone.now() - timedelta(seconds=60)
        self.assertEqual(next_poll_after(self.attempt), 10)
        self.attempt.created_at = timezone.now() - timedelta(minutes=3)
        self.assertEqual(next_poll_after(self.attempt), 20)

    def test_terminal_attempt_stops_polling_and_gets_cached(self):
        self.attempt.status = PaymentAttempt.Status.CONFIRMED
        self.assertIsNone(next_poll_after(self.attempt))
        self.assertIsNone(retry_after(self.attempt))
        payload = {'payment_id': 'payment-1', 'status': 'confirmed', 'terminal': True}
        cache_status(7, 'payment-1', payload, 'confirmed')
        self.assertEqual(get_cached_status(7, 'payment-1'), payload)
        self.assertTrue(TERMINAL_PAYMENT_STATUSES)

    def test_manual_review_returns_slow_retry_hint(self):
        self.attempt.status = PaymentAttempt.Status.MANUAL_REVIEW
        self.assertEqual(retry_after(self.attempt), 60)
