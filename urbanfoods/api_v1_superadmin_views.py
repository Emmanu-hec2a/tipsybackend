from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404
from .models import Store, User, Order, WeeklyRevenueStat
from .api_v1_serializers import StoreSerializer, UserSerializer, OrderSerializer
from .permissions import IsSuperAdmin

class SuperAdminBaseView:
    permission_classes = [IsSuperAdmin]

class StoreListView(SuperAdminBaseView, APIView):
    def get(self, request):
        stores = Store.objects.all().order_by('-created_at')
        # Strict pricing synchronization for Admin visibility
        for s in stores:
            if s.plan == 'base':
                s.plan_price = 3000
            elif s.plan == 'pro':
                s.plan_price = 5000

        serializer = StoreSerializer(stores, many=True)
        return Response(serializer.data)

class StoreDetailView(SuperAdminBaseView, APIView):
    def get(self, request, pk):
        try:
            store = Store.objects.get(pk=pk)
            serializer = StoreSerializer(store)
            return Response(serializer.data)
        except Store.DoesNotExist:
            return Response({'error': 'Store not found'}, status=status.HTTP_404_NOT_FOUND)

class PartnerApproveView(SuperAdminBaseView, APIView):
    def post(self, request, pk):
        try:
            partner = User.objects.get(pk=pk, role='partner')
            partner.is_approved = True
            partner.save()
            
            # Create store if it doesn't exist
            store = partner.stores.first()
            if not store:
                store = Store.objects.create(
                    owner=partner,
                    name=partner.business_name or f"{partner.username}'s Store",
                    is_active=True,
                    latitude=0,
                    longitude=0
                )
            else:
                store.is_active = True
                store.save()
            
            if partner.telegram_chat_id:
                from .tasks import send_telegram_notification_task
                send_telegram_notification_task.delay(
                    partner.telegram_chat_id,
                    f"🎉 <b>Approved!</b>\nYour store <b>{store.name}</b> is now live on TipsyTheoryy."
                )
                
            return Response({
                'message': f'Partner {partner.username} approved',
                'store_id': store.id
            })
        except User.DoesNotExist:
            return Response({'error': 'Partner not found'}, status=status.HTTP_404_NOT_FOUND)

class PartnerSuspendView(SuperAdminBaseView, APIView):
    def post(self, request, pk):
        try:
            partner = User.objects.get(pk=pk, role='partner')
            partner.is_approved = False
            partner.save()
            
            # Deactivate all associated stores
            for s in partner.stores.all():
                s.is_active = False
                s.save()
                
            return Response({'message': f'Partner {partner.username} suspended'})
        except User.DoesNotExist:
            return Response({'error': 'Partner not found'}, status=status.HTTP_404_NOT_FOUND)

class PlatformOrdersView(SuperAdminBaseView, APIView):
    def get(self, request):
        orders = Order.objects.all().order_by('-created_at')[:100]
        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data)

class PlatformAnalyticsView(SuperAdminBaseView, APIView):
    def get(self, request):
        total_revenue = Order.objects.filter(payment_status='paid').aggregate(total=Sum('total'))['total'] or 0
        total_orders = Order.objects.count()
        total_stores = Store.objects.count()
        total_customers = User.objects.filter(role='customer').count()
        
        return Response({
            'total_revenue': float(total_revenue),
            'total_orders': total_orders,
            'total_stores': total_stores,
            'total_customers': total_customers
        })

class PendingPartnersView(SuperAdminBaseView, APIView):
    def get(self, request):
        pending = User.objects.filter(role='partner', is_approved=False).order_by('-date_joined')
        serializer = UserSerializer(pending, many=True)
        return Response(serializer.data)

class PendingRevenuePayoutsView(SuperAdminBaseView, APIView):
    def get(self, request):
        pending = WeeklyRevenueStat.objects.filter(status='pending').order_by('-week_start')
        data = []
        for p in pending:
            data.append({
                'id': p.id,
                'store_name': p.store.name,
                'week_range': f"{p.week_start} to {p.week_end}",
                'amount': float(p.partner_share_40),
                'mpesa_code': p.payouts.mpesa_code if hasattr(p, 'payouts') else "N/A",
                'submitted_at': p.payouts.paid_at if hasattr(p, 'payouts') else p.created_at
            })
        return Response(data)

class ApproveRevenuePayoutView(SuperAdminBaseView, APIView):
    def post(self, request, pk):
        stat = get_object_or_404(WeeklyRevenueStat, pk=pk)
        stat.status = 'paid'
        stat.is_paid = True
        stat.save()
        
        if stat.store.owner.telegram_chat_id:
            from .tasks import send_telegram_notification_task
            send_telegram_notification_task.delay(
                stat.store.owner.telegram_chat_id,
                f"✅ <b>Revenue Payout Approved!</b>\nYour payment for week <b>{stat.week_start}</b> has been verified. Dashboard access restored.",
                bot_type='admin' # Verification results still come from Admin bot
            )
            
        return Response({'message': 'Payout approved successfully'})
