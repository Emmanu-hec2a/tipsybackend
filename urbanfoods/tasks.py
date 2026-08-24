from celery import shared_task
from .utils import send_fcm_notification, send_telegram_notification, send_telegram_message
from .models import (
    User, MarketingBlast, Store, Cart, ShirikiSession, 
    ShirikiContribution, RiderEarning, RiderWeeklyStat, Order, SubscriptionPayment, PaymentAttempt, OutboxEvent
)
from .mpesa_utils import MpesaIntegration
import os
import json
import logging
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from datetime import timedelta
from django.test import RequestFactory


logger = logging.getLogger(__name__)


@shared_task
def reconcile_financial_ledgers():
    """Report materialized-balance drift without silently changing customer money."""
    from django.db.models import Case, DecimalField, F, IntegerField, Q, Sum, Value, When
    from .models import LoyaltyLedger, WalletLedger

    mismatches = []
    for user in User.objects.only('id', 'wallet_balance', 'loyalty_points').iterator():
        wallet_total = WalletLedger.objects.filter(user_id=user.id).aggregate(
            credits=Sum('amount', filter=Q(entry_type__in=['credit', 'refund'])),
            debits=Sum('amount', filter=Q(entry_type__in=['debit', 'reversal'])),
        )
        expected_wallet = (wallet_total['credits'] or 0) - (wallet_total['debits'] or 0)
        loyalty_total = LoyaltyLedger.objects.filter(user_id=user.id).aggregate(
            credits=Sum('points', filter=Q(entry_type__in=['credit', 'refund'])),
            debits=Sum('points', filter=Q(entry_type__in=['debit', 'reversal'])),
        )
        expected_points = (loyalty_total['credits'] or 0) - (loyalty_total['debits'] or 0)
        if user.wallet_balance != expected_wallet or user.loyalty_points != expected_points:
            mismatches.append({
                'user_id': user.id,
                'wallet_balance': str(user.wallet_balance),
                'wallet_ledger_balance': str(expected_wallet),
                'loyalty_points': user.loyalty_points,
                'loyalty_ledger_points': expected_points,
            })
    logger.error('Financial ledger reconciliation found %s mismatches', len(mismatches)) if mismatches else logger.info('Financial ledgers reconciled cleanly')
    return {'mismatch_count': len(mismatches), 'mismatches': mismatches}


@shared_task
def dispatch_outbox_events(limit=100):
    """Publish pending and recoverable outbox records to event consumers."""
    from django.db.models import Q
    cutoff = timezone.now()
    stale_processing = cutoff - timedelta(minutes=10)
    OutboxEvent.objects.filter(
        status=OutboxEvent.Status.PROCESSING,
        updated_at__lt=stale_processing,
    ).update(status=OutboxEvent.Status.RETRY, next_attempt_at=cutoff)
    event_ids = list(OutboxEvent.objects.filter(
        status__in=[OutboxEvent.Status.PENDING, OutboxEvent.Status.RETRY],
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=cutoff)).order_by('created_at').values_list('id', flat=True)[:limit])
    for event_id in event_ids:
        process_outbox_event.delay(event_id)
    return len(event_ids)


@shared_task
def process_outbox_event(event_id):
    from .outbox_service import claim_outbox_event, mark_outbox_processed, mark_outbox_retry
    event = claim_outbox_event(event_id)
    if event is None:
        return 'already_processed'
    try:
        if event.event_type == 'order.confirmed':
            order = Order.objects.select_related('store', 'user').get(pk=event.payload['order_id'])
            from .utils import notify_new_order, update_weekly_revenue_share
            notify_new_order(order)
            update_weekly_revenue_share(order)
        elif event.event_type == 'shiriki.progress':
            notify_shiriki_progress_task.run(
                event.payload['session_id'], event.payload['contributor_id'], event.payload['amount']
            )
        elif event.event_type == 'payment.failed':
            send_lifecycle_notification_task.run(
                event.payload['user_id'], 'Payment Problem',
                'Your M-Pesa payment could not be completed.',
                {'type': 'stk_failed', 'payment_id': event.payload['payment_id']},
            )
        elif event.event_type == 'subscription.confirmed':
            pass
        mark_outbox_processed(event.id)
        return 'processed'
    except Exception as exc:
        logger.exception('Outbox event %s failed', event_id)
        mark_outbox_retry(event.id, exc)
        return 'retry'

