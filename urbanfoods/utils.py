# utils.py
import json
import os
from pywebpush import webpush
from .models import PushSubscription
from math import radians, sin, cos, sqrt, atan2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
import os

def get_aes_key():
    """Get or generate a 32-byte key for AES-256."""
    from django.conf import settings
    key = getattr(settings, 'ENCRYPTION_KEY', os.environ.get('ENCRYPTION_KEY'))
    if not key:
        # Fallback for dev
        return b'6csUuoMhN7dvrad3XaJ5ApYcFPV2AEFtlwSUEAzoREU='
    
    # Ensure it's 32 bytes. If it's a base64 string from Fernet, it might be 32 bytes decoded.
    try:
        decoded = base64.b64decode(key)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
        
    return key.encode().ljust(32)[:32]

def encrypt_verification_image(file_data):
    """Encrypt image data using AES-256-GCM."""
    key = get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, file_data, None)
    return nonce + ciphertext

def decrypt_verification_image(encrypted_data):
    """Decrypt image data using AES-256-GCM."""
    key = get_aes_key()
    aesgcm = AESGCM(key)
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)

def haversine_distance_km(lat1, lng1, lat2, lng2):
    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [float(lat1), float(lng1), float(lat2), float(lng2)])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def calculate_delivery_fee(user_lat, user_lng, store_lat, store_lng, store=None):
    """
    Calculate delivery fee based on distance.
    Priority: Store-specific overrides > SiteSettings global parameters.
    """
    from .models import SiteSettings
    global_settings = SiteSettings.get_instance()
    
    # Use store overrides if available, otherwise fallback to global settings
    base_fee = float(store.base_delivery_fee if store and store.base_delivery_fee is not None else global_settings.base_delivery_fee)
    base_dist = float(store.base_distance_km if store and store.base_distance_km is not None else global_settings.base_distance_km)
    surcharge = float(store.extra_distance_surcharge if store and store.extra_distance_surcharge is not None else global_settings.extra_distance_surcharge)

    distance = haversine_distance_km(user_lat, user_lng, store_lat, store_lng)
    
    if distance <= base_dist:
        return base_fee
    
    extra_km = distance - base_dist
    fee = base_fee + (extra_km * surcharge)
    
    # Round to nearest 5 or 10 for "cleaner" pricing
    return round(fee / 5) * 5

def is_within_delivery_zone(store, lat, lng):
    distance = haversine_distance_km(float(store.latitude), float(store.longitude), lat, lng)
    return distance <= store.delivery_radius_km, round(distance, 2)

VAPID_PRIVATE_KEY = "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgfWfJbjUWsfxd1GxLRwsiVoMo/T5nbZTZKKpa1WUnNA+hRANCAAT9nGX9yf5vW6dwFkKkn6s8rTsIGKiHBwSrGubbo98BtVVfrkwkSMp3v1S9koIv6JigRJ9vLRYFU0b5Zzk3mfdB"
VAPID_CLAIMS = {"sub": "mailto:petniqueke@gmail.com"}

def send_push_to_all(title, body, url="/"):
    subscriptions = PushSubscription.objects.all()
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": sub.keys
                },
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except Exception as e:
            print("Push failed for subscription:", sub.endpoint, e)

# utils.py
import requests
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def format_phone(phone):
    phone = phone.replace(" ", "")
    if phone.startswith("0"):
        phone = "+254" + phone[1:]
    return phone


import firebase_admin
from firebase_admin import credentials, messaging
import json

# Initialize Firebase Admin
try:
    if not firebase_admin._apps:
        # 1. Try environment variable (JSON string) for production/Railway
        service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
        
        if service_account_json:
            try:
                cert_dict = json.loads(service_account_json)
                cred = credentials.Certificate(cert_dict)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase Admin initialized via environment variable")
            except Exception as e:
                logger.error(f"Failed to initialize Firebase via env var: {e}")
        
        # 2. Fallback to file for local development
        if not firebase_admin._apps:
            cred_path = os.path.join(settings.BASE_DIR, 'tipsytheoryy-dfe92-firebase-adminsdk-fbsvc-499b77e717.json')
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase Admin initialized via local JSON file")
            else:
                logger.warning(f"Firebase credentials not found at {cred_path} or FIREBASE_SERVICE_ACCOUNT_JSON env var")
