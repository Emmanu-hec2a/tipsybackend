import requests
import base64
from datetime import datetime
from decimal import Decimal
from django.conf import settings
import os
import logging
from django.core.cache import cache
from cryptography.fernet import Fernet
import json
from django.utils import timezone

logger = logging.getLogger(__name__)

# =========================
# ENCRYPTION UTILS
# =========================
def get_encryption_key():
    """Get encryption key from settings/env. Generates one if missing (NOT FOR PRODUCTION)."""
    key = getattr(settings, 'ENCRYPTION_KEY', os.environ.get('ENCRYPTION_KEY'))
    if not key:
        logger.warning("ENCRYPTION_KEY not found in settings or env. This is insecure for production.")
        # Fallback for development/testing ONLY. 
        return b'6csUuoMhN7dvrad3XaJ5ApYcFPV2AEFtlwSUEAzoREU='
    return key.encode() if isinstance(key, str) else key

def encrypt_value(value):
    if not value: return None
    f = Fernet(get_encryption_key())
    return f.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value):
    if not encrypted_value: return None
    try:
        f = Fernet(get_encryption_key())
        return f.decrypt(encrypted_value.encode()).decode()
    except Exception:
        logger.error("Failed to decrypt M-Pesa credential. Check ENCRYPTION_KEY.")
        return None

# =========================
# EVENT LOGGING
# =========================
def log_mpesa_event(event_type, user_id=None, order_number=None, phone=None, amount=None, extra=None):
    log_data = {
        "event_type": event_type,
        "user_id": user_id,
        "order_number": order_number,
        "phone": f"+2547XXX{phone[-4:]}" if phone else None,
        "amount": float(amount) if amount else None,
        "timestamp": timezone.now().isoformat(),
    }
    if extra:
        log_data.update(extra)
    logger.info(json.dumps(log_data))


class MpesaIntegration:
    """
    Handles M-Pesa Daraja STK Push using store-specific credentials.
    """

    def __init__(self, store=None):
        self.store = store
        if store:
            self.consumer_key = decrypt_value(store.mpesa_consumer_key)
            self.consumer_secret = decrypt_value(store.mpesa_consumer_secret)
            self.passkey = decrypt_value(store.mpesa_passkey)
            self.shortcode = store.mpesa_shortcode
            self.callback_url = store.mpesa_callback_url or os.environ.get('MPESA_CALLBACK_URL')
        else:
            # Fallback to env variables (legacy/default)
            self.consumer_key = os.environ.get('MPESA_CONSUMER_KEY')
            self.consumer_secret = os.environ.get('MPESA_CONSUMER_SECRET')
            self.passkey = os.environ.get('MPESA_PASSKEY')
            self.shortcode = os.environ.get('MPESA_PAYBILL_NUMBER')
            self.callback_url = os.environ.get('MPESA_CALLBACK_URL')

        is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
        self.base_url = (
            'https://api.safaricom.co.ke'
            if is_production
            else 'https://sandbox.safaricom.co.ke'
        )

        self.access_token_url = f'{self.base_url}/oauth/v1/generate?grant_type=client_credentials'
        self.stk_push_url = f'{self.base_url}/mpesa/stkpush/v1/processrequest'
        self.stk_query_url = f'{self.base_url}/mpesa/stkpushquery/v1/query'

    def get_access_token(self):
        # Cache per-store if needed, but for now global cache with store prefix is safer
        cache_key = f'mpesa_token_{self.shortcode}' if self.shortcode else 'mpesa_access_token'
        token = cache.get(cache_key)
        if token:
            return token

        if not self.consumer_key or not self.consumer_secret:
            logger.error(f"Missing M-Pesa credentials for store: {self.store}")
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
            cache.set(cache_key, token, timeout=3500)
            return token
        except Exception:
            logger.exception("Failed to obtain MPESA access token")
            return None

    def generate_password(self, timestamp):
        data_to_encode = f"{self.shortcode}{self.passkey}{timestamp}"
        return base64.b64encode(data_to_encode.encode()).decode()

    def initiate_stk_push(self, phone_number, amount, account_reference, transaction_desc):
        access_token = self.get_access_token()
        if not access_token:
            return {'success': False, 'message': 'Authentication failed'}

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        password = self.generate_password(timestamp)

        # Determine if it's Paybill or Till
        # Simple heuristic: if shortcode is 5-6 digits, likely Paybill. If 7 digits, likely Till.
        # But Daraja API expects BusinessShortCode and PartyB to be the same for STK.
        
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline", # Works for both Paybill and Till in many cases
            "Amount": int(Decimal(str(amount))),
            "PartyA": phone_number,
            "PartyB": self.shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": transaction_desc[:13]
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
                    "checkout_request_id": result.get("CheckoutRequestID"),
                    "customer_message": result.get("CustomerMessage")
                }
            return {
                "success": False,
                "message": result.get("ResponseDescription", "STK push failed")
            }
        except Exception as e:
            logger.exception("STK Push error")
            return {"success": False, "message": str(e)}

    def query_stk_status(self, checkout_request_id):
        access_token = self.get_access_token()
        if not access_token:
            return {'success': False, 'message': 'Authentication failed'}

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        password = self.generate_password(timestamp)

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                self.stk_query_url,
                json=payload,
                headers=headers,
                timeout=20
            )
            response.raise_for_status()
            result = response.json()
            return {
                "success": True,
                "response_code": result.get("ResponseCode"),
                "result_code": result.get("ResultCode"),
                "result_desc": result.get("ResultDesc")
            }
        except Exception:
            logger.exception("STK Query error")
            return {"success": False, "message": "Network error"}

    def format_phone_number(self, phone_number):
        phone = ''.join(filter(str.isdigit, str(phone_number)))
        if phone.startswith('0') and len(phone) == 10:
            return '254' + phone[1:]
        elif phone.startswith('254') and len(phone) == 12:
            return phone
        elif len(phone) == 9:
            return '254' + phone
        else:
            raise ValueError("Invalid phone number format")