@shared_task(rate_limit='5000/m')
def send_single_marketing_notification(user_id, title, body, data=None):
    try:
        user = User.objects.get(id=user_id)
        if user.fcm_token:
            send_fcm_notification(user, title, body, data)
    except User.DoesNotExist:
        logger.error(f"User with id {user_id} does not exist")
    except Exception as e:
        logger.error(f"Error in send_single_marketing_notification: {e}")

@shared_task(rate_limit='5000/m')
def send_lifecycle_notification_task(user_id, title, body, data=None):
    try:
        user = User.objects.get(id=user_id)
        send_fcm_notification(user, title, body, data)
    except User.DoesNotExist:
        logger.error(f"User with id {user_id} does not exist")
    except Exception as e:
        logger.error(f"Error in send_lifecycle_notification_task: {e}")

@shared_task
def send_marketing_blast_task(store_id, blast_id):
    try:
        store = Store.objects.get(id=store_id)
        blast = MarketingBlast.objects.get(id=blast_id)
        
        customer_ids = Order.objects.filter(
            store=store, 
            user__fcm_token__isnull=False
        ).exclude(user__fcm_token='').values_list('user_id', flat=True).distinct()
        
        customers_with_tokens = User.objects.filter(id__in=customer_ids)
        
        count = 0
        for customer in customers_with_tokens:
            send_single_marketing_notification.delay(
                customer.id, 
                store.name, 
                blast.message,
                {'store_id': str(store.id), 'type': 'marketing_blast'}
            )
            count += 1
            
        blast.target_count = count
        blast.save()
        
        logger.info(f"Queued {count} notifications for blast {blast_id} from store {store_id}")
        
    except Exception as e:
        logger.error(f"Error in send_marketing_blast_task: {e}")

@shared_task
def send_telegram_notification_task(chat_id, message, bot_type='merchant'):
    try:
        return send_telegram_notification(chat_id, message, bot_type)
    except Exception as e:
        logger.error(f"Error in send_telegram_notification_task: {e}")
        return False

@shared_task
def check_abandoned_carts():
    try:
        threshold = timezone.now() - timedelta(hours=2)
        abandoned_carts = Cart.objects.filter(
            updated_at__lte=threshold,
            items__isnull=False,
            user__fcm_token__isnull=False
        ).exclude(
            last_reminder_sent_at__date=timezone.now().date()
        ).select_related('user').distinct().iterator(chunk_size=500)

        count = 0
        for cart in abandoned_carts:
            send_lifecycle_notification_task.delay(
                cart.user.id,
                "Items waiting for you! 🥂",
                "You left some items in your cart. Grab them before they're gone!",
                {'type': 'cart_reminder'}
            )
            cart.last_reminder_sent_at = timezone.now()
            cart.save(update_fields=['last_reminder_sent_at'])
            count += 1
            
    except Exception as e:
        logger.error(f"Error in check_abandoned_carts: {e}")

@shared_task
def check_expired_shiriki_sessions():
    now = timezone.now()
    expired_sessions = ShirikiSession.objects.filter(status='active', expires_at__lt=now)
    count = 0
    for session in expired_sessions:
        try:
            with transaction.atomic():
                session.status = 'expired'
                session.save()
                contributions = session.contributions.filter(status='confirmed')
                for contrib in contributions:
                    user = contrib.user
                    user.wallet_balance += contrib.amount
                    user.save()
                    contrib.status = 'refunded'
                    contrib.save()
                session.order.status = 'cancelled'
                session.order.save()
                count += 1
        except Exception as e:
            logger.error(f"Failed to process expiry for Shiriki Session {session.invite_code}: {e}")
    return f"Processed {count} sessions"