except Exception as e:
    logger.error(f"Firebase Admin initialization failed: {e}")

def send_fcm_notification(user, title, body, data=None):
    """Send FCM push notification to a specific user"""
    if not user.fcm_token:
        return False
    
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=user.fcm_token,
        )
        response = messaging.send(message)
        logger.info(f"Successfully sent FCM message: {response}")
        return True
    except Exception as e:
        logger.error(f"Error sending FCM message: {e}")
        return False

def _send_telegram_message_single(message, buttons=None):
    try:
        bot_token = getattr(settings, 'TELEGRAM_BOTT_TOKEN', None)
        chat_id = getattr(settings, 'TELEGRAM_CHATT_ID', None)

        if not bot_token or not chat_id:
            logger.warning("Telegram credentials not configured")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }

        if buttons:
            payload['reply_markup'] = json.dumps({
                "inline_keyboard": buttons
            })

        response = requests.post(url, data=payload, timeout=10)

        if response.status_code == 200:
            logger.info("✅ Telegram message sent")
            return True
        else:
            logger.error(f"❌ Telegram failed: {response.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Telegram error: {e}")
        return False

def send_telegram_notification(chat_id, message):
    """Send a single telegram message to a specific chat ID"""
    if not chat_id:
        return False
    
    try:
        bot_token = getattr(settings, 'TELEGRAM_BOTT_TOKEN', None)
        if not bot_token:
            return False
            
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, data=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error sending telegram notification: {e}")
        return False

def send_telegram_message(message, buttons=None):
    try:
        bot_token = getattr(settings, 'TELEGRAM_BOTT_TOKEN', None)
        chat_ids = getattr(settings, 'TELEGRAM_CHATT_IDS', None)
        if not chat_ids:
            chat_ids = getattr(settings, 'TELEGRAM_CHATT_ID', None)

        if isinstance(chat_ids, str):
            chat_ids = [chat_id.strip() for chat_id in chat_ids.split(',') if chat_id.strip()]

        if not bot_token or not chat_ids:
            logger.warning("Telegram credentials not configured")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        base_payload = {
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }

        if buttons:
            base_payload['reply_markup'] = json.dumps({
                "inline_keyboard": buttons
            })

        sent_count = 0
        for chat_id in chat_ids:
            payload = {
                **base_payload,
                'chat_id': chat_id,
            }

            response = requests.post(url, data=payload, timeout=10)

            if response.status_code == 200:
                sent_count += 1
                logger.info(f"Telegram message sent to {chat_id}")
            else:
                logger.error(f"Telegram failed for {chat_id}: {response.text}")

        return sent_count > 0

    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def notify_new_order(order):
    try:
        items_list = []
        for item in order.items.all():
            line_total = item.price_at_order * item.quantity
            items_list.append(
                f"  • {item.food_item.name} x{item.quantity} — KES {line_total}"
            )

        items_text = "\n".join(items_list) if items_list else "  No items"
        customer_name = order.user.username if order.user else "N/A"

        message = f"""
🆕 <b>NEW ORDER RECEIVED!</b>

📦 <b>Order #{order.order_number}</b>
━━━━━━━━━━━━━━━━━━━━
👤 <b>Customer:</b> {customer_name}
📱 <b>Phone:</b> {order.phone_number or 'N/A'}
🏠 <b>Location:</b> {order.address_string or order.hostel or 'N/A'}
🚪 <b>Room:</b> {order.room_number or 'N/A'}

📝 <b>Items:</b>
{items_text}

💵 <b>TOTAL:</b> KES {order.total}
⏰ {timezone.localtime(order.created_at).strftime('%I:%M %p, %d %b %Y')}

━━━━━━━━━━━━━━━━━━━━
🔔 Awaiting payment confirmation
        """.strip()

        # ✅ Admin order link
        admin_url = f"{settings.SITE_URL}/admin-panel/liquor/orders/{order.order_number}/"

        # ✅ Inline buttons
        buttons = [
            [
                {"text": "View in Admin", "url": admin_url}
            ]
        ]

        formatted_phone = format_phone(order.phone_number) if order.phone_number else "N/A"
        if order.phone_number:
            wa_url = f"https://wa.me/{formatted_phone.replace('+','')}"
            buttons.append([
                {"text": "WhatsApp Customer", "url": wa_url}
            ])

        # FCM for customer
        if order.user:
            from .tasks import send_lifecycle_notification_task
            send_lifecycle_notification_task.delay(
                order.user.id, 
                "Order Received!", 
                f"Order #{order.order_number} placed.",
                {'order_id': str(order.id), 'type': 'order_placed'}
            )

        # Send to store specific chat if configured
        if order.store and order.store.telegram_chat_id:
            send_telegram_notification(order.store.telegram_chat_id, message)

        # Also send to global admins
        return send_telegram_message(message, buttons=buttons)

    except Exception as e:
        logger.error(f"Error creating order notification: {e}")
        return False


