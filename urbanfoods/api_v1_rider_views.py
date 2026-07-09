from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.db.models import Q
from .models import Order, RiderLocationPing, RiderEarning, User
from .api_v1_serializers import OrderSerializer, RiderEarningSerializer, RiderProfileSerializer
from .permissions import IsRider
from .utils import send_telegram_notification

VALID_TRANSITIONS = {
    'assigned': ['picked_up'],
    'picked_up': ['arrived'],
    'arrived': ['delivered'],
}

class RiderOrderStatusView(APIView):
    permission_classes = [IsRider]
    
    def patch(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, assigned_rider=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found or not assigned to you'}, status=status.HTTP_404_NOT_FOUND)
            
        new_status = request.data.get('status')
        if new_status not in VALID_TRANSITIONS.get(order.status, []):
            return Response({
                'error': 'Invalid status transition',
                'current_status': order.status,
                'attempted_status': new_status
            }, status=status.HTTP_400_BAD_REQUEST)

        order.status = new_status
        if new_status == 'picked_up':
            order.picked_up_at = timezone.now()
        elif new_status == 'arrived':
            order.arrived_at = timezone.now()
        elif new_status == 'delivered':
            order.delivered_at = timezone.now()
            # Create earning record
            RiderEarning.objects.get_or_create(
                order=order,
                defaults={
                    'rider': request.user,
                    'base_fare': order.rider_base_fare,
                    'tip': order.tip_amount,
                    'total': order.rider_base_fare + order.tip_amount
                }
            )
            # Update rider stats
            request.user.total_deliveries += 1
            request.user.save(update_fields=['total_deliveries'])
            
            # Notify store
            if order.store and order.store.telegram_chat_id:
                send_telegram_notification(
                    order.store.telegram_chat_id,
                    f"✅ <b>Order Delivered!</b>\nOrder: #{order.order_number}\nBy Rider: {request.user.get_full_name() or request.user.username}"
                )
                
        order.save()
        return Response({'status': 'updated', 'new_status': order.status})

class RiderLocationPingView(APIView):
    permission_classes = [IsRider]
    
    def post(self, request):
        order_id = request.data.get('order_id')
        try:
            RiderLocationPing.objects.create(
                rider=request.user,
                order_id=order_id,
                latitude=request.data['latitude'],
                longitude=request.data['longitude']
            )
            return Response({'status': 'ok'})
        except KeyError as e:
            return Response({'error': f'Missing field: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

class RiderEarningsView(APIView):
    permission_classes = [IsRider]
    
    def get(self, request):
        earnings = RiderEarning.objects.filter(rider=request.user).order_by('-created_at')
        serializer = RiderEarningSerializer(earnings, many=True)
        return Response(serializer.data)

class RiderEarningsSummaryView(APIView):
    permission_classes = [IsRider]
    
    def get(self, request):
        from django.db.models import Sum
        summary = RiderEarning.objects.filter(rider=request.user).aggregate(
            total_earned=Sum('total'),
            total_base=Sum('base_fare'),
            total_tips=Sum('tip'),
            delivery_count=Sum(1) # Count is better here but aggregate Sum(1) works or just .count()
        )
        summary['delivery_count'] = RiderEarning.objects.filter(rider=request.user).count()
        return Response(summary)

class RiderProfileView(APIView):
    permission_classes = [IsRider]
    
    def get(self, request):
        serializer = RiderProfileSerializer(request.user)
        return Response(serializer.data)
        
    def patch(self, request):
        # Explicitly handle is_available for status toggle
        if 'is_available' in request.data:
            request.user.is_available = request.data['is_available']
            request.user.save(update_fields=['is_available'])
            
        serializer = RiderProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class RiderOrderQueueView(APIView):
    permission_classes = [IsRider]
    
    def get(self, request):
        # Available orders: assigned to nobody and store is active
        # Or specifically assigned to this rider but pending pickup
        queryset = Order.objects.filter(
            Q(assigned_rider__isnull=True, status='pending') | 
            Q(assigned_rider=request.user, status__in=['assigned', 'picked_up', 'arrived'])
        ).order_by('-created_at')
        
        serializer = OrderSerializer(queryset, many=True)
        return Response(serializer.data)

class RiderAcceptOrderView(APIView):
    permission_classes = [IsRider]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, assigned_rider__isnull=True, status='pending')
        except Order.DoesNotExist:
            return Response({'error': 'Order not available or already taken'}, status=status.HTTP_404_NOT_FOUND)

        order.assigned_rider = request.user
        order.status = 'assigned'
        order.save()
        
        return Response({'status': 'accepted', 'order': OrderSerializer(order).data})
