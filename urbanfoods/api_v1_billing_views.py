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
import json
import logging

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
    callback_data = data.get('Body', {}).get('stkCallback', {})
    result_code = callback_data.get('ResultCode')
    
    # AccountReference is typically passed back in Metadata or we use CheckoutRequestID to lookup
    account_ref = data.get('AccountReference', '')

    try:
        # Expected format: SUB-123
        store_id = account_ref.split('-')[1]
        store = Store.objects.get(id=store_id)
        
        if result_code == 0:
            store.billing_status = 'active'
            store.is_active = True # Reactivate store upon successful payment
            store.subscription_expires = date.today() + timedelta(days=30)
            
            # Synchronize is_pro based on the plan
            if store.plan == 'pro':
                store.is_pro = True
            elif store.plan == 'base':
                store.is_pro = False

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

class PayNowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        phone = request.data.get('phone')
        new_plan = request.data.get('plan') # 'base', 'pro', or 'custom'
        
        try:
            store = user.store
            
            # If a new plan is requested, update the store's plan and price temporarily
            # but don't mark it as active yet. The callback will handle the activation.
            if new_plan and new_plan in ['base', 'pro', 'custom']:
                store.plan = new_plan
                # Update price based on plan if necessary
                if new_plan == 'base':
                    store.plan_price = 5000
                elif new_plan == 'pro':
                    store.plan_price = 15000
                store.save()

            billing = SubscriptionBilling()
            # Pass the custom phone number if provided, otherwise it will default to owner's phone
            result = billing.charge_subscription(store, custom_phone=phone)
            
            if result['success']:
                return Response({'message': 'STK Push sent. Once paid, your plan will be updated.'})
            return Response({'error': result['message']}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("PayNowView error")
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
