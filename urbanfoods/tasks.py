from celery import shared_task
from .utils import send_fcm_notification, send_telegram_notification, send_telegram_message
from .models import (
    User, MarketingBlast, Store, Cart, ShirikiSession, 
    ShirikiContribution, RiderEarning, RiderWeeklyStat, Order
)
from .mpesa_utils import MpesaIntegration
import os
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

@shared_task(rate_limit='5000/m')
def send_single_marketing_notification(user_id, title, body, data=None):
    """
    Sends a single FCM notification to a user.
    Rate limited to 5000 per minute to prevent Thundering Herd on backend.
    """
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
    """
    Background task for order lifecycle notifications (Placed, Paid, Delivered).
    """
    try:
        user = User.objects.get(id=user_id)
        send_fcm_notification(user, title, body, data)
    except User.DoesNotExist:
        logger.error(f"User with id {user_id} does not exist")
    except Exception as e:
        logger.error(f"Error in send_lifecycle_notification_task: {e}")

@shared_task
def send_marketing_blast_task(store_id, blast_id):
    """
    Task to initiate a marketing blast.
    Queries relevant customers and queues individual notification tasks.
    """
    try:
        store = Store.objects.get(id=store_id)
        blast = MarketingBlast.objects.get(id=blast_id)
        
        # Get unique customers who have ordered from this store AND have an FCM token
        from .models import Order
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
    """
    Background task to send a telegram notification to a specific chat ID.
    """
    try:
        return send_telegram_notification(chat_id, message, bot_type)
    except Exception as e:
        logger.error(f"Error in send_telegram_notification_task: {e}")
        return False

@shared_task
def send_telegram_message_task(message, buttons=None, bot_type='admin'):
    """
    Background task to send a telegram message to global admin chat IDs.
    """
    try:
        return send_telegram_message(message, buttons, bot_type)
    except Exception as e:
        logger.error(f"Error in send_telegram_message_task: {e}")
        return False

@shared_task
def check_abandoned_carts():
    """
    Production-Ready Heartbeat task to remind users of items left in their cart.
    Scalable: Uses .iterator() to handle 10,000+ users without memory spikes.
    """
    try:
        # threshold: 2 hours ago
        threshold = timezone.now() - timedelta(hours=2)
        
        # 🛡️ Scalable Query: Use .iterator() to stream results from DB
        # This prevents loading all 10,000 users into memory at once
        abandoned_carts = Cart.objects.filter(
            updated_at__lte=threshold,
            items__isnull=False,
            user__fcm_token__isnull=False
        ).exclude(
            last_reminder_sent_at__date=timezone.now().date()
        ).select_related('user').distinct().iterator(chunk_size=500)

        count = 0
        for cart in abandoned_carts:
            # Send notification
            send_lifecycle_notification_task.delay(
                cart.user.id,
                "Items waiting for you! 🥂",
                "You left some items in your cart. Grab them before they're gone!",
                {'type': 'cart_reminder'}
            )
            
            # Update last reminder timestamp
            cart.last_reminder_sent_at = timezone.now()
            cart.save(update_fields=['last_reminder_sent_at'])
            count += 1
            
        if count > 0:
            logger.info(f"Processed {count} abandoned cart reminders.")
            
    except Exception as e:
        logger.error(f"Error in check_abandoned_carts: {e}")

@shared_task
def notify_new_arrival_task(product_id):
    """
    Notify previous customers of a store when a new liquor arrival is added.
    """
    try:
        from .models import FoodItem, Order
        product = FoodItem.objects.get(id=product_id)
        store = product.store
        
        # Only for Pro stores and Liquor items
        if not store.is_pro or product.store_type != 'liquor':
            return

        # Find unique customers who have ordered from this store
        customer_ids = Order.objects.filter(
            store=store,
            user__fcm_token__isnull=False
        ).exclude(user__fcm_token='').values_list('user_id', flat=True).distinct()
        
        count = 0
        for cust_id in customer_ids:
            send_lifecycle_notification_task.delay(
                cust_id,
                f"New in Stock at {store.name}! 🍾",
                f"Check out our new arrival: {product.name}",
                {'type': 'new_arrival', 'product_id': str(product.id)}
            )
            count += 1
            
        logger.info(f"Queued {count} new arrival notifications for {product.name} (Store: {store.id})")
        
    except FoodItem.DoesNotExist:
        logger.error(f"Product {product_id} not found for new arrival notification")
    except Exception as e:
        logger.error(f"Error in notify_new_arrival_task: {e}")

