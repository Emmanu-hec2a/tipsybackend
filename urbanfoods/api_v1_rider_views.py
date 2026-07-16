from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from django.utils import timezone
from django.db.models import Q, F
from django.core.cache import cache
import json
from .models import Order, RiderEarning, User
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
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    
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
            # 🛡️ Guard: Ensure verification is done if required
            if order.requires_rider_verification and not order.rider_verified_at:
                verification_method = request.data.get('verification_method')
                verification_image = request.FILES.get('verification_image')
                
                if not verification_method:
                    return Response({
                        'error': 'verification_required',
                        'message': 'Recipent ID verification is required for this order.'
                    }, status=status.HTTP_403_FORBIDDEN)
                
                # 🛡️ Midnight Mirror: Encrypt image if provided
                if verification_image:
                    from .utils import encrypt_verification_image
                    from django.core.files.base import ContentFile
                    
                    img_data = verification_image.read()
                    encrypted_data = encrypt_verification_image(img_data)
                    
                    # Save as a file with .enc extension
                    file_name = f"order_{order.order_number}_verify.enc"
                    order.verification_image.save(file_name, ContentFile(encrypted_data), save=False)

                order.rider_verified_at = timezone.now()
                order.rider_verification_method = verification_method

            order.delivered_at = timezone.now()
            # 1. Create earning record
            RiderEarning.objects.get_or_create(
                order=order,
                defaults={
                    'rider': request.user,
                    'base_fare': order.rider_base_fare,
                    'tip': order.tip_amount,
                    'total': order.rider_base_fare + order.tip_amount
                }
            )
            # 2. Write-back buffered location pings from cache to DB
            from .models import RiderLocationPing
            path_key = f"order_path_{order.id}"
            buffered_path = cache.get(path_key, [])
            if buffered_path:
                pings_to_create = [
                    RiderLocationPing(
                        rider=request.user,
                        order=order,
                        latitude=point['lat'],
                        longitude=point['lng'],
                        created_at=point['timestamp']
                    ) for point in buffered_path
                ]
                RiderLocationPing.objects.bulk_create(pings_to_create)
                cache.delete(path_key) # Clean up cache
            # Update rider stats
            request.user.total_deliveries += 1
            request.user.save(update_fields=['total_deliveries'])
            
            # 3. Update customer loyalty points (1 point per 100 KSh spent)
            if order.user:
                points_earned = int(order.total / 100)
                if points_earned > 0:
                    order.user.loyalty_points = F('loyalty_points') + points_earned
                    order.user.save(update_fields=['loyalty_points'])
            
            # Notify store
            if order.store and order.store.telegram_chat_id:
                send_telegram_notification(
                    order.store.telegram_chat_id,
                    f"✅ <b>Order Delivered!</b>\nOrder: #{order.order_number}\nBy Rider: {request.user.get_full_name() or request.user.username}"
                )
                
        order.save()
        return Response({'status': 'updated', 'new_status': order.status})

from django.core.cache import cache
import json

class RiderLocationPingView(APIView):
    permission_classes = [IsRider]
    
    def post(self, request):
        order_id = request.data.get('order_id')
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')

        if not lat or not lng:
            return Response({'error': 'Missing coordinates'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Update latest rider position in cache for real-time retrieval
        rider_pos_key = f"rider_pos_{request.user.id}"
        cache.set(rider_pos_key, {'lat': lat, 'lng': lng}, timeout=300) # 5 mins TTL

        # 2. If this ping is for a specific order, buffer it for the trip path
        if order_id:
            path_key = f"order_path_{order_id}"
            current_path = cache.get(path_key, [])
            current_path.append({
                'lat': lat,
                'lng': lng,
                'timestamp': timezone.now().isoformat()
            })
            cache.set(path_key, current_path, timeout=3600*4) # 4 hours TTL

        return Response({'status': 'ok'})

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
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    
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
        # 🛡️ Strict Isolation: Rider can ONLY see orders from their assigned store
        if not request.user.assigned_store:
            return Response({'error': 'No store assigned to this rider'}, status=status.HTTP_403_FORBIDDEN)

        # Available orders: assigned to nobody and status is pending, but ONLY for their store
        # Or specifically assigned to this rider for active delivery
        queryset = Order.objects.filter(
            Q(assigned_rider__isnull=True, status='pending', store=request.user.assigned_store) | 
            Q(assigned_rider=request.user, status__in=['assigned', 'picked_up', 'arrived'])
        ).order_by('-created_at')
        
        serializer = OrderSerializer(queryset, many=True)
        return Response(serializer.data)

class RiderHistoryView(APIView):
    permission_classes = [IsRider]
    
    def get(self, request):
        # Get all delivered orders for this rider
        queryset = Order.objects.filter(
            assigned_rider=request.user, 
            status='delivered'
        ).order_by('-delivered_at')
        
        serializer = OrderSerializer(queryset, many=True)
        return Response(serializer.data)

class RiderAcceptOrderView(APIView):
    permission_classes = [IsRider]

    def post(self, request, order_id):
        if not request.user.assigned_store:
            return Response({'error': 'No store assigned to this rider'}, status=status.HTTP_403_FORBIDDEN)

        try:
            # 🛡️ Strict Isolation: Only allow accepting if the order belongs to the rider's assigned store
            order = Order.objects.get(
                id=order_id, 
                assigned_rider__isnull=True, 
                status='pending',
                store=request.user.assigned_store
            )
        except Order.DoesNotExist:
            return Response({'error': 'Order not available or belongs to another store'}, status=status.HTTP_404_NOT_FOUND)

        order.assigned_rider = request.user
        order.status = 'assigned'
        order.save()
        
        return Response({'status': 'accepted', 'order': OrderSerializer(order).data})
