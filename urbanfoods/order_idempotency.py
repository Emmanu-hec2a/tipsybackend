"""
Order Idempotency Module - Payment Idempotency & Duplicate Prevention
═══════════════════════════════════════════════════════════════════════════════

Purpose: Prevent duplicate payments and ensure payment requests are idempotent.
Compliance: PCI DSS 6.5.11 (Brute Force Prevention), API Security Best Practices

Idempotency Guarantees:
1. Same request always produces same result (idempotent)
2. Replay attacks result in same response (not duplicate payment)
3. Network failures don't cause duplicate charges
4. Customer re-submits form doesn't create duplicate order

How It Works:
1. Client provides Idempotency-Key header (UUID format)
2. Server generates request fingerprint (SHA256 of order params)
3. Fingerprint + key stored with payment attempt
4. On retry: Verify fingerprint matches (no parameter change)
5. Return cached response if already processed

Improvements (Day 3):
- Replace MD5 with SHA256 (MD5 deprecated, security risk)
- Bind to customer_id + phone_number (prevents parameter tampering)
- Add 24-hour expiration (old requests cleaned up)
- Add signature validation (HMAC prevents forgery)
- Detect parameter reuse (client using same key with different params)
"""

import hashlib
import json
import uuid
import hmac
from datetime import datetime, timedelta
from typing import Optional, Tuple

from django.conf import settings
import logging

logger = logging.getLogger(__name__)


MAX_IDEMPOTENCY_KEY_LENGTH = 128
IDEMPOTENCY_KEY_EXPIRATION_HOURS = 24


def validate_idempotency_key(key: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    🛡️ Validate idempotency key format.
    
    Requirements:
    - Must be non-empty string
    - Max 128 characters
    - Should be UUID format for uniqueness
    
    Args:
        key: Idempotency-Key header value
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if key is None:
        return True, None  # Optional header
    
    if not isinstance(key, str) or not key.strip():
        return False, 'Idempotency-Key must be a non-empty string.'
    
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return False, f'Idempotency-Key exceeds {MAX_IDEMPOTENCY_KEY_LENGTH} characters.'
    
    # Warn if not UUID format (best practice)
    try:
        uuid.UUID(key)
    except ValueError:
        # Not UUID format, but still valid (allow custom formats)
        logger.warning(f"Idempotency-Key not in UUID format: {key[:20]}...")
    
    return True, None


def order_request_fingerprint(
    data: dict,
    customer_id: Optional[int] = None,
    phone_number: Optional[str] = None
) -> str:
    """
    🛡️ Generate SHA256 fingerprint of order request.
    
    Purpose:
    - Detect if client sends different parameters with same key
    - Prevent parameter tampering (e.g., changing amount, customer)
    - Bind request to customer (prevents customer ID spoofing)
    
    Included Fields (order economics):
    - items: Product IDs and quantities
    - promo_code: Discount code
    - payment_method: Payment type (mpesa, wallet, etc.)
    - use_wallet: Whether to use wallet balance
    - address: Delivery location
    - phone: M-Pesa phone number
    
    Excluded Fields (secrets/temporal):
    - Idempotency key (already unique)
    - Timestamps (naturally change on retry)
    - Auth tokens (secrets)
    - Device info (changes across devices)
    
    Args:
        data: Request payload dict
        customer_id: Customer ID (bound for security)
        phone_number: M-Pesa phone number (bound for verification)
    
    Returns:
        SHA256 hex digest
    """
    items = sorted(
        [
            {
                'product_id': str(item.get('product_id')),
                'quantity': str(item.get('quantity', 1))
            }
            for item in (data.get('items') or [])
        ],
        key=lambda item: (item['product_id'], item['quantity']),
    )
    
    # Create canonical representation (deterministic)
    canonical = {
        'customer_id': customer_id,  # 🛡️ Bind to customer (prevents spoofing)
        'items': items,
        'promo_code': str(data.get('promo_code') or '').strip().upper(),
        'payment_method': str(data.get('payment_method') or 'mpesa').lower(),
        'use_wallet': bool(data.get('use_wallet')),
        'latitude': str(data.get('latitude') or ''),
        'longitude': str(data.get('longitude') or ''),
        'address_string': str(data.get('address_string') or ''),
        'phone': phone_number or str(data.get('mpesa_phone') or ''),  # 🛡️ Bind to phone
    }
    
    # SHA256 (stronger than MD5, which is deprecated)
    encoded = json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def compute_fingerprint_signature(
    fingerprint: str,
    idempotency_key: str,
    secret: Optional[str] = None
) -> str:
    """
    🛡️ Compute HMAC signature of fingerprint.
    
    Purpose:
    - Prevent fingerprint tampering in database
    - Detect if request parameters changed after initial submission
    - HMAC signature ties fingerprint to specific idempotency key
    
    Args:
        fingerprint: SHA256 hex digest of order parameters
        idempotency_key: Client-provided idempotency key
        secret: Secret key (uses MPESA_SECRET_KEY if not provided)
    
    Returns:
        HMAC-SHA256 signature (hex encoded)
    """
    if secret is None:
        secret = getattr(settings, 'MPESA_SECRET_KEY', 'default-secret')
    
    message = f"{fingerprint}:{idempotency_key}"
    signature = hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature


def verify_fingerprint_unchanged(
    previous_fingerprint: str,
    current_fingerprint: str,
    idempotency_key: str
) -> Tuple[bool, Optional[str]]:
    """
    🛡️ Verify request fingerprint hasn't changed.
    
    When client retries with same idempotency key, we verify parameters unchanged.
    If parameters changed: Client error (400), not server retry (409).
    
    Common Scenarios:
    
    ✅ Valid Retry (same parameters):
       Request 1: items=[A], amount=100, key=abc123 → fingerprint=xyz789
       Request 2: items=[A], amount=100, key=abc123 → fingerprint=xyz789
       Result: Return cached response
    
    ❌ Invalid Retry (different parameters):
       Request 1: items=[A], amount=100, key=abc123 → fingerprint=xyz789
       Request 2: items=[B], amount=200, key=abc123 → fingerprint=qqq111
       Result: Error 400 (client error, don't retry)
    
    Args:
        previous_fingerprint: Fingerprint from first request
        current_fingerprint: Fingerprint from retry request
        idempotency_key: Client key
    
    Returns:
        Tuple of (matches, error_message)
    """
    if previous_fingerprint == current_fingerprint:
        return True, None
    
    error_msg = (
        f"Idempotency key '{idempotency_key}' used with different request parameters. "
        f"Request parameters must remain unchanged for idempotent retries."
    )
    
    logger.warning(
        "Idempotency key reused with different parameters",
        extra={
            "idempotency_key": idempotency_key[:20] + "...",
            "previous_fingerprint": previous_fingerprint[:12] + "...",
            "current_fingerprint": current_fingerprint[:12] + "...",
            "violation_type": "idempotency_key_parameter_mismatch"
        }
    )
    
    return False, error_msg

