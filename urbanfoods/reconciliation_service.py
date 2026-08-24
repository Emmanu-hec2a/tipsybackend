from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import PaymentAttempt, PaymentReconciliation


class ReconciliationService:
    MAX_ATTEMPTS = 8
    FIRST_DELAY = timedelta(minutes=2)
    MANUAL_REVIEW_AFTER = timedelta(minutes=45)

    @classmethod
    def claim_attempt(cls, attempt_id):
        now = timezone.now()
        with transaction.atomic():
            attempt = PaymentAttempt.objects.select_for_update().select_related(
                'order__store', 'subscription_payment__store',
                'shiriki_contribution__session__order__store',
            ).get(pk=attempt_id)
            if attempt.status != PaymentAttempt.Status.PENDING or not attempt.checkout_request_id:
                return None
            if attempt.next_reconciliation_at and attempt.next_reconciliation_at > now:
                return None
            if attempt.reconciliation_started_at and now - attempt.reconciliation_started_at < timedelta(minutes=10):
                return None
            if attempt.reconciliation_attempts >= cls.MAX_ATTEMPTS:
                attempt.status = PaymentAttempt.Status.MANUAL_REVIEW
                attempt.manual_review_reason = 'Maximum reconciliation attempts exceeded.'
                attempt.save(update_fields=['status', 'manual_review_reason'])
                return None
            attempt.reconciliation_started_at = now
            attempt.reconciliation_attempts += 1
            attempt.last_reconciled_at = now
            attempt.next_reconciliation_at = now + timedelta(minutes=2 ** min(attempt.reconciliation_attempts, 5))
            attempt.save(update_fields=[
                'reconciliation_started_at', 'reconciliation_attempts',
                'last_reconciled_at', 'next_reconciliation_at',
            ])
            return attempt

    @staticmethod
    def _provider(attempt):
        from .mpesa_utils import MpesaIntegration
        if attempt.subscription_payment_id:
            from .billing_utils import SubscriptionBilling
            return SubscriptionBilling()
        store = attempt.order.store if attempt.order_id else attempt.shiriki_contribution.session.order.store
        return MpesaIntegration(store=store)

    @classmethod
    def reconcile(cls, attempt_id):
        attempt = cls.claim_attempt(attempt_id)
        if attempt is None:
            return 'skipped'
        try:
            result = cls._provider(attempt).query_stk_status(attempt.checkout_request_id)
            if not result.get('success'):
                cls._record(attempt, PaymentReconciliation.Status.ERROR, result=result, error=result.get('message', 'Query failed'))
                return 'error'
            result_code = result.get('result_code')
            metadata = result.get('metadata') or {}
            if result_code in (None, 4999, '4999'):
                cls._record(attempt, PaymentReconciliation.Status.PENDING, result=result)
                cls._maybe_manual_review(attempt)
                return 'pending'
            cls._record(
                attempt,
                PaymentReconciliation.Status.CONFIRMED if int(result_code) == 0 else PaymentReconciliation.Status.FAILED,
                result=result,
            )
            from .payment_service import ConfirmPaymentService
            ConfirmPaymentService.process_payment_signal(
                checkout_request_id=attempt.checkout_request_id,
                result_code=int(result_code),
                result_desc=result.get('result_desc', ''),
                metadata=metadata,
                source='reconciliation',
            )
            return 'processed'
        except Exception as exc:
            cls._record(attempt, PaymentReconciliation.Status.ERROR, error=str(exc))
            return 'error'

    @classmethod
    def _record(cls, attempt, status, result=None, error=''):
        result = result or {}
        PaymentReconciliation.objects.create(
            payment_attempt=attempt,
            attempt_number=attempt.reconciliation_attempts,
            status=status,
            result_code=result.get('result_code'),
            result_description=result.get('result_desc', ''),
            raw_response=result,
            error_message=error,
        )
        PaymentAttempt.objects.filter(pk=attempt.pk).update(reconciliation_started_at=None)
        from .observability import increment_metric, log_payment_event
        increment_metric('payment_reconciliation_total')
        log_payment_event('payment_reconciliation', attempt, source='reconciliation',
                          reconciliation_status=status, attempt_number=attempt.reconciliation_attempts)

    @classmethod
    def _maybe_manual_review(cls, attempt):
        if timezone.now() - attempt.created_at >= cls.MANUAL_REVIEW_AFTER:
            updated = PaymentAttempt.objects.filter(pk=attempt.pk, status=PaymentAttempt.Status.PENDING).update(
                status=PaymentAttempt.Status.MANUAL_REVIEW,
                manual_review_reason='Provider remained pending beyond reconciliation SLA.',
            )
            if updated and attempt.order_id:
                from .inventory_service import InventoryReservationService
                InventoryReservationService.release_order(attempt.order_id)
            if updated and attempt.shiriki_contribution_id:
                from .models import ShirikiContribution
                ShirikiContribution.objects.filter(
                    pk=attempt.shiriki_contribution_id, status='pending'
                ).update(status='failed')
            from .observability import increment_metric, log_payment_event
            increment_metric('payment_manual_review_total')
            log_payment_event('payment_manual_review', attempt, source='reconciliation')
