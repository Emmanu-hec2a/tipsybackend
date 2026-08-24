"""
Fraud Detection and Incident Response System for TipsyTheoryy

Purpose:
- Monitor payment transactions for fraudulent patterns
- Detect anomalies in M-Pesa payments, customer behavior, and system activity
- Trigger automatic alerts for suspicious activity
- Enable quick incident response and customer notification

Fraudulent Patterns Detected:
1. Rapid-fire failed payment attempts (brute force)
2. Unusual transaction amounts (3x user's normal average)
3. Unusual geographic/IP patterns
4. Velocity fraud (multiple orders from same card/phone)
5. Test transaction patterns (common fraud probe)
6. Rate limit bypass attempts
7. Callback manipulation attempts
8. Customer account takeover (unusual access patterns)

Implementation:
- Redis-backed pattern storage
- Real-time monitoring via Celery
- Configurable thresholds per merchant/customer type
- Automatic escalation on high-confidence fraud
- Audit trail of all fraud detection triggers
"""

import logging
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q, Sum, Count, Avg
from django.conf import settings

logger = logging.getLogger(__name__)


class FraudPattern:
    """Represents a detected fraud pattern with confidence score"""
    
    def __init__(self, pattern_type: str, confidence: float, details: Dict):
        self.pattern_type = pattern_type
        self.confidence = confidence  # 0.0 - 1.0
        self.details = details
        self.detected_at = timezone.now()
    
    def to_dict(self) -> Dict:
        return {
            'pattern_type': self.pattern_type,
            'confidence': self.confidence,
            'details': self.details,
            'detected_at': self.detected_at.isoformat(),
        }


