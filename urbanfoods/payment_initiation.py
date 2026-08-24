import logging
import os
import uuid

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Order, PaymentAttempt, ShirikiContribution, SubscriptionPayment
from .phone_validation import PhoneNumberValidator

logger = logging.getLogger('mpesa_initiation')


class PaymentInitiationConflict(Exception):
    """The supplied idempotency key belongs to another payment target."""


class InitiatePaymentService:
    """Create, reuse, and enqueue exactly one payment attempt per request."""

    ACTIVE_STATUSES = (
        PaymentAttempt.Status.INITIATING,
        PaymentAttempt.Status.PENDING,
    )

    @classmethod
    def create_or_get_for_order(cls, order, phone_number, idempotency_key=None):
        return cls._create_or_get(
            target=order,
            payment_type=PaymentAttempt.PaymentType.ORDER,
            expected_amount=order.total,
            phone_number=phone_number,
            idempotency_key=idempotency_key,
        )

    @classmethod
    def create_or_get_for_contribution(cls, contribution, phone_number, idempotency_key=None):
        return cls._create_or_get(
            target=contribution,
            payment_type=PaymentAttempt.PaymentType.SHIRIKI,
            expected_amount=contribution.amount,
            phone_number=phone_number,
            idempotency_key=idempotency_key,
        )

    @classmethod
    def create_or_get_for_subscription(cls, subscription, phone_number, idempotency_key=None):
        payment_type = (
            PaymentAttempt.PaymentType.COMMISSION
            if subscription.payment_type == 'commission'
            else PaymentAttempt.PaymentType.SUBSCRIPTION
        )
        return cls._create_or_get(
            target=subscription,
            payment_type=payment_type,
            expected_amount=subscription.amount,
            phone_number=phone_number,
            idempotency_key=idempotency_key,
        )

    @classmethod
    def _create_or_get(cls, target, payment_type, expected_amount, phone_number, idempotency_key):
        """
        Create or retrieve a payment attempt with validation.
        
        🛡️ PCI DSS 12.3: Validates phone number format and rate limits before payment initiation
        """
        idempotency_key = idempotency_key or str(uuid.uuid4())
        target_field = cls._target_field(target)
        
        # 🛡️ PCI DSS: Validate phone number before processing
        is_valid, error_msg, metadata = PhoneNumberValidator.validate(
            phone_number=phone_number,
            amount_cents=int(expected_amount * 100) if expected_amount else None,
            check_ownership=False  # Owner check happens in payment service
        )
        
        if not is_valid:
            logger.warning(f"Phone validation failed for payment: {error_msg}")
            raise ValidationError(error_msg)
        
        # Use normalized phone number
        normalized_phone = metadata.get('normalized_phone', phone_number)
        remaining_attempts = metadata.get('attempts_remaining', 0)
        
        logger.info(f"Phone validated successfully. Attempts remaining this hour: {remaining_attempts}")

        with transaction.atomic():
            locked_target = target.__class__.objects.select_for_update().get(pk=target.pk)
            query = PaymentAttempt.objects.select_for_update()

            keyed_attempt = query.filter(idempotency_key=idempotency_key).first()
            created = False
            if keyed_attempt:
                if getattr(keyed_attempt, f'{target_field}_id', None) != locked_target.pk:
                    raise PaymentInitiationConflict('Idempotency key is already used for another payment.')
                attempt = keyed_attempt
            else:
                attempt = query.filter(
                    **{f'{target_field}': locked_target},
                    status__in=cls.ACTIVE_STATUSES,
                ).order_by('-created_at').first()

                if attempt:
                    if attempt.status in cls.ACTIVE_STATUSES and not attempt.checkout_request_id:
                        transaction.on_commit(lambda attempt_id=attempt.id: cls.enqueue(attempt_id))
                    return attempt, False

                attempt = PaymentAttempt.objects.create(
                    payment_type=payment_type,
                    **{target_field: locked_target},
                    idempotency_key=idempotency_key,
                    expected_amount=expected_amount,
                    phone_number=normalized_phone,  # Use normalized phone
                    status=PaymentAttempt.Status.PENDING,
                )
                created = True

            target_key = getattr(locked_target, 'payment_idempotency_key', None)
            if target_key and target_key != idempotency_key:
                raise PaymentInitiationConflict('Payment target is already bound to another request.')
            if hasattr(locked_target, 'payment_idempotency_key') and not target_key:
                locked_target.payment_idempotency_key = idempotency_key
                locked_target.save(update_fields=['payment_idempotency_key'])

            if attempt.status not in cls.ACTIVE_STATUSES:
                return attempt, False

            transaction.on_commit(lambda attempt_id=attempt.id: cls.enqueue(attempt_id))
            return attempt, created

    @staticmethod
    def _target_field(target):
        if isinstance(target, Order):
            return 'order'
        if isinstance(target, ShirikiContribution):
            return 'shiriki_contribution'
        if isinstance(target, SubscriptionPayment):
            return 'subscription_payment'
        raise TypeError(f'Unsupported payment target: {type(target).__name__}')

    @staticmethod
    def enqueue(attempt_id):
        from .tasks import initiate_payment_attempt_task
        initiate_payment_attempt_task.delay(attempt_id)

    @classmethod
    def initiate_attempt(cls, attempt_id):
        """Claim one attempt, call the provider once, and persist the result."""
        with transaction.atomic():
            attempt = PaymentAttempt.objects.select_for_update().select_related(
                'order__store', 'subscription_payment__store', 'shiriki_contribution__session__order__store'
            ).get(pk=attempt_id)
            if attempt.status not in cls.ACTIVE_STATUSES or attempt.checkout_request_id:
                return {'success': True, 'checkout_request_id': attempt.checkout_request_id, 'status': attempt.status}

            now = timezone.now()
            if attempt.status == PaymentAttempt.Status.INITIATING and attempt.initiation_started_at:
                # Never issue a second STK request for the same PaymentAttempt.
                # A worker crash is recovered by reconciliation/manual review,
                # not by guessing whether Safaricom accepted the first call.
                return {'success': True, 'status': attempt.status, 'in_progress': True}

            attempt.status = PaymentAttempt.Status.INITIATING
            attempt.initiation_started_at = now
            attempt.processing_attempts += 1
            attempt.save(update_fields=['status', 'initiation_started_at', 'processing_attempts'])

        target = cls._target(attempt)
        try:
            result = cls._send_to_provider(attempt, target)
        except Exception:
            logger.exception('Payment initiation failed for attempt %s', attempt.id)
            result = {'success': False, 'message': 'Payment provider unavailable'}

        with transaction.atomic():
            attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt_id)
            if attempt.checkout_request_id:
                return {'success': True, 'checkout_request_id': attempt.checkout_request_id, 'status': attempt.status}

            if result.get('success') and result.get('checkout_request_id'):
                attempt.checkout_request_id = result['checkout_request_id']
                attempt.status = PaymentAttempt.Status.PENDING
                attempt.initiation_completed_at = timezone.now()
                attempt.raw_initiation_response = result
                attempt.save(update_fields=[
                    'checkout_request_id', 'status', 'initiation_completed_at', 'raw_initiation_response'
                ])
                cls._persist_legacy_checkout_id(attempt, result['checkout_request_id'])
                from .observability import increment_metric, log_payment_event
                increment_metric('payment_initiation_total')
                log_payment_event('payment_initiated', attempt, source='provider')
                return result

            attempt.status = PaymentAttempt.Status.FAILED
            attempt.failure_code = result.get('error_code', 'initiation_failed')
            attempt.failure_message = result.get('message', 'Payment initiation failed')
            attempt.failed_at = timezone.now()
            attempt.raw_initiation_response = result
            attempt.save(update_fields=[
                'status', 'failure_code', 'failure_message', 'failed_at', 'raw_initiation_response'
            ])
            if attempt.shiriki_contribution_id:
                ShirikiContribution.objects.filter(
                    pk=attempt.shiriki_contribution_id, status='pending'
                ).update(status='failed')
            from .observability import increment_metric, log_payment_event
            increment_metric('payment_initiation_failure_total')
            log_payment_event('payment_initiation_failed', attempt, source='provider',
                              failure_code=attempt.failure_code)
            return result

    @staticmethod
    def _target(attempt):
        if attempt.order_id:
            return attempt.order
        if attempt.subscription_payment_id:
            return attempt.subscription_payment
        return attempt.shiriki_contribution

    @staticmethod
    def _send_to_provider(attempt, target):
        if attempt.subscription_payment_id:
            from .billing_utils import SubscriptionBilling
            billing = SubscriptionBilling()
            return billing.charge_subscription(target.store, custom_phone=attempt.phone_number, amount=target.amount)

        from .mpesa_utils import MpesaIntegration
        store = target.store if isinstance(target, Order) else target.session.order.store
        mpesa = MpesaIntegration(store=store)
        phone = mpesa.format_phone_number(attempt.phone_number)
        reference = target.order_number if isinstance(target, Order) else f'POT-{target.id}'
        description = f'Order {reference}' if isinstance(target, Order) else f'Shiriki {target.session.invite_code}'
        amount = int(attempt.expected_amount)
        if str(os.environ.get('MPESA_PRODUCTION', 'false')).lower() != 'true':
            amount = 1
        return mpesa.initiate_stk_push(
            phone_number=phone,
            amount=amount,
            account_reference=reference,
            transaction_desc=description,
        )

    @staticmethod
    def _persist_legacy_checkout_id(attempt, checkout_request_id):
        if attempt.order_id:
            Order.objects.filter(pk=attempt.order_id).update(
                mpesa_checkout_request_id=checkout_request_id,
                payment_status='pending',
            )
        elif attempt.shiriki_contribution_id:
            ShirikiContribution.objects.filter(pk=attempt.shiriki_contribution_id).update(
                checkout_request_id=checkout_request_id,
            )
        elif attempt.subscription_payment_id:
            SubscriptionPayment.objects.filter(pk=attempt.subscription_payment_id).update(
                checkout_request_id=checkout_request_id,
            )