def notify_payment_received(order):
    customer_name = order.user.username if order.user else "N/A"

    message = f"""
✅ <b>PAYMENT CONFIRMED</b>

📦 Order #{order.order_number}
👤 {customer_name}
💰 KES {order.total}

Status: Ready for delivery 🚀
    """.strip()

    if order.user:
        from .tasks import send_lifecycle_notification_task
        send_lifecycle_notification_task.delay(
            order.user.id, 
            "Payment Confirmed!", 
            f"Payment for order #{order.order_number} received.",
            {'order_id': str(order.id), 'type': 'payment_confirmed'}
        )

    if order.store and order.store.telegram_chat_id:
        send_telegram_notification(order.store.telegram_chat_id, message)

    return send_telegram_message(message)


def notify_order_delivered(order):
    customer_name = order.user.username if order.user else "N/A"

    message = f"""
🎉 <b>ORDER DELIVERED</b>

📦 Order #{order.order_number}
👤 {customer_name}
💰 KES {order.total}

Status: Completed ✅
    """.strip()

    if order.user:
        from .tasks import send_lifecycle_notification_task
        send_lifecycle_notification_task.delay(
            order.user.id, 
            "Enjoy!", 
            f"Order #{order.order_number} delivered.",
            {'order_id': str(order.id), 'type': 'order_delivered'}
        )

    if order.store and order.store.telegram_chat_id:
        send_telegram_notification(order.store.telegram_chat_id, message)

    return send_telegram_message(message)

def notify_low_stock(product):
    """Send Telegram alert for a single low stock product"""
    threshold = getattr(product, 'low_stock_threshold', 2)
    message = f"""
⚠️ <b>LOW STOCK ALERT</b>

🍾 <b>{product.name}</b>
📦 Remaining Stock: <b>{product.stock}</b>
🏷️ Threshold: {threshold}
🏷 Category: {product.category.name if hasattr(product, 'category') and hasattr(product.category, 'name') else 'N/A'}

Restock soon!
    """.strip()

    admin_url = f"{settings.SITE_URL}/admin-panel/liquor/menu/"

    buttons = [[{"text": "Restock", "url": admin_url}]]

    # Send to store specific chat if available
    if product.store and product.store.telegram_chat_id:
        send_telegram_notification(product.store.telegram_chat_id, message)

    return send_telegram_message(message, buttons=buttons)


def notify_rider_assigned(order, rider):
    if not rider.telegram_chat_id and not rider.fcm_token:
        return False
        
    message = f"""
🚴 <b>NEW DELIVERY ASSIGNED!</b>

📦 <b>Order #{order.order_number}</b>
━━━━━━━━━━━━━━━━━━━━
👤 <b>Customer:</b> {order.user.username}
🏠 <b>Location:</b> {order.address_string or order.hostel}
🚪 <b>Room:</b> {order.room_number or 'N/A'}
💰 <b>Base Fare:</b> KES {order.rider_base_fare}
💵 <b>Tip:</b> KES {order.tip_amount}

📍 <a href="{order.google_maps_link}">View on Google Maps</a>

Please head to <b>{order.store.name}</b> to pick up.
    """.strip()
    
    # Send FCM
    from .tasks import send_lifecycle_notification_task
    send_lifecycle_notification_task.delay(
        rider.id,
        "New Delivery Assigned!",
        f"New delivery from {order.store.name}.",
        {'order_id': str(order.id), 'type': 'new_assignment'}
    )
    
    if rider.telegram_chat_id:
        return send_telegram_notification(rider.telegram_chat_id, message)
    return True

