from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from urbanfoods.models import Order, PaymentAttempt, PaymentReconciliation, Store, User
from urbanfoods.reconciliation_service import ReconciliationService


class ReconciliationServiceTest(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='reconciliation-user')
        store = Store.objects.create(owner=user, name='Reconciliation Store')
        order = Order.objects.create(
            user=user, store=store, phone_number='0712345678',
            subtotal=Decimal('100'), total=Decimal('100'),
            mpesa_checkout_request_id='ws_CO_reconcile',
        )
        self.attempt = PaymentAttempt.objects.create(
            payment_type=PaymentAttempt.PaymentType.ORDER,
            order=order,
            checkout_request_id='ws_CO_reconcile',
            expected_amount=Decimal('100'),
            status=PaymentAttempt.Status.PENDING,
        )

    @patch('urbanfoods.payment_service.ConfirmPaymentService.process_payment_signal')
    @patch('urbanfoods.reconciliation_service.ReconciliationService._provider')
    def test_successful_query_uses_provider_metadata_without_fabricated_receipt(self, provider, confirm):
        provider.return_value.query_stk_status.return_value = {
            'success': True,
            'result_code': 0,
            'result_desc': 'Success',
            'metadata': {'Amount': 100, 'MpesaReceiptNumber': 'QREAL123'},
        }
        result = ReconciliationService.reconcile(self.attempt.id)
        self.assertEqual(result, 'processed')
        confirm.assert_called_once()
        self.assertEqual(confirm.call_args.kwargs['metadata']['MpesaReceiptNumber'], 'QREAL123')
        self.assertNotEqual(confirm.call_args.kwargs['metadata']['MpesaReceiptNumber'], 'RECONCILED')
        self.assertEqual(PaymentReconciliation.objects.get().status, PaymentReconciliation.Status.CONFIRMED)

    @patch('urbanfoods.reconciliation_service.ReconciliationService._provider')
    def test_pending_query_moves_to_manual_review_after_sla(self, provider):
        self.attempt.created_at = timezone.now() - ReconciliationService.MANUAL_REVIEW_AFTER
        self.attempt.save(update_fields=['created_at'])
        provider.return_value.query_stk_status.return_value = {
            'success': True, 'result_code': 4999, 'result_desc': 'Still processing', 'metadata': {},
        }
        self.assertEqual(ReconciliationService.reconcile(self.attempt.id), 'pending')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.MANUAL_REVIEW)

    def test_max_attempts_are_not_scheduled(self):
        self.attempt.reconciliation_attempts = ReconciliationService.MAX_ATTEMPTS
        self.attempt.save(update_fields=['reconciliation_attempts'])
        self.assertIsNone(ReconciliationService.claim_attempt(self.attempt.id))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, PaymentAttempt.Status.MANUAL_REVIEW)
