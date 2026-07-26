# urbanfoods/notifications.py
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

local_time = timezone.localtime(timezone.now())

def safe_upper(val):
    return str(val).upper() if val else 'N/A'

def send_admin_order_notification(order):
    """Send email notification to admin when a new order is received"""
    subject = f'🔔 New Order: {order.order_number}'
    
    # Context for template
    context = {
        'order': order,
        'site_url': settings.SITE_URL,
        'now': timezone.now()
    }
    
    # Render templates
    html_message = render_to_string('emails/admin_order_notification.html', context)
    
    # Get order items for plain text
    items_list = "\n".join([
        f"  - {item.food_item.name} x{item.quantity} @ KES {item.price_at_order}"
        for item in order.items.all()
    ])
    
    # Plain text version
    message = f'''
New Order Received!

Order Details:
--------------
Order Number: {order.order_number}
Store: {order.store.name}
Status: {safe_upper(order.status)}

Customer Information:
--------------------
Name: {order.user.get_full_name() or order.user.username}
Email: {order.user.email}
Phone: {order.phone_number}

Delivery Details:
----------------
Hostel: {order.hostel}
Room Number: {order.room_number}
Delivery Notes: {order.delivery_notes or 'None'}

Order Summary:
-------------
{items_list}

Subtotal: KES {order.subtotal}
Delivery Fee: KES {order.delivery_fee}
Total Amount: KES {order.total}

Payment:
--------
Payment Method: {safe_upper(order.payment_method)}
Payment Status: {safe_upper(order.payment_status)}

View order details at:
{settings.SITE_URL}/admin-panel/orders/

---
TipsyTheoryy Admin System
    '''
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_NOTIFICATION_EMAIL],
            fail_silently=False,
            html_message=html_message,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send admin notification email: {e}")
        return False


def send_customer_order_confirmation(order):
    """Send order confirmation email to customer"""
    subject = f'Order Confirmation - {order.order_number}'
    
    # Context for template
    context = {
        'order': order,
        'now': timezone.now()
    }
    
    # Render templates
    html_message = render_to_string('emails/customer_order_confirmation.html', context)
    
    # Get order items for plain text
    items_list = "\n".join([
        f"  - {item.food_item.name} x{item.quantity} @ KES {item.price_at_order}"
        for item in order.items.all()
    ])
    
    payment_instructions = ""
    if order.payment_method == 'cash':
        if order.store_type == 'liquor':
            payment_instructions = f'''
Payment Instructions:
--------------------
Please complete payment using M-PESA Paybill:
Business Number: 8330098 - NETWIX
Account Number: {order.order_number}
Amount: KES {order.total}
'''
        else:
            payment_instructions = f'''
Payment Instructions:
--------------------
Please complete payment using M-PESA Till Number:
Till Number: 6960814 - MOSES ONKUNDI ATINDA
Amount: KES {order.total}
'''
    
    # Plain text version
    message = f'''
Thank you for your order!

Hi {order.user.get_full_name() or order.user.username},

Your order #{order.order_number} has been received and is being processed.

Order Summary:
-------------
{items_list}

Subtotal: KES {order.subtotal}
Delivery Fee: KES {order.delivery_fee}
Total Amount: KES {order.total}

{payment_instructions}

Track your order: tipsytheoryy://order/{order.id}

Questions? Reply to this email or call 0110345054.

Thank you for choosing Tipsy Theoryy!
    '''
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.user.email],
            fail_silently=False,
            html_message=html_message,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send customer confirmation email: {e}")
        return False
