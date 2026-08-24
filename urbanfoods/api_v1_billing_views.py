from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from django.utils import timezone
from datetime import date, timedelta
from django.conf import settings
from django.db import transaction
from decimal import Decimal, InvalidOperation
from .models import Store, SubscriptionPayment, Order, PaymentAttempt
from .api_v1_partner_views import PartnerStoreMixin
from .billing_utils import SubscriptionBilling
from .payment_initiation import InitiatePaymentService, PaymentInitiationConflict
from .payment_throttles import PaymentAttemptThrottle
from .views import safaricom_ip_required
from django.views.decorators.csrf import csrf_exempt
import json
import logging
import os
import os

logger = logging.getLogger(__name__)

@csrf_exempt
@safaricom_ip_required
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def subscription_callback(request):
    data = request.data
    callback_data = data.get('Body', {}).get('stkCallback', {})
    checkout_request_id = callback_data.get('CheckoutRequestID')
    from .observability import increment_metric, log_payment_event
    increment_metric('payment_callback_received_total')
    if not checkout_request_id:
        increment_metric('payment_unmatched_total')
        return Response({'status': 'ignored'}, status=status.HTTP_200_OK)

    result_code = callback_data.get('ResultCode')
    try:
        result_code = int(result_code)
    except (TypeError, ValueError):
        result_code = -1

    metadata = {
        item.get('Name'): item.get('Value')
        for item in callback_data.get('CallbackMetadata', {}).get('Item', [])
    }

    from .payment_service import ConfirmPaymentService
    success = ConfirmPaymentService.process_payment_signal(
        checkout_request_id=checkout_request_id,
        result_code=result_code,
        result_desc=callback_data.get('ResultDesc', ''),
        metadata=metadata,
        source='billing_callback'
    )
    increment_metric('payment_callback_processing_total')
    log_payment_event('payment_callback_processed', source='billing_callback',
                      checkout_request_id=checkout_request_id[-6:], success=success)
    
    return Response({'status': 'ok', 'success': success})

