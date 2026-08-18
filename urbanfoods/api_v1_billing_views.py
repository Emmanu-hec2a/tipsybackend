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
            # 🛡️ ARCHITECTURAL HARDENING: Strict Idempotency & Raw Logging
            payment = SubscriptionPayment.objects.select_for_update().get(
                checkout_request_id=checkout_request_id
            )

            if payment.status == 'success':
                return Response({'status': 'ok', 'payment_status': 'success'})

            payment.result_code = result_code
            payment.result_desc = callback_data.get('ResultDesc', '')
            payment.phone_number = str(metadata.get('PhoneNumber') or payment.phone_number)
            payment.transaction_date = str(metadata.get('TransactionDate') or '')
            payment.mpesa_receipt = metadata.get('MpesaReceiptNumber')
            payment.raw_callback = data # 🛡️ Audit Trail

            if result_code != 0:
                payment.status = 'failed'
                payment.save()
                return Response({'status': 'ok', 'payment_status': 'failed'})

            try:
                raw_amt = metadata.get('Amount')
                received_amount = Decimal(str(raw_amt)) if raw_amt is not None else None
            except (InvalidOperation, TypeError, ValueError):
                received_amount = None

            # 🛡️ HARDENING: Standardized Amount Verification
            if received_amount is None or received_amount < Decimal('1.0'):
                payment.status = 'failed'
                payment.result_desc = f"Invalid Amount: {received_amount}"
                payment.save()
                return Response({'status': 'ok', 'payment_status': 'failed'})

            if received_amount != payment.amount:
                payment.status = 'failed'
                payment.result_desc = f"Amount mismatch: {received_amount} vs {payment.amount}"
                payment.save()
                return Response({'status': 'ok', 'payment_status': 'failed'})

            store = payment.store
            today = timezone.localdate()
            
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

            if payment.payment_type == 'commission' and payment.week_stat:
                week_stat = payment.week_stat
                week_stat.status = 'paid'
                week_stat.save(update_fields=['status'])

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
    except Exception as e:
        logger.exception('Subscription callback processing failed')
        return Response({'status': 'error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PayNowView(PartnerStoreMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

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

            # 🛡️ HARDENING: Prevent overlapping STK pushes
            active_pending = SubscriptionPayment.objects.filter(
                store=store, 
                status='pending',
                created_at__gt=timezone.now() - timedelta(minutes=2)
            ).exists()
            
            if active_pending and not request.data.get('force'):
                return Response({
                    'error': 'A payment is already in progress. Please wait 2 minutes.'
                }, status=status.HTTP_409_CONFLICT)

            from .mpesa_utils import MpesaIntegration
            mpesa = MpesaIntegration()
            formatted_phone = mpesa.format_phone_number(phone or store.owner.phone)

            is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
            stk_amount = int(requested_amount) if is_production else 1
            
            payment = SubscriptionPayment.objects.create(
                store=store,
                amount=stk_amount,
                plan=requested_plan,
                status='pending',
                phone_number=formatted_phone,
            )

            billing = SubscriptionBilling()
            result = billing.charge_subscription(
                store, custom_phone=phone, amount=stk_amount
            )
            
            if result['success']:
                checkout_request_id = result.get('checkout_request_id')
                if not checkout_request_id:
                    payment.status = 'failed'
                    payment.save()
                    return Response({'error': 'No checkout ID'}, status=status.HTTP_502_BAD_GATEWAY)
                
                payment.checkout_request_id = checkout_request_id
                payment.save()
                
                return Response({
                    'status': 'pending',
                    'checkout_request_id': payment.checkout_request_id,
                    'amount': payment.amount,
                })
            
            payment.status = 'failed'
            payment.save()
            return Response({'error': result['message']}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("PayNowView error")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SubscriptionPaymentStatusView(PartnerStoreMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

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