def notify_superadmin_new_partner(user):
    # Get superadmin chat IDs from settings or environment
    bot_token = getattr(settings, 'TELEGRAM_BOTT_TOKEN', None)
    chat_ids = getattr(settings, 'TELEGRAM_CHATT_IDS', None) or getattr(settings, 'TELEGRAM_CHATT_ID', None)
    
    if isinstance(chat_ids, str):
        chat_ids = [chat_id.strip() for chat_id in chat_ids.split(',') if chat_id.strip()]
    elif not chat_ids:
        return False

    message = f"""
🤝 <b>NEW PARTNER APPLICATION</b>

👤 <b>User:</b> {user.username}
📧 <b>Email:</b> {user.email}
🏢 <b>Business:</b> {user.business_name}
📍 <b>Location:</b> {user.business_location}

Login to admin panel to approve.
    """.strip()
    
    for chat_id in chat_ids:
        send_telegram_notification(chat_id, message)
    return True

def notify_partner_approved(user):
    if not user.telegram_chat_id and not user.phone:
        return False
        
    message = f"""
🎉 <b>CONGRATULATIONS!</b>

Your partner account for <b>{user.business_name}</b> has been approved.

Login to your dashboard to set up your store:
<a href="{settings.SITE_URL}/admin-panel/login/">Merchant Dashboard</a>
    """.strip()
    
    if user.telegram_chat_id:
        send_telegram_notification(user.telegram_chat_id, message)
    # SMS could also be triggered here if configured
    return True

def check_and_notify_low_stock():
    """
    Check all products for low stock and send Telegram alerts.
    This function checks products where stock < low_stock_threshold (default 2).
    Should be called periodically or after order processing.
    """
    from .models import FoodItem
    from django.db import models
    
    # Get all products with stock below their threshold
    low_stock_products = FoodItem.objects.filter(
        stock__gt=0  # Only check products that have stock (ignore out of stock)
    ).filter(
        stock__lt=models.F('low_stock_threshold')
    )
    
    if not low_stock_products.exists():
        logger.info("No low stock products found")
        return False
    
    alert_count = 0
    for product in low_stock_products:
        try:
            notify_low_stock(product)
            alert_count += 1
        except Exception as e:
            logger.error(f"Failed to send low stock alert for {product.name}: {e}")
    
    if alert_count > 0:
        logger.info(f"✅ Sent {alert_count} low stock alerts")
    
    return alert_count > 0

def calculate_risk_score(user, order_data):
    """
    Intelligently calculate a risk score (0-100) for a transaction.
    Factors: Order Value, Location, Behavior Signals.
    """
    score = 0
    
    # 1. Order Value Signal
    total = float(order_data.get('total', 0))
    if total > 20000: # Very High Value (e.g., $150+)
        score += 40
    elif total > 5000: # High Value
        score += 20
        
    # 2. Silent Sentry Signal (Interaction Speed)
    meta = user.verification_metadata or {}
    picker_ms = meta.get('picker_interaction_ms', 5000)
    if picker_ms < 1500: # Suspiciously fast DOB entry
        score += 30
        
    # 3. Location Intelligence (Near High-Risk Areas like Schools)
    # Note: In production, you'd match coords against a DB of schools.
    # For now, we flag specific high-risk area strings.
    address = str(order_data.get('address_string', '')).lower()
    high_risk_keywords = ['school', 'university', 'campus', 'college', 'hostel']
    if any(keyword in address for keyword in high_risk_keywords):
        score += 30
        
    # 4. Account Age
    if (timezone.now() - user.date_joined).days < 1: # Brand new account
        score += 15

    return min(score, 100)