class PayNowView(PartnerStoreMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment_initiation'

    def post(self, request):
        phone = request.data.get('phone')
        new_plan = request.data.get('plan')
        
        try:
            store = self.get_store(request)
            if not store:
                return Response({'error': 'No store associated'}, status=status.HTTP_400_BAD_REQUEST)
            
            requested_plan = new_plan if new_plan in ['base', 'pro', 'custom'] else store.plan
            requested_amount = {
                'base': Decimal('3000.00'),
                'pro': Decimal('5000.00'),
            }.get(requested_plan, store.plan_price)
            key = request.headers.get('Idempotency-Key') or request.data.get('idempotency_key')
            existing = SubscriptionPayment.objects.filter(payment_idempotency_key=key).first() if key else None
            if existing:
                payment = existing
                attempt, _ = InitiatePaymentService.create_or_get_for_subscription(payment, payment.phone_number, key)
                return Response({'status': attempt.status, 'payment_id': str(attempt.public_payment_id),
                                 'checkout_request_id': attempt.checkout_request_id, 'amount': payment.amount,
                                 'idempotency_key': attempt.idempotency_key, 'is_async': True})

            # 🛡️ HARDENING: Prevent overlapping STK pushes
            active_pending = SubscriptionPayment.objects.filter(
                store=store, 
                status='pending',
                created_at__gt=timezone.now() - timedelta(minutes=2)
            ).order_by('-created_at').first()
            
            if active_pending and not request.data.get('force'):
                active_attempt = PaymentAttempt.objects.filter(
                    subscription_payment=active_pending,
                    status__in=[PaymentAttempt.Status.INITIATING, PaymentAttempt.Status.PENDING],
                ).order_by('-created_at').first()
                return Response({
                    'error': 'A payment is already in progress. Please wait 2 minutes.',
                    'payment_id': str(active_attempt.public_payment_id) if active_attempt else None,
                    'checkout_request_id': active_attempt.checkout_request_id if active_attempt else active_pending.checkout_request_id,
                    'status': active_attempt.status if active_attempt else active_pending.status,
                    'amount': active_attempt.expected_amount if active_attempt else active_pending.amount,
                }, status=status.HTTP_409_CONFLICT)

            from .mpesa_utils import MpesaIntegration
            formatted_phone = MpesaIntegration().format_phone_number(phone or store.owner.phone)
            if not existing:
                is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
                stk_amount = int(requested_amount) if is_production else 1
                payment = SubscriptionPayment.objects.create(
                    store=store,
                    amount=stk_amount,
                    plan=requested_plan,
                    status='pending',
                    phone_number=formatted_phone,
                    payment_idempotency_key=key,
                )

            attempt, _ = InitiatePaymentService.create_or_get_for_subscription(payment, formatted_phone, key)
            return Response({
                'status': attempt.status,
                'payment_id': str(attempt.public_payment_id),
                'checkout_request_id': attempt.checkout_request_id,
                'amount': payment.amount,
                'idempotency_key': attempt.idempotency_key,
                'is_async': True,
            })
        except PaymentInitiationConflict as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        except Exception as e:
            logger.exception("PayNowView error")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SubscriptionPaymentStatusView(PartnerStoreMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment_status'

    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_400_BAD_REQUEST)

        checkout_request_id = request.query_params.get('checkout_request_id')
        payment = SubscriptionPayment.objects.filter(store=store)
        if checkout_request_id:
            payment = payment.filter(checkout_request_id=checkout_request_id)
        payment = payment.order_by('-created_at').first()
        if not payment:
            return Response({'payment_status': None})

        return Response({
            'payment_status': payment.status,
            'checkout_request_id': payment.checkout_request_id,
            'amount': payment.amount,
        })


class PartnerPaymentAttemptStatusView(PartnerStoreMixin, APIView):
    """Authoritative status for a merchant-owned subscription/commission attempt."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle, PaymentAttemptThrottle]
    throttle_scope = 'payment_status'

    def get(self, request, payment_id):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_400_BAD_REQUEST)

        attempt = PaymentAttempt.objects.select_related('subscription_payment').filter(
            public_payment_id=payment_id,
            subscription_payment__store=store,
        ).first()
        if not attempt:
            return Response({'error': 'Payment attempt not found'}, status=status.HTTP_404_NOT_FOUND)

        target = attempt.subscription_payment
        return Response({
            'payment_id': str(attempt.public_payment_id),
            'payment_type': attempt.payment_type,
            'status': attempt.status,
            'payment_status': attempt.status,
            'checkout_request_id': attempt.checkout_request_id,
            'amount': str(attempt.expected_amount),
            'currency': attempt.currency,
            'receipt': attempt.provider_receipt or target.mpesa_receipt,
            'provider_receipt': attempt.provider_receipt or target.mpesa_receipt,
            'failure_code': attempt.failure_code,
            'failure_message': attempt.failure_message or attempt.manual_review_reason,
            'manual_review_reason': attempt.manual_review_reason,
            'created_at': attempt.created_at.isoformat(),
            'updated_at': (attempt.confirmed_at or attempt.failed_at or attempt.expired_at or attempt.created_at).isoformat(),
        })

class SubscriptionHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        payments = SubscriptionPayment.objects.filter(store__owner=user).order_by('-created_at')
        data = [{
            'id': p.id,
            'amount': str(p.amount),
            'status': p.status,
            'mpesa_receipt': p.mpesa_receipt,
            'created_at': p.created_at.isoformat()
        } for p in payments]
        return Response(data)

class DowngradeToFreeView(PartnerStoreMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=400)
            
        store.plan = 'free'
        store.plan_price = Decimal('0.00')
        store.is_pro = False
        store.billing_status = 'active'
        store.subscription_expires = timezone.now().date()
        store.save()
        
        return Response({'success': True})
