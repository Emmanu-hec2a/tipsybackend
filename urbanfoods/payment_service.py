import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import (
    CartItem,
    MpesaTransaction,
    Order,
    OrderStatusHistory,
    PaymentAttempt,
    ShirikiContribution,
    ShirikiSession,
    SubscriptionPayment,
)
from .ledger_service import FinancialLedgerService
from .models import LoyaltyLedger, WalletLedger
from .outbox_service import create_outbox_event

logger = logging.getLogger('mpesa_reconciliation')


class ConfirmPaymentService:
    """Single atomic state-transition authority for M-Pesa payment signals."""

    TERMINAL_ATTEMPT_STATUSES = {
        PaymentAttempt.Status.CONFIRMED,
        PaymentAttempt.Status.FAILED,
        PaymentAttempt.Status.EXPIRED,
        PaymentAttempt.Status.MANUAL_REVIEW,
        PaymentAttempt.Status.OVERPAID,
        PaymentAttempt.Status.REFUND_REQUIRED,
    }

    @classmethod
    def process_payment_signal(cls, checkout_request_id, result_code, result_desc, metadata, source='callback', client_ip=None):
        """Process one provider signal inside one locked database transaction."""
        if not checkout_request_id:
            return False
        try:
            result_code = int(result_code)
        except (TypeError, ValueError):
            result_code = -1

        metadata = metadata or {}
        receipt = metadata.get('MpesaReceiptNumber')
        amount = cls._decimal_or_none(metadata.get('Amount'))
        post_commit_order_id = None
        post_commit_failure_user_id = None

        try:
            with transaction.atomic():
                attempt, target = cls._lock_or_create_attempt(checkout_request_id, metadata)
                if attempt is None:
                    from .observability import increment_metric, log_payment_event
                    increment_metric('payment_unmatched_total')
                    log_payment_event('payment_unmatched', source=source,
                                      checkout_request_id=checkout_request_id[-6:])
                    logger.warning('Unmatched payment signal: %s (client_ip=%s)', checkout_request_id, client_ip)
                    return False

                previous_status = attempt.status
                cls._record_signal(attempt, result_code, result_desc, metadata, amount, receipt)
                if attempt.status in cls.TERMINAL_ATTEMPT_STATUSES:
                    from .observability import record_payment_transition
                    record_payment_transition(attempt, previous_status, source)
                    return True

                if result_code != 0:
                    post_commit_failure_user_id = cls._fail_target(attempt, target, result_desc)
                    result = True
                else:
                    expected_amount = cls._expected_amount(target)
                    if not cls._amount_matches(expected_amount, amount):
                        cls._mark_amount_mismatch(attempt, expected_amount, amount)
                        from .observability import increment_metric
                        increment_metric('payment_amount_mismatch_total')
                        result = True
                    elif isinstance(target, ShirikiContribution):
                        post_commit_order_id = cls._confirm_shiriki(attempt, target, receipt, amount)
                        result = True
                    elif isinstance(target, Order):
                        cls._confirm_order(attempt, target, receipt)
                        post_commit_order_id = target.id
                        result = True
                    else:
                        cls._confirm_subscription(attempt, target, receipt)
                        result = True

                from .observability import record_payment_transition
                record_payment_transition(attempt, previous_status, source)

                if post_commit_order_id:
                    transaction.on_commit(
                        lambda order_id=post_commit_order_id: _enqueue_order_payment_tasks(order_id)
                    )
                if post_commit_failure_user_id:
                    transaction.on_commit(
                        lambda user_id=post_commit_failure_user_id: _enqueue_payment_failure(user_id)
                    )
                return result
        except Exception:
            logger.exception('Atomic payment confirmation failed for %s', checkout_request_id)
            return False

    @classmethod
    def _lock_or_create_attempt(cls, checkout_request_id, metadata):
        attempt = PaymentAttempt.objects.select_for_update().filter(
            provider=PaymentAttempt.Provider.MPESA,
            checkout_request_id=checkout_request_id,
        ).first()
        if attempt:
            return attempt, cls._lock_attempt_target(attempt)

        order = Order.objects.select_for_update().filter(
            mpesa_checkout_request_id=checkout_request_id
        ).first()
        if order:
            target = order
            payment_type = PaymentAttempt.PaymentType.ORDER
            expected_amount = order.total
        else:
            contribution = ShirikiContribution.objects.select_for_update().filter(
                checkout_request_id=checkout_request_id
            ).first()
            if contribution:
                ShirikiSession.objects.select_for_update().get(pk=contribution.session_id)
                target = contribution
                payment_type = PaymentAttempt.PaymentType.SHIRIKI
                expected_amount = contribution.amount
            else:
                subscription = SubscriptionPayment.objects.select_for_update().filter(
                    checkout_request_id=checkout_request_id
                ).first()
                if not subscription:
                    return None, None
                target = subscription
                payment_type = (
                    PaymentAttempt.PaymentType.COMMISSION
                    if subscription.payment_type == 'commission'
                    else PaymentAttempt.PaymentType.SUBSCRIPTION
                )
                expected_amount = subscription.amount

        attempt, created = PaymentAttempt.objects.select_for_update().get_or_create(
            provider=PaymentAttempt.Provider.MPESA,
            checkout_request_id=checkout_request_id,
            defaults={
                'payment_type': payment_type,
                'order': target if isinstance(target, Order) else None,
                'subscription_payment': target if isinstance(target, SubscriptionPayment) else None,
                'shiriki_contribution': target if isinstance(target, ShirikiContribution) else None,
                'expected_amount': expected_amount,
                'phone_number': str(metadata.get('PhoneNumber') or ''),
                'status': PaymentAttempt.Status.PENDING,
            },
        )
        if not created:
            target = cls._lock_attempt_target(attempt)
        return attempt, target

    @staticmethod
    def _lock_attempt_target(attempt):
        if attempt.order_id:
            return Order.objects.select_for_update().get(pk=attempt.order_id)
        if attempt.subscription_payment_id:
            return SubscriptionPayment.objects.select_for_update().get(pk=attempt.subscription_payment_id)
        if attempt.shiriki_contribution_id:
            contribution = ShirikiContribution.objects.select_for_update().get(pk=attempt.shiriki_contribution_id)
            ShirikiSession.objects.select_for_update().get(pk=contribution.session_id)
            return contribution
        raise ValueError(f'Payment attempt {attempt.pk} has no target')

    @classmethod
    def _record_signal(cls, attempt, result_code, result_desc, metadata, amount, receipt):
        attempt.provider_result_code = result_code
        attempt.provider_result_description = result_desc or ''
        attempt.raw_callback_payload = metadata
        attempt.received_amount = amount
        if receipt:
            attempt.provider_receipt = str(receipt)
        if metadata.get('PhoneNumber'):
            attempt.phone_number = str(metadata['PhoneNumber'])
        attempt.processing_attempts = F('processing_attempts') + 1
        attempt.save(update_fields=[
            'provider_result_code', 'provider_result_description',
            'raw_callback_payload', 'received_amount', 'provider_receipt',
            'phone_number', 'processing_attempts',
        ])
        attempt.refresh_from_db(fields=['processing_attempts', 'status'])

        if attempt.order_id:
            MpesaTransaction.objects.update_or_create(
                checkout_request_id=attempt.checkout_request_id,
                defaults={
                    'order_id': attempt.order_id,
                    'mpesa_receipt_number': receipt,
                    'phone_number': attempt.phone_number,
                    'amount': amount or Decimal('0.00'),
                    'result_code': result_code,
                    'result_desc': result_desc or '',
                    'raw_callback': metadata,
                },
            )

    @staticmethod
    def _decimal_or_none(value):
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value)).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _expected_amount(target):
        return target.amount if isinstance(target, (ShirikiContribution, SubscriptionPayment)) else target.total

    @staticmethod
    def _amount_matches(expected, received):
        if received is None:
            return False
        is_production = str(__import__('os').environ.get('MPESA_PRODUCTION', 'false')).lower() == 'true'
        return received == expected or (not is_production and received == Decimal('1.00'))

    @staticmethod
    def _mark_amount_mismatch(attempt, expected, received):
        attempt.status = PaymentAttempt.Status.MANUAL_REVIEW
        attempt.failure_code = 'amount_mismatch'
        attempt.failure_message = f'Received {received}; expected {expected}'
        attempt.failed_at = timezone.now()
        attempt.save(update_fields=['status', 'failure_code', 'failure_message', 'failed_at'])
        if attempt.order_id:
            from .inventory_service import InventoryReservationService
            InventoryReservationService.release_order(attempt.order_id)
        logger.error('Payment amount mismatch checkout=%s expected=%s received=%s', attempt.checkout_request_id, expected, received)

    @classmethod
    def _confirm_order(cls, attempt, order, receipt):
        now = timezone.now()
        if order.payment_status == 'paid':
            attempt.status = PaymentAttempt.Status.CONFIRMED
            attempt.confirmed_at = attempt.confirmed_at or now
            attempt.save(update_fields=['status', 'confirmed_at'])
            return

        order.payment_status = 'paid'
        order.status = 'pending'
        order.payment_completed_at = now
        order.mpesa_receipt_number = receipt
        order.save(update_fields=['payment_status', 'status', 'payment_completed_at', 'mpesa_receipt_number', 'updated_at'])

        for item in order.items.select_related('food_item'):
            item.food_item.times_ordered = F('times_ordered') + item.quantity
            item.food_item.save(update_fields=['times_ordered'])
        CartItem.objects.filter(cart__user=order.user).delete()
        FinancialLedgerService.loyalty_entry(
            order.user_id,
            LoyaltyLedger.EntryType.CREDIT,
            int(order.total),
            attempt.public_payment_id,
            f'payment-loyalty-{attempt.public_payment_id}',
        )
        OrderStatusHistory.objects.create(order=order, status='pending', notes=f'Paid via M-Pesa ({receipt})')

        attempt.status = PaymentAttempt.Status.CONFIRMED
        attempt.confirmed_at = now
        attempt.save(update_fields=['status', 'confirmed_at'])
        create_outbox_event(
            'order.confirmed', 'order', order.id,
            {'order_id': order.id, 'payment_id': str(attempt.public_payment_id)}, attempt
        )

    @classmethod
    def _confirm_shiriki(cls, attempt, contribution, receipt, amount):
        if contribution.status == 'confirmed':
            attempt.status = PaymentAttempt.Status.CONFIRMED
            attempt.confirmed_at = attempt.confirmed_at or timezone.now()
            attempt.save(update_fields=['status', 'confirmed_at'])
            return None

        session = ShirikiSession.objects.select_for_update().get(pk=contribution.session_id)
        order = Order.objects.select_for_update().get(pk=session.order_id)
        confirmed_applied = session.contributions.filter(status='confirmed').exclude(
            pk=contribution.pk
        ).aggregate(Sum('amount_applied_to_pot'))['amount_applied_to_pot__sum'] or Decimal('0')
        remaining_capacity = max(order.total - confirmed_applied, Decimal('0'))
        applied = min(amount, remaining_capacity)
        overflow = amount - applied

        contribution.amount_applied_to_pot = applied
        contribution.wallet_credit_amount = overflow
        contribution.status = 'confirmed'
        contribution.paid_at = timezone.now()
        contribution.save(update_fields=['amount_applied_to_pot', 'wallet_credit_amount', 'status', 'paid_at'])
        if overflow:
            FinancialLedgerService.wallet_entry(
                contribution.user_id,
                WalletLedger.EntryType.CREDIT,
                overflow,
                'shiriki_overflow',
                contribution.id,
                f'shiriki-wallet-{contribution.id}',
            )
        FinancialLedgerService.loyalty_entry(
            contribution.user_id,
            LoyaltyLedger.EntryType.CREDIT,
            int(amount),
            attempt.public_payment_id,
            f'payment-loyalty-{attempt.public_payment_id}',
        )

        total_in_pot = session.contributions.filter(status='confirmed').aggregate(
            Sum('amount_applied_to_pot')
        )['amount_applied_to_pot__sum'] or Decimal('0')
        order_id = None
        if total_in_pot >= (order.total - Decimal('0.01')):
            session.status = 'completed'
            session.save(update_fields=['status'])
            cls._confirm_order(attempt, order, receipt)
            order_id = order.id

        attempt.status = PaymentAttempt.Status.CONFIRMED
        attempt.confirmed_at = timezone.now()
        attempt.save(update_fields=['status', 'confirmed_at'])
        create_outbox_event(
            'shiriki.progress', 'shiriki_contribution', contribution.id,
            {
                'session_id': session.id,
                'contributor_id': contribution.user_id,
                'amount': str(amount),
                'order_id': session.order_id,
                'order_number': order.order_number,
            }, attempt
        )
        return order_id

    @staticmethod
    def _confirm_subscription(attempt, subscription, receipt):
        now = timezone.now()
        if subscription.status != 'success':
            subscription.status = 'success'
            subscription.mpesa_receipt = receipt
            subscription.save(update_fields=['status', 'mpesa_receipt'])
            store = subscription.store
            store.billing_status = 'active'
            store.subscription_expires = timezone.localdate() + timezone.timedelta(days=30)
            store.last_payment_date = timezone.localdate()
            store.save(update_fields=['billing_status', 'subscription_expires', 'last_payment_date'])
        attempt.status = PaymentAttempt.Status.CONFIRMED
        attempt.confirmed_at = attempt.confirmed_at or now
        attempt.save(update_fields=['status', 'confirmed_at'])
        create_outbox_event(
            'subscription.confirmed', 'subscription_payment', subscription.id,
            {'subscription_payment_id': subscription.id, 'payment_id': str(attempt.public_payment_id)}, attempt
        )

    @staticmethod
    def _fail_target(attempt, target, reason):
        attempt.status = PaymentAttempt.Status.FAILED
        attempt.failure_code = 'provider_failure'
        attempt.failure_message = reason or 'M-Pesa payment failed'
        attempt.failed_at = timezone.now()
        attempt.save(update_fields=['status', 'failure_code', 'failure_message', 'failed_at'])
        if isinstance(target, ShirikiContribution):
            target.status = 'failed'
            target.save(update_fields=['status'])
            create_outbox_event(
                'payment.failed', 'payment_attempt', attempt.id,
                {'user_id': target.user_id, 'payment_id': str(attempt.public_payment_id), 'reason': reason}, attempt
            )
            return target.user_id
        if isinstance(target, Order):
            from .inventory_service import InventoryReservationService
            InventoryReservationService.release_order(target.id)
            target.payment_status = 'failed'
            target.payment_failure_reason = reason
            target.status = 'cancelled'
            target.save(update_fields=['payment_status', 'payment_failure_reason', 'status', 'updated_at'])
            OrderStatusHistory.objects.create(order=target, status='cancelled', notes=f'Payment failed: {reason}')
            create_outbox_event(
                'payment.failed', 'payment_attempt', attempt.id,
                {
                    'user_id': target.user_id, 'payment_id': str(attempt.public_payment_id),
                    'order_id': target.id, 'order_number': target.order_number, 'reason': reason,
                }, attempt
            )
            return target.user_id
        owner_id = target.store.owner_id
        create_outbox_event(
            'payment.failed', 'payment_attempt', attempt.id,
            {'user_id': owner_id, 'payment_id': str(attempt.public_payment_id), 'reason': reason}, attempt
        )
        return owner_id


def _enqueue_order_payment_tasks(order_id):
    from .tasks import dispatch_outbox_events
    dispatch_outbox_events.delay()


def _enqueue_payment_failure(user_id):
    from .tasks import dispatch_outbox_events
    dispatch_outbox_events.delay()


def _enqueue_shiriki_progress(session_id, contributor_id, amount):
    from .tasks import notify_shiriki_progress_task
    notify_shiriki_progress_task.delay(session_id, contributor_id, float(amount))
