from celery import shared_task
from .utils import send_fcm_notification, send_telegram_notification, send_telegram_message
from .models import User, MarketingBlast, Store, Cart
from django.utils import timezone
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
    Heartbeat task to remind users of items left in their cart.
    Runs periodically via Celery Beat.
    """
    try:
        # threshold: 2 hours ago
        threshold = timezone.now() - timedelta(hours=2)
        
        # Find carts updated > 2 hours ago that have items
        # and haven't been reminded in the last 24 hours
        abandoned_carts = Cart.objects.filter(
            updated_at__lte=threshold,
            items__isnull=False,
            user__fcm_token__isnull=False
        ).exclude(
            last_reminder_sent_at__date=timezone.now().date()
        ).distinct()

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
            logger.info(f"Sent {count} abandoned cart reminders.")
            
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
