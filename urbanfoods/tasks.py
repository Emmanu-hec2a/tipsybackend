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
def calculate_rider_weekly_stats(force_date=None):
    """
    Automated Weekly Payout Calculation.
    Runs every Sunday at 23:59.
    Aggregates all RiderEarning for the previous week and groups them by Rider and Store.
    """
    from django.db.models import Sum
    from datetime import date, timedelta
    
    # 🛡️ TIMEZONE HARDENING: Use force_date for debugging or manual runs
    today = force_date or timezone.localdate()
    
    # Logic: We want to calculate for the week that JUST ended.
    # If today is Sunday (weekday 6), week_start is Monday, week_end is Sunday.
    week_start = today - timedelta(days=today.weekday())
    week_end = today
    
    logger.info(f"Starting Rider Payout Calculation for range: {week_start} to {week_end}")
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

@shared_task
def reconcile_pending_mpesa_payments():
    """
    Catches contributions/orders whose M-Pesa callback never arrived,
    by actively querying Safaricom for the true status.
    Runs every 2 minutes via Celery Beat.
    """
    from datetime import timedelta
    from .models import ShirikiContribution, Order
    from .views import process_mpesa_callback_data

    cutoff = timezone.now() - timedelta(minutes=2)
    stale_cutoff = timezone.now() - timedelta(hours=1)

    # ── Shiriki contributions stuck pending ──
    pending_contributions = ShirikiContribution.objects.filter(
        status='pending',
        checkout_request_id__isnull=False,
        created_at__lt=cutoff,
        created_at__gt=stale_cutoff,
    ).select_related('session__order__store')

    for contribution in pending_contributions:
        _reconcile_one(contribution.checkout_request_id, contribution.session.order, contribution)

    # ── Standard orders stuck pending ──
    pending_orders = Order.objects.filter(
        payment_status='pending',
        mpesa_checkout_request_id__isnull=False,
    ).exclude(mpesa_checkout_request_id='').filter(
        created_at__lt=cutoff,
        created_at__gt=stale_cutoff,
    ).select_related('store')

    for order in pending_orders:
        _reconcile_one(order.mpesa_checkout_request_id, order, None)


def _reconcile_one(checkout_request_id, order, contribution):
    from .views import process_mpesa_callback_data
    try:
        mpesa = MpesaIntegration(store=order.store)
        result = mpesa.query_stk_status(checkout_request_id)

        if not result.get('success'):
            return  # network/auth error querying — try again next run

        result_code = result.get('result_code')
        if result_code in (None, '4999'):
            return  # Safaricom itself says still processing — try again next run

        fake_callback = {
            'Body': {'stkCallback': {
                'CheckoutRequestID': checkout_request_id,
                'ResultCode': int(result_code),
                'ResultDesc': result.get('result_desc', ''),
                'CallbackMetadata': {'Item': []},
            }}
        }
        logger.info(
            "Reconciliation resolved stuck payment: %s (result_code=%s)",
            checkout_request_id, result_code
        )
        process_mpesa_callback_data(fake_callback, order, contribution)
    except Exception:
        logger.exception(f"Reconciliation failed for checkout_request_id={checkout_request_id}")

