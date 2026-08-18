from celery import shared_task
from .utils import send_fcm_notification, send_telegram_notification, send_telegram_message
from .models import (
    User, MarketingBlast, Store, Cart, ShirikiSession, 
    ShirikiContribution, RiderEarning, RiderWeeklyStat, Order, SubscriptionPayment
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
    from .models import Order, ShirikiContribution
    from .views import process_mpesa_callback_data
    
    stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
    checkout_request_id = stk_callback.get('CheckoutRequestID')

    if not checkout_request_id: return "No CheckoutRequestID"

    order = None
    contribution = None

    try:
        order = Order.objects.select_related('user').get(mpesa_checkout_request_id=checkout_request_id)
    except Order.DoesNotExist:
        try:
            contribution = ShirikiContribution.objects.select_related('session__order', 'user').get(checkout_request_id=checkout_request_id)
            order = contribution.session.order
        except ShirikiContribution.DoesNotExist:
            order = None

    if order is None:
        if attempt < 4:
            delays = {1: 3, 2: 8, 3: 20}
            retry_unmatched_callback_task.apply_async(args=[callback_data, attempt + 1], countdown=delays[attempt])
            return f"Requeued attempt {attempt + 1}"
        return "Permanently unmatched"

    process_mpesa_callback_data(callback_data, order=order, contribution=contribution)
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
                        {'Name': 'MpesaReceiptNumber', 'Value': 'RECONCILED'},
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
    from .views import process_mpesa_callback_data
    cutoff = timezone.now() - timedelta(minutes=2)
    stale_cutoff = timezone.now() - timedelta(hours=1)

    pending_contributions = ShirikiContribution.objects.filter(status='pending', checkout_request_id__isnull=False, created_at__lt=cutoff, created_at__gt=stale_cutoff)
    for contrib in pending_contributions:
        _reconcile_one(contrib.checkout_request_id, contrib.session.order, contrib)

    pending_orders = Order.objects.filter(payment_status='pending', mpesa_checkout_request_id__isnull=False, created_at__lt=cutoff, created_at__gt=stale_cutoff)
    for order in pending_orders:
        _reconcile_one(order.mpesa_checkout_request_id, order, None)

def _reconcile_one(checkout_request_id, order, contribution):
    from .views import process_mpesa_callback_data
    try:
        mpesa = MpesaIntegration(store=order.store)
        result = mpesa.query_stk_status(checkout_request_id)
        if not result.get('success'): return
        result_code = result.get('result_code')
        if result_code in (None, '4999'): return
        fake_callback = {
            'Body': {'stkCallback': {
                'CheckoutRequestID': checkout_request_id,
                'ResultCode': int(result_code),
                'ResultDesc': result.get('result_desc', ''),
                'CallbackMetadata': {'Item': []},
            }}
        }
        process_mpesa_callback_data(fake_callback, order, contribution)
    except Exception:
        logger.exception(f"Reconciliation failed for {checkout_request_id}")

@shared_task(rate_limit='50/s', bind=True, max_retries=3)
def trigger_stk_push_task(self, order_id, mpesa_phone, contribution_id=None):
    try:
        from django.core.cache import cache
        lock_key = f"stk_push_lock_contrib_{contribution_id}" if contribution_id else f"stk_push_lock_ord_{order_id}"
        if cache.get(lock_key): return "Locked"
        cache.set(lock_key, True, timeout=45)

        contribution = None
        if contribution_id:
            contribution = ShirikiContribution.objects.select_related('session__order', 'user').get(id=contribution_id)
            order = contribution.session.order
            amount_to_charge = contribution.amount
            account_ref = f"POT-{contribution.id}"
            desc = f"Shiriki Contrib {contribution.session.invite_code}"
        else:
            order = Order.objects.select_related('store', 'user').get(id=order_id)
            if order.payment_status == 'paid': return "Already Paid"
            amount_to_charge = order.total
            account_ref = f"ORD-{order.order_number}"
            desc = f"Order {order.order_number} Payment"

        mpesa = MpesaIntegration(store=order.store)
        phone_to_use = mpesa_phone or order.phone_number or (order.user.phone if order.user else None)
        if not phone_to_use: return "Failed: Missing Phone"
        phone = mpesa.format_phone_number(phone_to_use)
        
        is_production = str(os.environ.get('MPESA_PRODUCTION', 'false')).lower() == 'true'
        stk_amount = int(amount_to_charge) if is_production else 1
        
        stk_result = mpesa.initiate_stk_push(phone_number=phone, amount=stk_amount, account_reference=account_ref, transaction_desc=desc)
        if stk_result.get('success'):
            checkout_id = stk_result.get('checkout_request_id')
            if contribution:
                contribution.checkout_request_id = checkout_id
                contribution.save(update_fields=['checkout_request_id'])
            else:
                order.mpesa_checkout_request_id = checkout_id
                order.save(update_fields=['mpesa_checkout_request_id'])
            return f"Success: {checkout_id}"
        else:
            if stk_result.get('retryable', False): raise self.retry(countdown=5)
            return f"Failed: {stk_result.get('message')}"
    except Exception as e:
        logger.exception("STK Task Exception")
        raise self.retry(exc=e, countdown=10)

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