@shared_task
def calculate_rider_weekly_stats(force_date=None):
    today = force_date or timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    week_end = today
    earnings = RiderEarning.objects.filter(
        created_at__date__gte=week_start,
        created_at__date__lte=week_end
    ).select_related('rider', 'order__store')
    
    rider_store_map = {}
    for earn in earnings:
        key = (earn.rider.id, earn.order.store.id)
        if key not in rider_store_map:
            rider_store_map[key] = {'base': 0, 'tips': 0, 'rider': earn.rider, 'store': earn.order.store}
        rider_store_map[key]['base'] += earn.base_fare
        rider_store_map[key]['tips'] += earn.tip
        
    count = 0
    for key, data in rider_store_map.items():
        total = data['base'] + data['tips']
        if total > 0:
            stat, created = RiderWeeklyStat.objects.get_or_create(
                rider=data['rider'], store=data['store'], week_start=week_start,
                defaults={'week_end': week_end, 'total_base_fare': data['base'], 'total_tips': data['tips'], 'total_amount': total, 'status': 'unpaid'}
            )
            if not created:
                stat.total_base_fare = data['base']
                stat.total_tips = data['tips']
                stat.total_amount = total
                stat.save()
            count += 1
    return f"Generated {count} stats"

@shared_task(bind=True, max_retries=3)
def retry_unmatched_callback_task(self, callback_data, attempt=1):
    """
    Retries matching an M-Pesa callback to an Order/ShirikiContribution.
    """
    from .payment_service import ConfirmPaymentService
    
    stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
    checkout_request_id = stk_callback.get('CheckoutRequestID')

    if not checkout_request_id: return "No CheckoutRequestID"

    # Extract metadata
    raw_metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
    metadata = {item.get('Name'): item.get('Value') for item in raw_metadata}

    success = ConfirmPaymentService.process_payment_signal(
        checkout_request_id=checkout_request_id,
        result_code=int(stk_callback.get('ResultCode', -1)),
        result_desc=stk_callback.get('ResultDesc', ''),
        metadata=metadata,
        source=f'retry_task_att_{attempt}'
    )

    if not success:
        if attempt < 4:
            delays = {1: 5, 2: 15, 3: 45}
            retry_unmatched_callback_task.apply_async(args=[callback_data, attempt + 1], countdown=delays[attempt])
            return f"Requeued attempt {attempt + 1}"
        return "Permanently unmatched"

    return f"Matched and processed on attempt {attempt}"

@shared_task
def reconcile_pending_billing_payments():
    """
    🛡️ ARCHITECTURAL HARDENING: Safaricom Reconciliation Safety Net
    """
    from .api_v1_billing_views import subscription_callback
    
    cutoff = timezone.now() - timedelta(minutes=3)
    
    cutoff = timezone.now() - timedelta(minutes=3)
    stale_cutoff = timezone.now() - timedelta(hours=1)
    
    pending = SubscriptionPayment.objects.filter(
        status='pending',
        checkout_request_id__isnull=False,
        created_at__lt=cutoff,
        created_at__gt=stale_cutoff
    )
    
    count = 0
    for payment in pending:
        try:
            mpesa = MpesaIntegration(store=None) 
            result = mpesa.query_stk_status(payment.checkout_request_id)
            if not result.get('success'): continue
            result_code = result.get('result_code')
            if result_code in (None, '4999'): continue
            
            fake_callback = {
                'Body': {'stkCallback': {
                    'CheckoutRequestID': payment.checkout_request_id,
                    'ResultCode': int(result_code),
                    'ResultDesc': result.get('result_desc', ''),
                    'CallbackMetadata': {'Item': [
                        {'Name': 'Amount', 'Value': float(payment.amount)},
                        {'Name': 'MpesaReceiptNumber', 'Value': result.get('metadata', {}).get('MpesaReceiptNumber')},
                    ]},
                }}
            }
            factory = RequestFactory()
            request = factory.post('/api/v1/billing/callback/', json.dumps(fake_callback), content_type='application/json')
            # 🛡️ Mocking DRF's .data behavior
            request.data = fake_callback
            subscription_callback(request)
            count += 1
        except Exception:
            logger.exception(f"Billing Reconciliation failed for {payment.checkout_request_id}")
    return f"Reconciled {count} payments"

@shared_task
def reconcile_pending_mpesa_payments():
    cutoff = timezone.now() - timedelta(minutes=2)
    stale_cutoff = timezone.now() - timedelta(hours=1)

    pending_contributions = ShirikiContribution.objects.filter(status='pending', checkout_request_id__isnull=False, created_at__lt=cutoff, created_at__gt=stale_cutoff)
    for contrib in pending_contributions:
        _reconcile_one(contrib.checkout_request_id, contrib.session.order, contrib)

    pending_orders = Order.objects.filter(payment_status='pending', mpesa_checkout_request_id__isnull=False, created_at__lt=cutoff, created_at__gt=stale_cutoff)
    for order in pending_orders:
        _reconcile_one(order.mpesa_checkout_request_id, order, None)