@shared_task(rate_limit='50/s', bind=True, max_retries=3)
def trigger_stk_push_task(self, order_id, mpesa_phone, contribution_id=None):
    """
    Asynchronous task to trigger M-Pesa STK Push.
    Rate limited to 50/s to comply with Safaricom TPS limits.
    Handles both direct orders and Shiriki contributions.
    """
    try:
        from django.core.cache import cache
        # 🛡️ FIX: For Shiriki contributions, use a more granular lock to allow simultaneous pot contributions.
        # Direct orders still use the order-level lock to prevent double payment.
        if contribution_id:
            lock_key = f"stk_push_lock_contrib_{contribution_id}"
        else:
            lock_key = f"stk_push_lock_ord_{order_id}"

        if cache.get(lock_key):
            logger.warning(f"STK push already in progress for {lock_key}. Skipping.")
            return "Locked"
        cache.set(lock_key, True, timeout=45) # 45s lock to prevent rapid retries

        from .models import ShirikiContribution, Order
        
        # Determine target and context
        contribution = None
        if contribution_id:
            contribution = ShirikiContribution.objects.select_related('session__order', 'user').get(id=contribution_id)
            order = contribution.session.order
            amount_to_charge = contribution.amount
            # 🛡️ FIX: Unique Account Reference to prevent Safaricom from rejecting overlapping pot payments.
            account_ref = f"POT-{contribution.id}"
            desc = f"Shiriki Contrib {contribution.session.invite_code}"
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
            
            # 🛡️ Task: Surface it to the user so it doesn't fail silently
            if not contribution:
                order.payment_status = 'failed'
                order.payment_failure_reason = f"Invalid phone format: {phone_to_use}"
                order.save(update_fields=['payment_status', 'payment_failure_reason'])
            
            target_user_id = contribution.user.id if contribution else order.user.id
            send_lifecycle_notification_task.delay(
                target_user_id,
                "Payment Issue",
                "We couldn't process that phone number. Please check it and try again.",
                {'type': 'phone_format_error', 'order_id': str(order.id)}
            )
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
            
            # 🛡️ Notify user of the failure so UI doesn't hang
            target_user_id = contribution.user.id if contribution else order.user.id
            send_lifecycle_notification_task.delay(
                target_user_id,
                "Payment Failed",
                f"M-Pesa rejected the request: {error_msg}",
                {
                    'type': 'stk_failed', 
                    'order_id': str(order.id),
                    'error': error_msg
                }
            )

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
        
        # Calculate current total for the update
        confirmed_qs = ShirikiContribution.objects.filter(session=session, status='confirmed')
        current_total = float(confirmed_qs.aggregate(Sum('amount_applied_to_pot'))['amount_applied_to_pot__sum'] or 0)
        
        # Determine unique participants to notify (Host + anyone who has contributed)
        participant_ids = list(confirmed_qs.values_list('user_id', flat=True))
        participant_ids.append(session.host.id)
        unique_participants = list(set(participant_ids))
        
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


@shared_task
def send_daily_deals_digest():
    """
    Automated Daily Digest of New Promotions.
    Runs daily at 17:00 EAT.
    Finds active promotions created in the last 24 hours and notifies nearby users.
    """
    from .models import Promotion, Store, SavedAddress
    from .utils import haversine_distance_km
    from django.db.models import Count

    # 1. Find active promos created in the last 24 hours
    yesterday = timezone.now() - timedelta(days=1)
    new_promos = Promotion.objects.filter(
        is_active=True,
        start_date__gte=yesterday,
        store__isnull=False
    ).select_related('store')

    if not new_promos.exists():
        logger.info("Daily Digest: No new promotions found in the last 24 hours.")
        return "No new promos"

    # 2. Group stores with fresh deals
    # { store_id: [promo_titles] }
    promo_stores_map = {}
    for promo in new_promos:
        if promo.store.id not in promo_stores_map:
            promo_stores_map[promo.store.id] = []
        promo_stores_map[promo.store.id].append(promo.title)

    # 3. Get all users with FCM tokens and their primary addresses
    # We use .iterator() to handle large user bases efficiently
    users_with_addresses = User.objects.filter(
        fcm_token__isnull=False,
        saved_addresses__isnull=False
    ).exclude(fcm_token='').prefetch_related('saved_addresses').distinct().iterator(chunk_size=500)

    notification_count = 0
    
    # 🛡️ Limit for V1 to prevent massive loops: 15km radius
    PROXIMITY_RADIUS_KM = 15.0

    for user in users_with_addresses:
        # Check proximity to any store with a deal
        nearby_deals = []
        
        # Get user's primary/default address (fallback to first)
        primary_addr = next((a for a in user.saved_addresses.all() if a.is_default), user.saved_addresses.all()[0])
        
        if not primary_addr.latitude or not primary_addr.longitude:
            continue

        for store_id, titles in promo_stores_map.items():
            store = next(p.store for p in new_promos if p.store.id == store_id)
            
            if not store.latitude or not store.longitude:
                continue

            distance = haversine_distance_km(
                float(primary_addr.latitude), float(primary_addr.longitude),
                float(store.latitude), float(store.longitude)
            )

            if distance <= PROXIMITY_RADIUS_KM:
                nearby_deals.append({
                    'store_name': store.name,
                    'deals': titles
                })

        # 4. Craft and send personalized notification
        if nearby_deals:
            deal_count = len(nearby_deals)
            if deal_count == 1:
                title = f"Fresh Deal at {nearby_deals[0]['store_name']}! 🥂"
                body = f"New offer: {nearby_deals[0]['deals'][0]}. Check it out now!"
            else:
                title = "Tipsy Deals of the Day! 🥂"
                body = f"{deal_count} stores near you have new offers today. Tap to save!"

            send_single_marketing_notification.delay(
                user.id,
                title,
                body,
                {'type': 'daily_digest', 'deal_count': str(deal_count)}
            )
            notification_count += 1

    logger.info(f"Daily Digest: Queued {notification_count} personalized notifications.")
    return f"Sent {notification_count} notifications"
