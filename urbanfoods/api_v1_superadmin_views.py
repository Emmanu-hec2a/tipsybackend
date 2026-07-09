from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum, Count
from .models import Store, User, Order
from .api_v1_serializers import StoreSerializer, UserSerializer, OrderSerializer
from .permissions import IsSuperAdmin
from .utils import send_telegram_notification

class SuperAdminBaseView:
    permission_classes = [IsSuperAdmin]

class StoreListView(SuperAdminBaseView, APIView):
    def get(self, request):
        stores = Store.objects.all().order_by('-created_at')
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
            store, created = Store.objects.get_or_create(
                owner=partner,
                defaults={
                    'name': partner.business_name or f"{partner.username}'s Store",
                    'is_active': True,
                    'latitude': 0,
                    'longitude': 0
                }
            )
            
            if partner.telegram_chat_id:
                send_telegram_notification(
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
            
            # Deactivate store
            if hasattr(partner, 'store'):
                partner.store.is_active = False
                partner.store.save()
                
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