def _reconcile_one(checkout_request_id, order, contribution):
    from .payment_service import ConfirmPaymentService
    try:
        mpesa = MpesaIntegration(store=order.store)
        result = mpesa.query_stk_status(checkout_request_id)
        if not result.get('success'): return
        result_code = result.get('result_code')
        if result_code in (None, '4999'): return
        
        ConfirmPaymentService.process_payment_signal(
            checkout_request_id=checkout_request_id,
            result_code=int(result_code),
            result_desc=result.get('result_desc', ''),
            metadata=result.get('metadata', {}),
            source='reconciliation_task'
        )
    except Exception:
        logger.exception(f"Reconciliation failed for {checkout_request_id}")


@shared_task
def reconcile_payment_attempt_task(attempt_id):
    from .reconciliation_service import ReconciliationService
    return ReconciliationService.reconcile(attempt_id)


@shared_task(queue='payment_reconciliation')
def review_stale_initiating_payment_attempts(limit=500):
    """Close crashed provider calls without sending a duplicate STK request."""
    cutoff = timezone.now() - timedelta(minutes=5)
    attempts = list(PaymentAttempt.objects.filter(
        status=PaymentAttempt.Status.INITIATING,
        initiation_started_at__lt=cutoff,
    ).order_by('initiation_started_at')[:limit])
    reviewed = 0
    for attempt in attempts:
        updated = PaymentAttempt.objects.filter(
            pk=attempt.pk, status=PaymentAttempt.Status.INITIATING
        ).update(
            status=PaymentAttempt.Status.MANUAL_REVIEW,
            manual_review_reason='Provider initiation became stale without a checkout request.',
        )
        if not updated:
            continue
        if attempt.order_id:
            from .inventory_service import InventoryReservationService
            InventoryReservationService.release_order(attempt.order_id)
        if attempt.shiriki_contribution_id:
            ShirikiContribution.objects.filter(
                pk=attempt.shiriki_contribution_id, status='pending'
            ).update(status='failed')
        reviewed += 1
    return reviewed


def reconcile_payment_attempts():
    """Schedule bounded reconciliation for pending PaymentAttempts only."""
    from django.db.models import Q
    from .reconciliation_service import ReconciliationService
    cutoff = timezone.now() - timedelta(minutes=2)
    attempts = PaymentAttempt.objects.filter(
        status=PaymentAttempt.Status.PENDING,
        checkout_request_id__isnull=False,
        created_at__lt=cutoff,
        reconciliation_attempts__lt=ReconciliationService.MAX_ATTEMPTS,
    ).filter(Q(next_reconciliation_at__isnull=True) | Q(next_reconciliation_at__lte=timezone.now()))
    count = 0
    for attempt_id in attempts.values_list('id', flat=True)[:500]:
        reconcile_payment_attempt_task.delay(attempt_id)
        count += 1
    return f'Scheduled reconciliation for {count} payment attempts'


# Compatibility names used by existing Celery Beat and operator tooling.
@shared_task(name='urbanfoods.tasks.reconcile_pending_mpesa_payments')
def reconcile_pending_mpesa_payments():
    return reconcile_payment_attempts()


@shared_task(name='urbanfoods.tasks.reconcile_pending_billing_payments')
def reconcile_pending_billing_payments():
    return reconcile_payment_attempts()