class FraudDetectionEngine:
    """Real-time fraud detection using multiple pattern matching strategies"""
    
    # Configuration thresholds
    FAILED_ATTEMPT_THRESHOLD = 5  # 5+ failed attempts in 30 minutes
    FAILED_ATTEMPT_WINDOW = 1800  # 30 minutes
    
    VELOCITY_THRESHOLD = 3  # 3+ orders in 5 minutes
    VELOCITY_WINDOW = 300  # 5 minutes
    
    AMOUNT_MULTIPLIER = 3.0  # Amount 3x user's average is suspicious
    
    TEST_AMOUNT_THRESHOLD = Decimal('1.00')  # Test transactions typically $1
    TEST_AMOUNT_WINDOW = 300  # 5 minutes
    
    HIGH_CONFIDENCE_THRESHOLD = 0.75  # Trigger alert if >= 75% confidence
    
    # Cache keys
    FRAUD_CACHE_PREFIX = 'fraud:'
    
    @staticmethod
    def get_cache_key(key_type: str, identifier: str) -> str:
        """Generate consistent cache key for fraud pattern storage"""
        return f"{FraudDetectionEngine.FRAUD_CACHE_PREFIX}{key_type}:{identifier}"
    
    # ═══════════════════════════════════════════════════════════════
    # PATTERN 1: Rapid-Fire Failed Payment Attempts (Brute Force)
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_failed_attempt_velocity(phone_number: str, mpesa_merchant: str = None) -> Optional[FraudPattern]:
        """
        Detect rapid-fire failed payment attempts (brute force attack).
        
        Suspicious if: 5+ failed attempts in 30 minutes
        
        Use Case: Attacker tries multiple payment methods/amounts to find valid payment
        """
        from urbanfoods.models import PaymentAttempt
        
        cache_key = FraudDetectionEngine.get_cache_key('failed_velocity', phone_number)
        
        # Get recent failed attempts
        thirty_min_ago = timezone.now() - timedelta(seconds=FraudDetectionEngine.FAILED_ATTEMPT_WINDOW)
        failed_attempts = PaymentAttempt.objects.filter(
            phone_number=phone_number,
            status__in=['FAILED', 'REJECTED', 'CANCELLED'],
            created_at__gte=thirty_min_ago
        )
        
        if mpesa_merchant:
            failed_attempts = failed_attempts.filter(merchant=mpesa_merchant)
        
        attempt_count = failed_attempts.count()
        
        if attempt_count >= FraudDetectionEngine.FAILED_ATTEMPT_THRESHOLD:
            confidence = min(0.95, 0.5 + (attempt_count * 0.1))
            
            logger.warning(
                f"🚨 FRAUD ALERT: Failed Payment Velocity",
                extra={
                    'pattern': 'failed_attempt_velocity',
                    'phone_number': phone_number,
                    'attempt_count': attempt_count,
                    'confidence': confidence,
                    'window_minutes': FraudDetectionEngine.FAILED_ATTEMPT_WINDOW // 60,
                }
            )
            
            return FraudPattern(
                pattern_type='failed_attempt_velocity',
                confidence=confidence,
                details={
                    'phone_number': phone_number,
                    'attempt_count': attempt_count,
                    'threshold': FraudDetectionEngine.FAILED_ATTEMPT_THRESHOLD,
                    'window_minutes': FraudDetectionEngine.FAILED_ATTEMPT_WINDOW // 60,
                    'reason': 'Multiple failed payment attempts in short time period',
                }
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # PATTERN 2: Unusual Transaction Amount (3x User Average)
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_unusual_transaction_amount(customer_id: str, transaction_amount: Decimal) -> Optional[FraudPattern]:
        """
        Detect unusual transaction amounts compared to user's historical average.
        
        Suspicious if: Amount is 3x user's average transaction
        
        Use Case: Stolen account - attacker places large order
        """
        from urbanfoods.models import Order
        
        # Get user's last 50 orders for average
        recent_orders = Order.objects.filter(
            customer_id=customer_id
        ).order_by('-created_at')[:50]
        
        if not recent_orders:
            # New customer - no baseline, less suspicious
            return None
        
        avg_amount = recent_orders.aggregate(Avg('total_amount'))['total_amount__avg']
        if not avg_amount:
            return None
        
        avg_amount = Decimal(str(avg_amount))
        
        if transaction_amount >= (avg_amount * FraudDetectionEngine.AMOUNT_MULTIPLIER):
            # Amount is 3x+ user's average
            confidence = min(0.85, 0.6 + ((transaction_amount / avg_amount - 1) * 0.1))
            
            logger.warning(
                f"🚨 FRAUD ALERT: Unusual Amount",
                extra={
                    'pattern': 'unusual_amount',
                    'customer_id': customer_id,
                    'amount': float(transaction_amount),
                    'average_amount': float(avg_amount),
                    'multiplier': float(transaction_amount / avg_amount),
                    'confidence': confidence,
                }
            )
            
            return FraudPattern(
                pattern_type='unusual_amount',
                confidence=confidence,
                details={
                    'customer_id': customer_id,
                    'transaction_amount': float(transaction_amount),
                    'average_amount': float(avg_amount),
                    'multiplier': float(transaction_amount / avg_amount),
                    'reason': f'Transaction amount {float(transaction_amount / avg_amount):.1f}x user average',
                }
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # PATTERN 3: Test Transaction Detection (Common Fraud Probe)
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_test_transaction_pattern(phone_number: str, amount: Decimal) -> Optional[FraudPattern]:
        """
        Detect test transaction patterns (common fraud probe technique).
        
        Suspicious if: Multiple $1 transactions from same phone in 5 minutes
        
        Use Case: Fraudster testing stolen payment method before large purchase
        """
        from urbanfoods.models import PaymentAttempt
        
        # Check if amount is typical test amount
        if amount > FraudDetectionEngine.TEST_AMOUNT_THRESHOLD:
            return None  # Not a test amount
        
        # Look for similar test amounts in recent 5 minutes
        five_min_ago = timezone.now() - timedelta(seconds=FraudDetectionEngine.TEST_AMOUNT_WINDOW)
        test_attempts = PaymentAttempt.objects.filter(
            phone_number=phone_number,
            amount__lte=FraudDetectionEngine.TEST_AMOUNT_THRESHOLD,
            created_at__gte=five_min_ago
        ).count()
        
        if test_attempts >= 2:  # Multiple test attempts
            confidence = 0.8
            
            logger.warning(
                f"🚨 FRAUD ALERT: Test Transaction Pattern",
                extra={
                    'pattern': 'test_transaction',
                    'phone_number': phone_number,
                    'test_attempt_count': test_attempts,
                    'confidence': confidence,
                }
            )
            
            return FraudPattern(
                pattern_type='test_transaction',
                confidence=confidence,
                details={
                    'phone_number': phone_number,
                    'test_amount': float(amount),
                    'test_attempt_count': test_attempts,
                    'reason': 'Multiple small test transactions detected',
                }
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # PATTERN 4: Velocity Fraud (Multiple Orders, Short Time)
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_order_velocity(customer_id: str, store_id: str = None) -> Optional[FraudPattern]:
        """
        Detect velocity fraud (multiple orders in short time period).
        
        Suspicious if: 3+ orders in 5 minutes
        
        Use Case: Account takeover - attacker rapidly placing multiple orders
        """
        from urbanfoods.models import Order
        
        five_min_ago = timezone.now() - timedelta(seconds=FraudDetectionEngine.VELOCITY_WINDOW)
        
        recent_orders = Order.objects.filter(
            customer_id=customer_id,
            created_at__gte=five_min_ago
        )
        
        if store_id:
            recent_orders = recent_orders.filter(store_id=store_id)
        
        order_count = recent_orders.count()
        
        if order_count >= FraudDetectionEngine.VELOCITY_THRESHOLD:
            confidence = min(0.9, 0.6 + (order_count * 0.1))
            
            logger.warning(
                f"🚨 FRAUD ALERT: Order Velocity",
                extra={
                    'pattern': 'order_velocity',
                    'customer_id': customer_id,
                    'order_count': order_count,
                    'confidence': confidence,
                }
            )
            
            return FraudPattern(
                pattern_type='order_velocity',
                confidence=confidence,
                details={
                    'customer_id': customer_id,
                    'order_count': order_count,
                    'threshold': FraudDetectionEngine.VELOCITY_THRESHOLD,
                    'window_minutes': FraudDetectionEngine.VELOCITY_WINDOW // 60,
                    'reason': f'{order_count} orders placed in {FraudDetectionEngine.VELOCITY_WINDOW // 60} minutes',
                }
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # PATTERN 5: Geographic Impossibility (IP/Location Anomaly)
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_geographic_anomaly(customer_id: str, current_ip: str, current_city: str = None) -> Optional[FraudPattern]:
        """
        Detect geographic impossibilities (orders from impossible locations).
        
        Suspicious if: Orders from different cities within impossible timeframe
        
        Use Case: Account takeover - attacker accessing from different location
        """
        from urbanfoods.models import Order
        
        # Get last order from this customer
        last_order = Order.objects.filter(
            customer_id=customer_id
        ).order_by('-created_at').first()
        
        if not last_order or not last_order.ip_address:
            return None  # No baseline
        
        # Check if same IP (same location)
        if last_order.ip_address == current_ip:
            return None  # Same location, not suspicious
        
        # If different IP and less than 30 minutes ago - suspicious
        time_since_last_order = timezone.now() - last_order.created_at
        if time_since_last_order.total_seconds() < 1800:  # 30 minutes
            confidence = 0.7
            
            logger.warning(
                f"🚨 FRAUD ALERT: Geographic Anomaly",
                extra={
                    'pattern': 'geographic_anomaly',
                    'customer_id': customer_id,
                    'last_ip': last_order.ip_address,
                    'current_ip': current_ip,
                    'minutes_elapsed': time_since_last_order.total_seconds() / 60,
                    'confidence': confidence,
                }
            )
            
            return FraudPattern(
                pattern_type='geographic_anomaly',
                confidence=confidence,
                details={
                    'customer_id': customer_id,
                    'last_ip': last_order.ip_address,
                    'current_ip': current_ip,
                    'minutes_elapsed': time_since_last_order.total_seconds() / 60,
                    'reason': f'Order from different IP within {int(time_since_last_order.total_seconds() / 60)} minutes',
                }
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # PATTERN 6: Rate Limit Bypass Attempts
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_rate_limit_bypass_attempt(customer_id: str, request_count: int, window_seconds: int) -> Optional[FraudPattern]:
        """
        Detect attempts to bypass rate limiting.
        
        Suspicious if: High request volume despite rate limiting
        
        Use Case: Attacker using multiple accounts/proxies to bypass rate limits
        """
        
        # Rate limit bypass attempts are extremely suspicious
        if request_count > 50:  # More than 50 requests per second?
            confidence = 0.95
            
            logger.warning(
                f"🚨 FRAUD ALERT: Rate Limit Bypass Attempt",
                extra={
                    'pattern': 'rate_limit_bypass',
                    'customer_id': customer_id,
                    'request_count': request_count,
                    'window_seconds': window_seconds,
                    'confidence': confidence,
                }
            )
            
            return FraudPattern(
                pattern_type='rate_limit_bypass',
                confidence=confidence,
                details={
                    'customer_id': customer_id,
                    'request_count': request_count,
                    'requests_per_second': request_count / max(1, window_seconds),
                    'reason': 'Abnormally high request volume detected',
                }
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # PATTERN 7: Callback Manipulation Attempts
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def check_callback_manipulation(
        order_id: str,
        callback_status: str,
        callback_amount: Decimal,
        original_amount: Decimal
    ) -> Optional[FraudPattern]:
        """
        Detect callback manipulation attempts (false payment confirmation).
        
        Suspicious if: Callback amount doesn't match order amount
        
        Use Case: Attacker forging M-Pesa callback to claim payment without paying
        """
        
        if callback_amount != original_amount:
            # Amounts don't match - possible manipulation
            confidence = 0.9
            
            logger.warning(
                f"🚨 FRAUD ALERT: Callback Manipulation",
                extra={
                    'pattern': 'callback_manipulation',
                    'order_id': order_id,
                    'original_amount': float(original_amount),
                    'callback_amount': float(callback_amount),
                    'confidence': confidence,
                }
            )
            
            return FraudPattern(
                pattern_type='callback_manipulation',
                confidence=confidence,
                details={
                    'order_id': order_id,
                    'original_amount': float(original_amount),
                    'callback_amount': float(callback_amount),
                    'difference': float(abs(original_amount - callback_amount)),
                    'reason': 'Callback amount does not match order amount',
                }
            )
        
        return None
    
    # ═══════════════════════════════════════════════════════════════
    # COMPOSITE FRAUD CHECK (Run all patterns)
    # ═══════════════════════════════════════════════════════════════
    
    @staticmethod
    def run_fraud_check(
        customer_id: str,
        phone_number: str,
        transaction_amount: Decimal,
        request_ip: str = None,
        order_id: str = None
    ) -> Tuple[List[FraudPattern], float]:
        """
        Run all fraud detection patterns and return aggregate confidence.
        
        Returns:
            (patterns_detected, aggregate_confidence)
            
            aggregate_confidence = max confidence of any pattern detected
        """
        
        patterns = []
        
        # Pattern 1: Failed attempt velocity
        failed_velocity = FraudDetectionEngine.check_failed_attempt_velocity(phone_number)
        if failed_velocity:
            patterns.append(failed_velocity)
        
        # Pattern 2: Unusual amount
        unusual_amount = FraudDetectionEngine.check_unusual_transaction_amount(customer_id, transaction_amount)
        if unusual_amount:
            patterns.append(unusual_amount)
        
        # Pattern 3: Test transaction
        test_pattern = FraudDetectionEngine.check_test_transaction_pattern(phone_number, transaction_amount)
        if test_pattern:
            patterns.append(test_pattern)
        
        # Pattern 4: Order velocity
        velocity = FraudDetectionEngine.check_order_velocity(customer_id)
        if velocity:
            patterns.append(velocity)
        
        # Pattern 5: Geographic anomaly
        if request_ip:
            geo_anomaly = FraudDetectionEngine.check_geographic_anomaly(customer_id, request_ip)
            if geo_anomaly:
                patterns.append(geo_anomaly)
        
        # Get aggregate confidence
        max_confidence = max([p.confidence for p in patterns]) if patterns else 0.0
        
        # Log all detected patterns
        if patterns:
            logger.info(
                f"🚨 FRAUD CHECK COMPLETE: {len(patterns)} patterns detected",
                extra={
                    'customer_id': customer_id,
                    'patterns': len(patterns),
                    'max_confidence': max_confidence,
                    'patterns_list': [p.pattern_type for p in patterns],
                }
            )
        
        return patterns, max_confidence


# ═══════════════════════════════════════════════════════════════
# FRAUD STORAGE & RETRIEVAL
# ═══════════════════════════════════════════════════════════════

class FraudIncidentStore:
    """Store and retrieve fraud incidents for investigation"""
    
    INCIDENT_TTL = 7 * 24 * 3600  # Keep fraud incidents for 7 days
    
    @staticmethod
    def save_incident(
        pattern: FraudPattern,
        customer_id: str,
        phone_number: str,
        severity: str = 'HIGH'
    ) -> str:
        """Save fraud incident to database for investigation"""
        from urbanfoods.models import FraudIncident
        
        incident = FraudIncident.objects.create(
            pattern_type=pattern.pattern_type,
            confidence=pattern.confidence,
            severity=severity,
            customer_id=customer_id,
            phone_number=phone_number,
            details=json.dumps(pattern.to_dict()),
            status='OPEN'
        )
        
        return str(incident.id)
    
    @staticmethod
    def get_open_incidents(customer_id: str) -> List[Dict]:
        """Get all open fraud incidents for customer"""
        from urbanfoods.models import FraudIncident
        
        incidents = FraudIncident.objects.filter(
            customer_id=customer_id,
            status='OPEN'
        ).order_by('-created_at')
        
        return [
            {
                'id': str(i.id),
                'pattern_type': i.pattern_type,
                'confidence': i.confidence,
                'severity': i.severity,
                'created_at': i.created_at.isoformat(),
                'details': json.loads(i.details) if isinstance(i.details, str) else i.details,
            }
            for i in incidents
        ]


# ═══════════════════════════════════════════════════════════════
# FRAUD INCIDENT MODEL (to add to models.py)
# ═══════════════════════════════════════════════════════════════

"""
class FraudIncident(models.Model):
    '''🚨 Detected fraud incident for investigation and response'''
    
    SEVERITY_CHOICES = (
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    )
    
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('INVESTIGATING', 'Investigating'),
        ('ESCALATED', 'Escalated to Support'),
        ('RESOLVED', 'Resolved'),
        ('FALSE_POSITIVE', 'False Positive'),
    )
    
    # Identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Fraud details
    pattern_type = models.CharField(max_length=50)
    confidence = models.FloatField()  # 0.0 - 1.0
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    
    # Related entities
    customer_id = models.CharField(max_length=255, db_index=True)
    phone_number = models.CharField(max_length=20, db_index=True)
    order_id = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL)
    
    # Investigation
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    details = models.JSONField()  # Pattern details for investigation
    
    # Audit
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    resolution_notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer_id', 'status']),
            models.Index(fields=['created_at', 'severity']),
        ]
    
    def __str__(self):
        return f"[{self.severity}] {self.pattern_type} - {self.customer_id}"
"""
