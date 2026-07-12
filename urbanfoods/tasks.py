from celery import shared_task
from .utils import send_fcm_notification
from .models import User, MarketingBlast, Store
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
        
        # Get unique customers who have ordered from this store
        # This can be refined based on 'follower' logic if implemented later
        from .models import Order
        customer_ids = Order.objects.filter(store=store).values_list('user_id', flat=True).distinct()
        
        customers = User.objects.filter(id__in=customer_ids, fcm_token__isnull=False).exclude(fcm_token='')
        
        count = 0
        for customer in customers:
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