@shared_task
def check_expired_shiriki_sessions():
    """Safety Net: Refund expired Shiriki sessions to user wallets."""
    now = timezone.now()
    expired_sessions = ShirikiSession.objects.filter(
        status='active',
        expires_at__lt=now
    )
    
    count = 0
    for session in expired_sessions:
        try:
            with transaction.atomic():
                session.status = 'expired'
                session.save()
                
                # Refund confirmed contributions to Tipsy Credit
                contributions = session.contributions.filter(status='confirmed')
                for contrib in contributions:
                    user = contrib.user
                    amount = contrib.amount
                    
                    # Add to wallet
                    user.wallet_balance += amount
                    user.save()
                    
                    # Mark as refunded
                    contrib.status = 'refunded'
                    contrib.save()
                    
                    # Notify User
                    title = "Shiriki Session Expired"
                    body = f"The pot for {session.order.order_number} didn't fill up. KSh {amount} has been refunded to your Tipsy Credit. 🥂"
                    send_fcm_notification(user, title, body, data={"type": "wallet_refund"})
                
                # Cancel the original order
                session.order.status = 'cancelled'
                session.order.save()
                
                count += 1
        except Exception as e:
            logger.error(f"Failed to process expiry for Shiriki Session {session.invite_code}: {e}")

    return f"Processed {count} expired Shiriki sessions"

@shared_task
def calculate_rider_weekly_stats():
    """
    Automated Weekly Payout Calculation.
    Runs every Sunday at 23:59.
    Aggregates all RiderEarning for the current week and groups them by Rider and Store.
    """
    from django.db.models import Sum
    from datetime import date, timedelta
    
    today = timezone.localdate()
    # Week start: last Monday
    week_start = today - timedelta(days=today.weekday())
    # Week end: today (Sunday)
    week_end = today
    
    # Get all earnings for this week
    earnings = RiderEarning.objects.filter(
        created_at__date__gte=week_start,
        created_at__date__lte=week_end
    ).select_related('rider', 'order__store')
    
    # Group by (rider, store)
    # Note: In a large system, use .values('rider', 'order__store').annotate(...)
    # For Tipsy V1, we iterate for clarity and precision
    rider_store_map = {}
    
    for earn in earnings:
        key = (earn.rider.id, earn.order.store.id)
        if key not in rider_store_map:
            rider_store_map[key] = {
                'base': 0,
                'tips': 0,
                'rider': earn.rider,
                'store': earn.order.store
            }
        
        rider_store_map[key]['base'] += earn.base_fare
        rider_store_map[key]['tips'] += earn.tip
        
    count = 0
    for key, data in rider_store_map.items():
        total = data['base'] + data['tips']
        if total > 0:
            stat, created = RiderWeeklyStat.objects.get_or_create(
                rider=data['rider'],
                store=data['store'],
                week_start=week_start,
                defaults={
                    'week_end': week_end,
                    'total_base_fare': data['base'],
                    'total_tips': data['tips'],
                    'total_amount': total,
                    'status': 'unpaid'
                }
            )
            if not created:
                # Update if already exists (safe for re-runs)
                stat.total_base_fare = data['base']
                stat.total_tips = data['tips']
                stat.total_amount = total
                stat.save()
            count += 1
            
    logger.info(f"Generated {count} RiderWeeklyStat records for week {week_start}")
    return f"Generated {count} stats"

@shared_task(bind=True, max_retries=3)
def retry_unmatched_callback_task(self, callback_data, attempt=1):
    """
    Retries matching an M-Pesa callback to an Order/ShirikiContribution.
    Exists to cover the race where Safaricom's callback arrives before
    trigger_stk_push_task has finished saving checkout_request_id to the DB.
    """
    from .models import Order, ShirikiContribution
    from django.db import transaction

    stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
    checkout_request_id = stk_callback.get('CheckoutRequestID')

    if not checkout_request_id:
        logger.error("retry_unmatched_callback_task: missing CheckoutRequestID, dropping")
        return "No CheckoutRequestID"

    order = None
    contribution = None

    try:
        order = Order.objects.select_related('user').get(
            mpesa_checkout_request_id=checkout_request_id
        )
    except Order.DoesNotExist:
        try:
            contribution = ShirikiContribution.objects.select_related(
                'session__order', 'user'
            ).get(checkout_request_id=checkout_request_id)
            order = contribution.session.order
        except ShirikiContribution.DoesNotExist:
            order = None

    if order is None:
        if attempt < 4:
            # Backoff: 3s, 8s, 20s — covers realistic DB-write delay without hammering
            delays = {1: 3, 2: 8, 3: 20}
            logger.warning(
                "Callback still unmatched (attempt %s) for CheckoutRequestID: %s — retrying",
                attempt, checkout_request_id
            )
            retry_unmatched_callback_task.apply_async(
                args=[callback_data, attempt + 1],
                countdown=delays[attempt]
            )
            return f"Requeued attempt {attempt + 1}"
        else:
            # Genuinely unmatched after ~30s total — this is no longer a timing issue.
            logger.error(
                "Callback PERMANENTLY unmatched for CheckoutRequestID: %s. "
                "Manual reconciliation required. Raw: %s",
                checkout_request_id, json.dumps(callback_data)
            )
            # Optional: wire in an alert here (Slack webhook, email to yourself, etc.)
            # so a lost payment surfaces immediately instead of waiting for a customer complaint.
            return "Permanently unmatched — needs manual reconciliation"

    # Found it — replay the same processing logic the main callback view uses.
    from .views import process_mpesa_callback_data  # see note below
    process_mpesa_callback_data(callback_data, order=order, contribution=contribution)
    return f"Matched and processed on attempt {attempt}"

