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
from urbanfoods.tls_pinning import create_safaricom_session
from urbanfoods.secrets_manager import get_hybrid_credential_store
from urbanfoods.phone_validation import PhoneNumberValidator

logger = logging.getLogger(__name__)

# =========================
# ENCRYPTION UTILS
# =========================
def get_encryption_key():
    """Return the configured Fernet key; never use a predictable fallback."""
    from django.conf import settings
    key = getattr(settings, 'ENCRYPTION_KEY', os.environ.get('ENCRYPTION_KEY'))
    if not key:
        raise RuntimeError('ENCRYPTION_KEY is required to access payment credentials.')
    
    # Ensure it's bytes
    if isinstance(key, str):
        # Clean up any quotes or whitespace
        key = key.strip().strip("'").strip('"')
        return key.encode()
    return key

def encrypt_value(value):
    if not value: return None
    f = Fernet(get_encryption_key())
    return f.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value):
    if not encrypted_value: return None
    key = get_encryption_key()
    try:
        f = Fernet(key)
        return f.decrypt(encrypted_value.encode()).decode()
    except Exception as e:
        # Use more descriptive exception logging
        from cryptography.fernet import InvalidToken
        if isinstance(e, InvalidToken):
            logger.error("Failed to decrypt M-Pesa credential: Invalid Token (Wrong ENCRYPTION_KEY?)")
        else:
            logger.error(f"Failed to decrypt M-Pesa credential. Error Type: {type(e).__name__}")
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
    
    🛡️ PCI DSS Requirement 3.2.1: Credentials stored in AWS Secrets Manager with key rotation
    🛡️ PCI DSS Requirement 4.1: All API calls to M-Pesa use TLS certificate pinning
    """

    def __init__(self, store=None):
        self.store = store
        
        # 🛡️ PCI DSS: Use AWS Secrets Manager for credential storage (hybrid fallback to DB)
        credential_store = get_hybrid_credential_store()
        
        if store:
            # Try to get credentials from Secrets Manager or database
            creds = credential_store.get_credentials(store.id)
            if creds:
                self.consumer_key = creds['consumer_key']
                self.consumer_secret = creds['consumer_secret']
                self.passkey = creds['passkey']
                self.shortcode = creds.get('shortcode', store.mpesa_shortcode)
            else:
                # Fallback to encrypted fields on store model
                self.consumer_key = decrypt_value(store.mpesa_consumer_key)
                self.consumer_secret = decrypt_value(store.mpesa_consumer_secret)
                self.passkey = decrypt_value(store.mpesa_passkey)
                self.shortcode = store.mpesa_shortcode
                
            self.callback_url = store.mpesa_callback_url or os.environ.get('MPESA_CALLBACK_URL')
        else:
            # Fallback to env variables (legacy/default) - NOT RECOMMENDED FOR PRODUCTION
            self.consumer_key = os.environ.get('MPESA_CONSUMER_KEY')
            self.consumer_secret = os.environ.get('MPESA_CONSUMER_SECRET')
            self.passkey = os.environ.get('MPESA_PASSKEY')
            self.shortcode = os.environ.get('MPESA_PAYBILL_NUMBER')
            self.callback_url = os.environ.get('MPESA_CALLBACK_URL')

        # Store production flag for certificate pinning configuration
        self.is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
        
        self.base_url = (
            'https://api.safaricom.co.ke'
            if self.is_production
            else 'https://sandbox.safaricom.co.ke'
        )

        self.access_token_url = f'{self.base_url}/oauth/v1/generate?grant_type=client_credentials'
        self.stk_push_url = f'{self.base_url}/mpesa/stkpush/v1/processrequest'
        self.stk_query_url = f'{self.base_url}/mpesa/stkpushquery/v1/query'

    def get_access_token(self, force_refresh=False):
        # Cache per-store if needed, but for now global cache with store prefix is safer
        cache_key = f'mpesa_token_{self.shortcode}' if self.shortcode else 'mpesa_access_token'
        
        if not force_refresh:
            try:
                token = cache.get(cache_key)
                if token:
                    return token
            except Exception as cache_err:
                logger.warning(f"Cache access failed (Redis down?): {cache_err}")

        if not self.consumer_key or not self.consumer_secret:
            logger.error(f"Missing or invalid M-Pesa credentials for store: {self.store}")
            return None

        try:
            logger.info(f"Fetching fresh M-Pesa token from Safaricom. Store={self.store}")
            
            # 🛡️ PCI DSS: Use certificate-pinned session for all M-Pesa API calls
            with create_safaricom_session(is_production=self.is_production) as session:
                response = session.get(
                    self.access_token_url,
                    auth=(self.consumer_key, self.consumer_secret),
                    timeout=15
                )
            
            if response.status_code != 200:
                logger.error("M-Pesa Auth Failed (Status %s)", response.status_code)
                return None
                
            data = response.json()
            token = data.get('access_token')
            if token:
                try:
                    cache.set(cache_key, token, timeout=3500)
                except Exception:
                    pass
                return token
            else:
                logger.error("M-Pesa Auth Response missing access_token")
                return None
        except Exception:
            logger.exception("Failed to obtain MPESA access token")
            return None

    def generate_password(self, timestamp):
        data_to_encode = f"{self.shortcode}{self.passkey}{timestamp}"
        return base64.b64encode(data_to_encode.encode()).decode()

    def initiate_stk_push(self, phone_number, amount, account_reference, transaction_desc, _retrying=False):
        access_token = self.get_access_token()
        if not access_token:
            return {'success': False, 'message': 'Authentication failed'}

        # 🛡️ PCI DSS: Format phone to E.164 for M-Pesa API (+254XXXXXXXXX)
        try:
            formatted_phone = self.format_phone_number(phone_number)
            logger.info(f"✅ Phone formatted: {phone_number} → {formatted_phone}")
        except ValueError as e:
            logger.error(f"Phone format error for STK push: {e}")
            return {'success': False, 'message': f'Invalid phone number: {e}'}

        # Daraja API expects MSISDN without the leading "+" (e.g. 254712345678)
        daraja_phone = formatted_phone.lstrip('+')

        # 🛡️ Safaricom expects a specific timestamp format in Nairobi time (EAT)
        timestamp = timezone.localtime(timezone.now()).strftime('%Y%m%d%H%M%S')
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
            "PartyA": daraja_phone,
            "PartyB": self.shortcode,
            "PhoneNumber": daraja_phone,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": transaction_desc[:13]
        }
        logger.info(f"STK Push Payload: PartyA={daraja_phone}, BusinessShortCode={self.shortcode}, Amount={int(Decimal(str(amount)))}")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        try:
            # 🛡️ PCI DSS: Use certificate-pinned session for all M-Pesa API calls
            with create_safaricom_session(is_production=self.is_production) as session:
                response = session.post(
                    self.stk_push_url,
                    json=payload,
                    headers=headers,
                    timeout=20
                )
            
            # 🛡️ Task: Detect stale token (401) and retry once
            if response.status_code == 401 or (response.status_code >= 400 and 'invalid' in response.text.lower() and 'token' in response.text.lower()):
                if not _retrying:
                    logger.warning(f"STK push for Store {self.store} rejected — possible stale token, clearing cache and retrying once")
                    self.get_access_token(force_refresh=True)
                    return self.initiate_stk_push(phone_number, amount, account_reference, transaction_desc, _retrying=True)
                return {'success': False, 'message': 'M-Pesa authentication failed after retry'}

            # 🛡️ DEBUGGING: Capture other 400+ errors
            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    logger.error("Daraja STK Error %s: %s", response.status_code, error_data.get('errorCode', 'provider_error'))
                    
                    # 🛡️ Task: Notify failure if it's a known non-retryable error
                    # We can't easily notify user here because we don't have user_id, 
                    # but we return it to the task which DOES have it.
                    return {
                        "success": False, 
                        "message": error_data.get('errorMessage', 'M-Pesa rejected the request'),
                        "error_code": error_data.get('errorCode')
                    }
                except:
                    logger.error("Daraja STK Raw Error %s", response.status_code)
                    return {"success": False, "message": "M-Pesa service error"}

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
            logger.exception(f"Critical STK Push Exception: {e}")
            return {"success": False, "message": "Connection to M-Pesa failed"}

    def query_stk_status(self, checkout_request_id):
        access_token = self.get_access_token()
        if not access_token:
            return {'success': False, 'message': 'Authentication failed'}

        timestamp = timezone.localtime(timezone.now()).strftime('%Y%m%d%H%M%S')
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
            # 🛡️ PCI DSS: Use certificate-pinned session for all M-Pesa API calls
            with create_safaricom_session(is_production=self.is_production) as session:
                response = session.post(
                    self.stk_query_url,
                    json=payload,
                    headers=headers,
                    timeout=20
                )
                response.raise_for_status()
                result = response.json()
            
            # 🛡️ Hardening: Extract structured metadata to match Callback format
            # This allows the PaymentService to treat both identical.
            return {
                "success": True,
                "response_code": result.get("ResponseCode"),
                "result_code": int(result.get("ResultCode", -1)),
                "result_desc": result.get("ResultDesc"),
                "metadata": {
                    "Amount": result.get("Amount"),
                    "MpesaReceiptNumber": result.get("MpesaReceiptNumber"),
                    "PhoneNumber": result.get("PhoneNumber"),
                    "TransactionDate": result.get("TransactionDate"),
                }
            }
        except Exception:
            logger.exception("STK Query error")
            return {"success": False, "message": "Network error"}

    def format_phone_number(self, phone_number):
        """
        Validate and normalize phone number to E.164 format.
        
        🛡️ PCI DSS 12.3: Validates against Kenya-specific E.164 format to prevent spoofing
        
        Args:
            phone_number: Phone number in any Kenya format
        
        Returns:
            Normalized phone number in E.164 format (+254XXXXXXXXX)
        
        Raises:
            ValueError: If phone number is invalid
        """
        normalized = PhoneNumberValidator.normalize_format(phone_number)
        if not normalized:
            is_valid, error = PhoneNumberValidator.validate_format(phone_number)
            raise ValueError(error or "Invalid phone number format")
        return normalized