@shared_task(bind=True, max_retries=6, queue='payment_initiation')
def trigger_stk_push_task(self, order_id, mpesa_phone, contribution_id=None):
    """Compatibility entry point; all provider initiation goes through PaymentAttempt."""
    try:
        if contribution_id:
            contribution = ShirikiContribution.objects.select_related('session__order').get(id=contribution_id)
            from .payment_initiation import InitiatePaymentService
            attempt, _ = InitiatePaymentService.create_or_get_for_contribution(contribution, mpesa_phone)
        else:
            order = Order.objects.select_related('store', 'user').get(id=order_id)
            from .payment_initiation import InitiatePaymentService
            attempt, _ = InitiatePaymentService.create_or_get_for_order(
                order, mpesa_phone or order.phone_number or (order.user.phone if order.user else None)
            )
        return f"Payment attempt queued: {attempt.public_payment_id}"
    except Exception as e:
        logger.exception("STK Task Exception")
        from .payment_backpressure import PaymentBackpressure
        if self.request.retries >= self.max_retries:
            logger.error('STK enqueue retries exhausted: %s', e)
            return {'success': False, 'status': 'queued_but_deferred'}
        raise self.retry(
            exc=e,
            countdown=PaymentBackpressure.retry_delay(self.request.retries),
        )

@shared_task(bind=True, max_retries=6, queue='payment_initiation')
def initiate_payment_attempt_task(self, attempt_id):
    from .payment_initiation import InitiatePaymentService
    from .payment_backpressure import PaymentBackpressure
    from .observability import increment_metric
    try:
        admitted, reason = PaymentBackpressure.admit_provider_call(attempt_id)
        if not admitted:
            if reason == 'provider_circuit_open':
                increment_metric('payment_provider_circuit_open_total')
            else:
                increment_metric('payment_provider_queue_deferred_total')
            raise RuntimeError(reason)
        result = InitiatePaymentService.initiate_attempt(attempt_id)
        PaymentBackpressure.record_provider_result(result)
        return result
    except PaymentAttempt.DoesNotExist:
        logger.warning("Payment attempt %s no longer exists", attempt_id)
        return {'success': False, 'status': 'missing'}
    except Exception as exc:
        logger.exception("Payment attempt initiation task failed for %s", attempt_id)
        if self.request.retries >= self.max_retries:
            logger.error('Payment attempt %s deferred retries exhausted', attempt_id)
            return {'success': False, 'status': 'queued_but_deferred'}
        raise self.retry(
            exc=exc,
            countdown=PaymentBackpressure.retry_delay(self.request.retries),
        )


@shared_task(queue='payment_initiation')
def requeue_deferred_payment_attempts(limit=100):
    """Recover attempts left pending after bounded admission retries."""
    cutoff = timezone.now() - timedelta(seconds=30)
    attempts = PaymentAttempt.objects.filter(
        status=PaymentAttempt.Status.PENDING,
        checkout_request_id__isnull=True,
        created_at__lt=cutoff,
    ).order_by('created_at').values_list('id', flat=True)[:limit]
    for attempt_id in attempts:
        initiate_payment_attempt_task.delay(attempt_id)
    return len(attempts)

@shared_task
def post_payment_confirmation_task(order_id):
    """Run non-critical order effects after payment commit."""
    try:
        order = Order.objects.select_related('store', 'user').get(id=order_id)
        from .utils import notify_new_order, update_weekly_revenue_share
        notify_new_order(order)
        update_weekly_revenue_share(order)
    except Order.DoesNotExist:
        logger.warning("Post-payment order %s no longer exists", order_id)
    except Exception:
        logger.exception("Post-payment effects failed for order %s", order_id)


@shared_task
def notify_shiriki_progress_task(session_id, contributor_id, amount):
    try:
        session = ShirikiSession.objects.select_related('order', 'host').get(id=session_id)
        contributor = User.objects.get(id=contributor_id)
        confirmed_qs = ShirikiContribution.objects.filter(session=session, status='confirmed')
        current_total = float(confirmed_qs.aggregate(Sum('amount_applied_to_pot'))['amount_applied_to_pot__sum'] or 0)
        participant_ids = list(confirmed_qs.values_list('user_id', flat=True))
        participant_ids.append(session.host.id)
        unique_participants = list(set(map(str, participant_ids)))
        
        for user_id in unique_participants:
            if str(user_id) == str(contributor_id): continue
            send_lifecycle_notification_task.delay(user_id, "Pot Filling Up! 🥂", f"{contributor.username} added KSh {amount} to the pot.", 
                {'type': 'shiriki_progress', 'session_id': str(session.id), 'current_amount': str(current_total), 'target_amount': str(session.order.total)})
    except Exception as e:
        logger.error(f"Error in notify_shiriki_progress_task: {e}")
