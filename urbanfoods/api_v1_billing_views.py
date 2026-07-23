from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from datetime import date, timedelta
from django.conf import settings
from django.db import transaction
from decimal import Decimal, InvalidOperation
from .models import Store, SubscriptionPayment, Order
from .api_v1_partner_views import PartnerStoreMixin
from .billing_utils import SubscriptionBilling
from .views import safaricom_ip_required
import json
import logging

logger = logging.getLogger(__name__)

@safaricom_ip_required
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def subscription_callback(request):
    data = request.data
    callback_data = data.get('Body', {}).get('stkCallback', {})
    checkout_request_id = callback_data.get('CheckoutRequestID')
    if not checkout_request_id:
        return Response({'status': 'ignored', 'message': 'CheckoutRequestID missing'}, status=status.HTTP_200_OK)

    result_code = callback_data.get('ResultCode')
    try:
        result_code = int(result_code)
    except (TypeError, ValueError):
        result_code = -1

    metadata = {
        item.get('Name'): item.get('Value')
        for item in callback_data.get('CallbackMetadata', {}).get('Item', [])
    }

    try:
        with transaction.atomic():
            payment = SubscriptionPayment.objects.select_for_update().select_related('store').get(
                checkout_request_id=checkout_request_id
            )

            if payment.status == 'success':
                return Response({'status': 'ok', 'payment_status': 'success'})

            payment.result_code = result_code
            payment.result_desc = callback_data.get('ResultDesc', '')
            payment.phone_number = str(metadata.get('PhoneNumber') or payment.phone_number)
            payment.transaction_date = str(metadata.get('TransactionDate') or '')
            payment.mpesa_receipt = metadata.get('MpesaReceiptNumber')
            payment.raw_callback = data

            if result_code != 0:
                payment.status = 'failed'
                payment.save()
                return Response({'status': 'ok', 'payment_status': 'failed'})

            try:
                # Support Decimal conversion safely
                raw_amt = metadata.get('Amount')
                received_amount = Decimal(str(raw_amt)) if raw_amt is not None else None
            except (InvalidOperation, TypeError, ValueError):
                received_amount = None

            # 🛡️ Amount Validation (Crucial for Revenue Integrity)
            # In sandbox (is_production=False), allow 1.0 for testing, else strict match
            is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
            is_valid_amount = (received_amount == payment.amount) or (not is_production and received_amount == Decimal('1.0'))

            if received_amount is None or not is_valid_amount:
                payment.status = 'failed'
                payment.result_desc = (
                    f"Amount mismatch: received {received_amount}, expected {payment.amount}"
                )
                payment.save()
                logger.warning(f"Subscription amount mismatch for store {payment.store.id}. Rec: {received_amount}")
                return Response({'status': 'ok', 'payment_status': 'failed'})

            store = payment.store
            today = timezone.localdate()
            
            # 🛡️ Smart Renewal Logic: Extend from existing expiry if it hasn't passed yet
            current_expiry = store.subscription_expires
            base_date = current_expiry if (current_expiry and current_expiry > today) else today

            store.billing_status = 'active'
            store.is_active = True
            store.subscription_expires = base_date + timedelta(days=30)
            if payment.plan:
                store.plan = payment.plan
                store.plan_price = payment.amount
                store.is_pro = payment.plan == 'pro'
            store.last_payment_date = today
            store.save(update_fields=[
                'billing_status', 'is_active', 'subscription_expires',
                'plan', 'plan_price', 'is_pro', 'last_payment_date'
            ])

            payment.status = 'success'
            payment.save()

        if store.telegram_chat_id:
            from .tasks import send_telegram_notification_task
            send_telegram_notification_task.delay(
                store.telegram_chat_id,
                f"✅ *Subscription Renewed*\nYour store *{store.name}* is active until {store.subscription_expires}."
            )
        return Response({'status': 'ok', 'payment_status': 'success'})
    except SubscriptionPayment.DoesNotExist:
        logger.warning('Unknown subscription CheckoutRequestID: %s', checkout_request_id)
        return Response({'status': 'ignored'}, status=status.HTTP_200_OK)
    except Exception:
        logger.exception('Subscription callback processing failed')
        return Response({'status': 'error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PayNowView(PartnerStoreMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        phone = request.data.get('phone')
        new_plan = request.data.get('plan') # 'base', 'pro', or 'custom'
        
        try:
            # Safely check for store using mixin
            store = self.get_store(request)
            if not store:
                return Response({'error': 'No store associated with this account. Please create a store first.'}, status=status.HTTP_400_BAD_REQUEST)
            
            requested_plan = new_plan if new_plan in ['base', 'pro', 'custom'] else store.plan
            requested_amount = {
                'base': Decimal('3000.00'),
                'pro': Decimal('5000.00'),
            }.get(requested_plan, store.plan_price)
            retry_requested = request.data.get('retry') in [True, 'true', '1', 1]

            # Do not create overlapping charge attempts for the same store.
            existing = SubscriptionPayment.objects.filter(
                store=store, status='pending'
            ).order_by('-created_at').first()
            
            if existing:
                # If the existing one is more than 15 minutes old, mark it as failed so we can retry
                if timezone.now() - existing.created_at > timedelta(minutes=15):
                    existing.status = 'failed'
                    existing.result_desc = 'Timed out (Pending for >15 mins)'
                    existing.save(update_fields=['status', 'result_desc'])
                elif not retry_requested:
                    return Response({
                        'status': 'pending',
                        'payment_status': 'pending',
                        'checkout_request_id': existing.checkout_request_id,
                        'amount': existing.amount,
                    })

            from .mpesa_utils import MpesaIntegration
            mpesa = MpesaIntegration()
            formatted_phone = mpesa.format_phone_number(phone or store.owner.phone)
            
            # 1. Create PRE-INITIATED record (Hardens correlation)
            payment = SubscriptionPayment.objects.create(
                store=store,
                amount=requested_amount,
                plan=requested_plan,
                status='pending',
                phone_number=formatted_phone,
            )

            billing = SubscriptionBilling()
            result = billing.charge_subscription(
                store, custom_phone=phone, amount=requested_amount
            )
            
            if result['success']:
                checkout_request_id = result.get('checkout_request_id')
                if not checkout_request_id:
                    payment.status = 'failed'
                    payment.result_desc = 'M-PESA did not return a checkout request ID.'
                    payment.save(update_fields=['status', 'result_desc'])
                    return Response({'error': 'M-PESA did not return a checkout request ID.'}, status=status.HTTP_502_BAD_GATEWAY)
                
                # 2. Bind the checkout_request_id immediately
                payment.checkout_request_id = checkout_request_id
                payment.save(update_fields=['checkout_request_id'])
                
                return Response({
                    'status': 'pending',
                    'payment_status': payment.status,
                    'checkout_request_id': payment.checkout_request_id,
                    'amount': payment.amount,
                    'message': result['message'],
                })
            
            # Handle Initiation Failure
            payment.status = 'failed'
            payment.result_desc = result.get('message', 'M-PESA STK push failed')
            payment.save(update_fields=['status', 'result_desc'])
            return Response({'error': result['message']}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("PayNowView error")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SubscriptionPaymentStatusView(PartnerStoreMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated with this account.'}, status=status.HTTP_400_BAD_REQUEST)

        checkout_request_id = request.query_params.get('checkout_request_id')
        payment = SubscriptionPayment.objects.filter(store=store)
        if checkout_request_id:
            payment = payment.filter(checkout_request_id=checkout_request_id)
        payment = payment.order_by('-created_at').first()
        if not payment:
            return Response({'payment_status': None, 'subscription_expires': store.subscription_expires})

        return Response({
            'payment_status': payment.status,
            'checkout_request_id': payment.checkout_request_id,
            'amount': payment.amount,
            'subscription_expires': store.subscription_expires,
            'billing_status': store.billing_status,
        })

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
