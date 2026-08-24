from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from urbanfoods.models import Order, PaymentAttempt, Store, SubscriptionPayment, User
from urbanfoods.payment_service import ConfirmPaymentService


class ConfirmPaymentServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='payment-service-user')
        self.store = Store.objects.create(owner=self.user, name='Payment Service Store')
        self.order = Order.objects.create(
            user=self.user,
            store=self.store,
            phone_number='0712345678',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            mpesa_checkout_request_id='ws_CO_order_service',
        )

    @staticmethod
    def _metadata(amount, receipt='QABC123'):
        return {
            'Amount': amount,
            'MpesaReceiptNumber': receipt,
            'PhoneNumber': '254712345678',
        }

    def test_successful_signal_confirms_order_and_creates_attempt(self):
        with patch('urbanfoods.payment_service._enqueue_order_payment_tasks') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                result = ConfirmPaymentService.process_payment_signal(
                    checkout_request_id='ws_CO_order_service',
                    result_code=0,
                    result_desc='Success',
                    metadata=self._metadata(1),
                    source='test',
                )

        self.assertTrue(result)
        self.order.refresh_from_db()
        attempt = PaymentAttempt.objects.get(checkout_request_id='ws_CO_order_service')
        self.assertEqual(self.order.payment_status, 'paid')
        self.assertEqual(attempt.status, PaymentAttempt.Status.CONFIRMED)
        enqueue.assert_called_once_with(self.order.id)

    def test_duplicate_success_signal_does_not_award_loyalty_twice(self):
        with patch('urbanfoods.payment_service._enqueue_order_payment_tasks'):
            ConfirmPaymentService.process_payment_signal(
                checkout_request_id='ws_CO_order_service',
                result_code=0,
                result_desc='Success',
                metadata=self._metadata(1),
                source='test',
            )
            self.user.refresh_from_db()
            points_after_first = self.user.loyalty_points

            result = ConfirmPaymentService.process_payment_signal(
                checkout_request_id='ws_CO_order_service',
                result_code=0,
                result_desc='Success',
                metadata=self._metadata(1),
                source='duplicate_test',
            )

        self.user.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.user.loyalty_points, points_after_first)
        self.assertEqual(PaymentAttempt.objects.count(), 1)

    def test_amount_mismatch_does_not_confirm_order(self):
        result = ConfirmPaymentService.process_payment_signal(
            checkout_request_id='ws_CO_order_service',
            result_code=0,
            result_desc='Success',
            metadata=self._metadata(99),
            source='test',
        )

        self.assertTrue(result)
        self.order.refresh_from_db()
        attempt = PaymentAttempt.objects.get(checkout_request_id='ws_CO_order_service')
        self.assertEqual(self.order.payment_status, 'pending')
        self.assertEqual(attempt.status, PaymentAttempt.Status.MANUAL_REVIEW)
        self.assertEqual(attempt.failure_code, 'amount_mismatch')

    def test_failed_signal_is_terminal_and_duplicate_is_acknowledged(self):
        metadata = self._metadata(1, receipt=None)
        first = ConfirmPaymentService.process_payment_signal(
            checkout_request_id='ws_CO_order_service',
            result_code=1032,
            result_desc='Request cancelled by user',
            metadata=metadata,
            source='test',
        )
        second = ConfirmPaymentService.process_payment_signal(
            checkout_request_id='ws_CO_order_service',
            result_code=1032,
            result_desc='Request cancelled by user',
            metadata=metadata,
            source='duplicate_test',
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'failed')
        self.assertEqual(
            PaymentAttempt.objects.get(checkout_request_id='ws_CO_order_service').status,
            PaymentAttempt.Status.FAILED,
        )

    def test_subscription_signal_uses_subscription_target(self):
        subscription = SubscriptionPayment.objects.create(
            store=self.store,
            amount=Decimal('3000.00'),
            checkout_request_id='ws_CO_subscription_service',
        )

        result = ConfirmPaymentService.process_payment_signal(
            checkout_request_id=subscription.checkout_request_id,
            result_code=0,
            result_desc='Success',
            metadata=self._metadata(3000, receipt='QSUB123'),
            source='test',
        )

        subscription.refresh_from_db()
        attempt = PaymentAttempt.objects.get(subscription_payment=subscription)
        self.assertTrue(result)
        self.assertEqual(subscription.status, 'success')
        self.assertEqual(attempt.status, PaymentAttempt.Status.CONFIRMED)
