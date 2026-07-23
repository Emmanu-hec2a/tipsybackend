import requests
import base64
from datetime import datetime
from decimal import Decimal
from django.conf import settings
import os
import logging
from django.core.cache import cache
from .models import PlatformConfig
from .mpesa_utils import decrypt_value

logger = logging.getLogger(__name__)

class SubscriptionBilling:
    def __init__(self):
        config = PlatformConfig.objects.first()
        if not config:
            raise ValueError("PlatformConfig not configured. Please set it up in Admin.")
        
        self.config = config
        self.consumer_key = decrypt_value(config.daraja_consumer_key)
        self.consumer_secret = decrypt_value(config.daraja_consumer_secret)
        self.passkey = decrypt_value(config.daraja_passkey)
        self.shortcode = config.daraja_shortcode

        self.is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
        self.base_url = (
            'https://api.safaricom.co.ke'
            if self.is_production
            else 'https://sandbox.safaricom.co.ke'
        )
        self.access_token_url = f'{self.base_url}/oauth/v1/generate?grant_type=client_credentials'
        self.stk_push_url = f'{self.base_url}/mpesa/stkpush/v1/processrequest'

    def get_access_token(self):
        token = cache.get('subscription_mpesa_access_token')
        if token:
            return token

        if not self.consumer_key or not self.consumer_secret:
            logger.error("Missing Platform M-Pesa credentials")
            return None

        try:
            response = requests.get(
                self.access_token_url,
                auth=(self.consumer_key, self.consumer_secret),
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            token = data['access_token']
            cache.set('subscription_mpesa_access_token', token, timeout=3500)
            return token
        except Exception:
            logger.exception("Failed to obtain Subscription MPESA access token")
            return None

    def charge_subscription(self, store, custom_phone=None, amount=None):
        access_token = self.get_access_token()
        if not access_token:
            return {'success': False, 'message': 'Access token error'}

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        data_to_encode = f"{self.shortcode}{self.passkey}{timestamp}"
        password = base64.b64encode(data_to_encode.encode()).decode()

        # Use custom phone if provided, otherwise fallback to store owner's phone
        raw_phone = custom_phone if custom_phone else store.owner.phone
        phone = ''.join(filter(str.isdigit, str(raw_phone)))
        
        if phone.startswith('0') and len(phone) == 10:
            phone = '254' + phone[1:]
        elif not phone.startswith('254'):
            phone = '254' + phone
            
        if len(phone) != 12:
            return {'success': False, 'message': 'Invalid phone number format. Use 07... or 254...'}

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount if amount is not None else store.plan_price),
            "PartyA": phone,
            "PartyB": self.shortcode,
            "PhoneNumber": phone,
            "CallBackURL": f"{settings.SITE_URL}/api/v1/billing/callback/",
            "AccountReference": f"SUB-{store.id}",
            "TransactionDesc": f"{store.name} Monthly Subscription"
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                self.stk_push_url,
                json=payload,
                headers=headers,
                timeout=20
            )
            response.raise_for_status()
            result = response.json()
            if result.get("ResponseCode") == "0":
                return {
                    "success": True,
                    "message": result.get("CustomerMessage", "STK push initiated"),
                    "checkout_request_id": result.get("CheckoutRequestID"),
                }
            return {"success": False, "message": result.get("ResponseDescription")}
        except Exception as e:
            logger.exception("Subscription STK Push failed")
            return {"success": False, "message": str(e)}
