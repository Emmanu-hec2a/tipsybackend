from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from datetime import date, timedelta
from django.conf import settings
from .models import Store, SubscriptionPayment, Order
from .billing_utils import SubscriptionBilling
from .utils import send_telegram_notification
import hashlib
import hmac
import json
import logging
import uuid
import requests

logger = logging.getLogger(__name__)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def subscription_callback(request):
    """
    Separate callback for subscription payments (Rail 2)
    """
    data = request.data
    # Log the callback for debugging
    logger.info(f"Subscription Callback Received: {data}")
    
    # Check ResultCode from Daraja
    # Note: Structure might vary slightly based on Daraja version, 
    # but usually it's in Body.stkCallback
    callback_data = data.get('Body', {}).get('stkCallback', {})
    result_code = callback_data.get('ResultCode')
    account_ref = callback_data.get('ExternalReference', '') # Fallback or parse from metadata
    
    # AccountReference is typically passed back in Metadata or we use CheckoutRequestID to lookup
    # But as per step 12.3:
    account_ref = data.get('AccountReference', '')
    if not account_ref:
        # Try to find it in the description or other fields if missing
        pass

    try:
        store_id = account_ref.split('-')[1]
        store = Store.objects.get(id=store_id)
        
        if result_code == 0:
            store.subscription_active = True
            store.billing_status = 'active'
            store.subscription_expires = date.today() + timedelta(days=30)
            store.save()
            
            # Extract receipt number if available
            receipt = ""
            for item in callback_data.get('CallbackMetadata', {}).get('Item', []):
                if item.get('Name') == 'MpesaReceiptNumber':
                    receipt = item.get('Value')
            
            SubscriptionPayment.objects.create(
                store=store, 
                amount=store.plan_price, 
                status='success',
                mpesa_receipt=receipt
            )
            
            if store.telegram_chat_id:
                send_telegram_notification(
                    store.telegram_chat_id, 
                    f"✅ *Subscription Renewed*\nYour store *{store.name}* is now active until {store.subscription_expires}."
                )
        else:
            SubscriptionPayment.objects.create(
                store=store, 
                amount=store.plan_price, 
                status='failed'
            )
            if store.telegram_chat_id:
                send_telegram_notification(
                    store.telegram_chat_id, 
                    "❌ *Subscription Payment Failed*\nYour subscription payment for *{store.name}* was not successful. Please try again."
                )
    except (IndexError, Store.DoesNotExist, Exception) as e:
        logger.error(f"Error processing subscription callback: {e}")
        return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({'status': 'ok'})

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def flutterwave_webhook(request):
    """Accept Flutterwave webhook events and mark the related order as paid when confirmed."""
    payload = request.data or {}
    signature = request.headers.get('verif-hash') or request.headers.get('X-Flutterwave-Signature')

    secret = getattr(settings, 'FLUTTERWAVE_WEBHOOK_SECRET', None)
    if secret and signature:
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signature):
            return Response({'detail': 'Invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)

    data = payload.get('data', {}) if isinstance(payload, dict) else {}
    event = payload.get('event') or data.get('status') or ''
    reference = (
        data.get('tx_ref')
        or data.get('reference')
        or payload.get('reference')
        or payload.get('tx_ref')
    )

    if not reference:
        return Response({'detail': 'Reference missing'}, status=status.HTTP_400_BAD_REQUEST)

    order = None
    if isinstance(reference, str):
        order = Order.objects.filter(order_number=reference).first()
        if not order:
            try:
                order = Order.objects.get(id=int(reference))
            except (ValueError, Order.DoesNotExist):
                order = None

    if not order:
        return Response({'detail': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

    if event.lower() in {'charge.completed', 'successful', 'succeeded', 'completed'} or data.get('status') in {'successful', 'succeeded', 'completed'}:
        order.payment_status = 'paid'
        order.payment_completed_at = timezone.now()
        order.payment_failure_reason = ''
        order.save(update_fields=['payment_status', 'payment_completed_at', 'payment_failure_reason', 'updated_at'])
        return Response({'detail': 'Payment confirmed'})

    order.payment_status = 'failed'
    order.payment_failure_reason = str(payload)
    order.save(update_fields=['payment_status', 'payment_failure_reason', 'updated_at'])
    return Response({'detail': 'Payment failed'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def initiate_flutterwave_payment(request):
    """Create a Flutterwave payment link or hosted page for an order."""
    order_id = request.data.get('order_id') or request.data.get('order')
    amount = request.data.get('amount')
    currency = request.data.get('currency') or 'KES'
    email = request.data.get('email') or request.user.email
    name = request.data.get('name') or request.user.get_full_name() or request.user.username

    if not order_id:
        return Response({'detail': 'order_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        order = Order.objects.get(id=order_id, user=request.user)
    except Order.DoesNotExist:
        return Response({'detail': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

    if not amount:
        amount = order.total

    store = order.store
    if not store or not store.flutterwave_enabled:
        return Response({'detail': 'Flutterwave is not enabled for this store'}, status=status.HTTP_400_BAD_REQUEST)

    public_key = store.flutterwave_public_key or getattr(settings, 'FLUTTERWAVE_PUBLIC_KEY', None)
    secret_key = store.flutterwave_secret_key or getattr(settings, 'FLUTTERWAVE_SECRET_KEY', None)
    webhook_secret = store.flutterwave_webhook_secret or getattr(settings, 'FLUTTERWAVE_WEBHOOK_SECRET', None)

    if not public_key or not secret_key:
        return Response({'detail': 'Flutterwave credentials are not configured'}, status=status.HTTP_400_BAD_REQUEST)

    tx_ref = order.order_number or f"tt-{uuid.uuid4().hex[:10]}"
    order.order_number = tx_ref
    order.payment_method = 'flutterwave'
    order.save(update_fields=['order_number', 'payment_method'])

    payload = {
        'tx_ref': tx_ref,
        'amount': str(amount),
        'currency': currency,
        'redirect_url': f"{getattr(settings, 'SITE_URL', 'https://tipsytheoryy.com')}/payments/complete/",
        'customer': {'email': email, 'name': name},
        'customizations': {'title': 'Tipsy Theoryy Checkout', 'description': f'Payment for order {tx_ref}'},
        'meta': {'order_id': str(order.id), 'store_id': str(store.id)},
    }

    headers = {
        'Authorization': f'Bearer {secret_key}',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(
            'https://api.flutterwave.com/v3/charges?type=card',
            headers=headers,
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json().get('data', {})
        payment_url = data.get('link') or data.get('checkout_link') or data.get('payment_url')
        if not payment_url:
            return Response({'detail': 'Flutterwave did not return a payment link'}, status=status.HTTP_502_BAD_GATEWAY_ERROR)
        return Response({
            'payment_url': payment_url,
            'transaction_reference': tx_ref,
            'currency': currency,
            'amount': str(amount),
            'webhook_secret': webhook_secret,
        })
    except requests.RequestException as exc:
        logger.exception('Flutterwave charge initiation failed')
        return Response({'detail': f'Flutterwave request failed: {exc}'}, status=status.HTTP_502_BAD_GATEWAY_ERROR)

class PayNowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        try:
            store = user.store
            billing = SubscriptionBilling()
            result = billing.charge_subscription(store)
            if result['success']:
                return Response({'message': 'STK Push sent to your phone.'})
            return Response({'error': result['message']}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class SubscriptionHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        payments = SubscriptionPayment.objects.filter(store__owner=user).order_by('-created_at')
        data = [{
            'id': p.id,
            'amount': p.amount,
            'status': p.status,
            'receipt': p.mpesa_receipt,
            'date': p.created_at.strftime('%Y-%m-%d %H:%M')
        } for p in payments]
        return Response(data)