@shared_task(rate_limit='50/s', bind=True, max_retries=3)
def trigger_stk_push_task(self, order_id, mpesa_phone, contribution_id=None):
    """
    Asynchronous task to trigger M-Pesa STK Push.
    Rate limited to 50/s to comply with Safaricom TPS limits.
    Handles both direct orders and Shiriki contributions.
    """
    try:
        from .models import ShirikiContribution, Order
        
        # Determine target and context
        contribution = None
        if contribution_id:
            contribution = ShirikiContribution.objects.select_related('session__order', 'user').get(id=contribution_id)
            order = contribution.session.order
            amount_to_charge = contribution.amount
            account_ref = f"POT-{contribution.session.invite_code}"
            desc = f"Shiriki Contribution {contribution.session.invite_code}"
        else:
            # Direct Order path
            order = Order.objects.select_related('store', 'user').get(id=order_id)
            if order.payment_status == 'paid':
                return "Already Paid"
            amount_to_charge = order.total
            account_ref = f"ORD-{order.order_number}"
            desc = f"Order {order.order_number} Payment"

        mpesa = MpesaIntegration(store=order.store)
        
        # 🛡️ Resiliency: Fallback to user phone if order phone is missing
        phone_to_use = mpesa_phone or order.phone_number or (order.user.phone if order.user else None)
        if not phone_to_use:
            logger.error(f"STK Task Failed: No phone number found for Order {order.order_number}")
            return "Failed: Missing Phone"
            
        try:
            phone = mpesa.format_phone_number(phone_to_use)
        except ValueError as ve:
            logger.error(f"STK Task Failed: Invalid phone format '{phone_to_use}' - {ve}")
            return f"Failed: Invalid Phone Format"
        
        # 🛡️ Fail-Closed Production Guard
        is_production = str(os.environ.get('MPESA_PRODUCTION', 'false')).lower() == 'true'
        stk_amount = int(amount_to_charge) if is_production else 1
        
        logger.info(f"Task: Initiating STK for {account_ref} to {phone}")
        
        stk_result = mpesa.initiate_stk_push(
            phone_number=phone,
            amount=stk_amount,
            account_reference=account_ref,
            transaction_desc=desc
        )
        
        if stk_result.get('success'):
            checkout_id = stk_result.get('checkout_request_id')
            if contribution:
                contribution.checkout_request_id = checkout_id
                contribution.save(update_fields=['checkout_request_id'])
            else:
                order.mpesa_checkout_request_id = checkout_id
                order.save(update_fields=['mpesa_checkout_request_id'])
            
            # Notify user via Silent FCM that STK is coming
            target_user_id = contribution.user.id if contribution else order.user.id
            send_lifecycle_notification_task.delay(
                target_user_id,
                "Payment Processing",
                "Please check your phone for the M-Pesa PIN prompt.",
                {
                    'type': 'stk_initiated', 
                    'order_id': str(order.id),
                    'is_shiriki': 'true' if contribution else 'false'
                }
            )
            return f"Success: {checkout_id}"
        else:
            error_msg = stk_result.get('message', 'M-Pesa service unavailable')
            logger.error(f"STK Task Failed: {error_msg}")
            if stk_result.get('retryable', False):
                raise self.retry(countdown=5)
            return f"Failed: {error_msg}"
            
    except (Order.DoesNotExist, ShirikiContribution.DoesNotExist):
        logger.error(f"STK Task Error: Target record not found")
    except Exception as e:
        logger.exception(f"STK Task Exception")
        raise self.retry(exc=e, countdown=10)

@shared_task
def notify_shiriki_progress_task(session_id, contributor_id, amount):
    """
    Broadcasts pot progress to ALL participants in a Shiriki Session.
    Ensures real-time synchronization of progress bars.
    """
    try:
        from .models import ShirikiSession, ShirikiContribution
        session = ShirikiSession.objects.select_related('order', 'host').get(id=session_id)
        contributor = User.objects.get(id=contributor_id)
        
        # Get all participants (Host + confirmed contributors)
        participant_ids = list(ShirikiContribution.objects.filter(
            session=session, 
            status='confirmed'
        ).values_list('user_id', flat=True))
        participant_ids.append(session.host.id)
        unique_participants = list(set(participant_ids))
        
        # Calculate current total for the update
        current_total = float(ShirikiContribution.objects.filter(
            session=session, 
            status='confirmed'
        ).aggregate(Sum('amount'))['amount__sum'] or 0)
        
        title = "Pot Filling Up! 🥂"
        body = f"{contributor.first_name or contributor.username} added KSh {amount} to the pot."
        
        for user_id in unique_participants:
            # Don't notify the person who just paid (their app already knows)
            if user_id == contributor_id: continue
            
            send_lifecycle_notification_task.delay(
                user_id,
                title,
                body,
                {
                    'type': 'shiriki_progress',
                    'session_id': str(session.id),
                    'current_amount': str(current_total),
                    'target_amount': str(session.order.total)
                }
            )
            
    except Exception as e:
        logger.error(f"Error in notify_shiriki_progress_task: {e}")
