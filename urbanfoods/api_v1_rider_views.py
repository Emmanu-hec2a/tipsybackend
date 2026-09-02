from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.throttling import ScopedRateThrottle
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, F, ExpressionWrapper, FloatField, Sum, Value
from django.db.models.functions import Sqrt, Power
from django.core.cache import cache
import json
import logging
import requests
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404

logger = logging.getLogger(__name__)

from .models import Order, RiderEarning, RiderLocationPing, User, RiderWeeklyStat, PanicAlert
from .api_v1_serializers import (
    OrderSerializer, RiderEarningSerializer, RiderProfileSerializer,
    RiderWeeklyStatSerializer, PanicAlertSerializer
)
from .permissions import IsRider

VALID_TRANSITIONS = {
    'assigned': ['picked_up'],
    'picked_up': ['arrived'],
    'arrived': ['delivered'],
}


def parse_rider_coordinates(latitude, longitude):
    try:
        lat = Decimal(str(latitude))
        lng = Decimal(str(longitude))
    except (InvalidOperation, TypeError, ValueError):
        return None

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng

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
            
            # 🛡️ PRODUCTION HARDENING: Atomic Transaction for Source of Truth
            from django.db import transaction
            try:
                with transaction.atomic():
                    # 1. Create earning record (The financial source of truth)
                    base_fare = order.rider_base_fare if order.rider_base_fare is not None else Decimal('200.00')
                    tip = order.tip_amount if order.tip_amount is not None else Decimal('0.00')
                    
                    RiderEarning.objects.get_or_create(
                        order=order,
                        defaults={
                            'rider': request.user,
                            'base_fare': base_fare,
                            'tip': tip,
                            'total': base_fare + tip
                        }
                    )
                    # 2. Update order status permanently
                    order.save(update_fields=['status', 'delivered_at', 'rider_verified_at', 'rider_verification_method'])
                    
                    # 🚀 Real-time Invalidation: Clear earnings cache so rider sees updates instantly
                    cache.delete(f"rider_earnings_summary_{request.user.id}")
            except Exception as e:
                return Response({'error': f'Failed to finalize delivery: {str(e)}'}, status=500)

            # 3. Write-back buffered location pings from cache to DB
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
                from .tasks import send_telegram_notification_task
                send_telegram_notification_task.delay(
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

        coordinates = parse_rider_coordinates(lat, lng)
        if coordinates is None:
            return Response({'error': 'Invalid coordinates'}, status=status.HTTP_400_BAD_REQUEST)
        lat, lng = coordinates

        order = None
        if order_id:
            try:
                order = Order.objects.get(
                    id=order_id,
                    assigned_rider=request.user,
                    status__in=['assigned', 'picked_up', 'arrived']
                )
            except Order.DoesNotExist:
                return Response({'error': 'Active order not found'}, status=status.HTTP_400_BAD_REQUEST)

        # Heartbeats without an order establish discoverability. Active-order
        # pings remain buffered below and are persisted on delivery completion.
        if order is None:
            RiderLocationPing.objects.create(
                rider=request.user,
                latitude=lat,
                longitude=lng,
            )

        # 1. Update latest rider position in cache for real-time retrieval
        rider_pos_key = f"rider_pos_{request.user.id}"
        cache.set(rider_pos_key, {'lat': float(lat), 'lng': float(lng)}, timeout=300)

        # 2. If this ping is for a specific order, buffer it for the trip path
        if order_id:
            path_key = f"order_path_{order_id}"
            current_path = cache.get(path_key, [])
            current_path.append({
                'lat': lat,
                'lng': lng,
                'timestamp': timezone.localtime(timezone.now()).isoformat()
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
        # 🛡️ Redis Caching (1 Hour) - Earnings don't need real-time refresh every second
        cache_key = f"rider_earnings_summary_{request.user.id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)

        summary = RiderEarning.objects.filter(rider=request.user).aggregate(
            total_earned=Sum('total'),
            total_base=Sum('base_fare'),
            total_tips=Sum('tip')
        )
        summary['delivery_count'] = RiderEarning.objects.filter(rider=request.user).count()
        
        # Ensure floats for JSON serialization
        summary = {k: (float(v) if v is not None else 0.0) for k, v in summary.items()}
        
        cache.set(cache_key, summary, 3600)
        return Response(summary)

class RiderProfileView(APIView):
    permission_classes = [IsRider]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    
    def get(self, request):
        serializer = RiderProfileSerializer(request.user)
        return Response(serializer.data)
        
    def patch(self, request):
        logger.info(f"Rider Profile Patch Request: {request.data} for user {request.user.id}")
        
        # 🛡️ Mandatory Location Gate: To go online, rider MUST provide GPS
        if 'is_available' in request.data:
            # Handle both JSON boolean and possible form-encoded string
            val = request.data['is_available']
            is_available = val if isinstance(val, bool) else str(val).lower() == 'true'
            
            if is_available:
                lat = request.data.get('latitude')
                lng = request.data.get('longitude')
                
                if not lat or not lng:
                    logger.warning(f"Rider {request.user.id} tried to go online without GPS. Lat: {lat}, Lng: {lng}")
                    return Response({
                        'error': 'location_required',
                        'message': 'High-accuracy GPS is required to accept deliveries.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Instantly cache position to make rider visible to merchants
                rider_pos_key = f"rider_pos_{request.user.id}"
                cache.set(rider_pos_key, {'lat': lat, 'lng': lng}, timeout=300)
            else:
                # 🛡️ Safety Guard: Prevent going offline if they have an active order
                active_delivery = Order.objects.filter(
                    assigned_rider=request.user, 
                    status__in=['assigned', 'picked_up', 'arrived']
                ).exists()
                
                if active_delivery:
                    logger.warning(f"Rider {request.user.id} tried to go offline with active orders.")
                    return Response({
                        'error': 'active_order',
                        'message': 'You cannot go offline while you have an active delivery in progress.'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            request.user.is_available = is_available
            request.user.save(update_fields=['is_available'])
            
        serializer = RiderProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
            
        logger.error(f"Rider Profile Validation Errors: {serializer.errors}")
        # Always wrap errors in a message for the frontend
        return Response({
            'error': 'validation_error',
            'message': 'Unable to update profile. Please check your details.',
            'details': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

class RiderOrderQueueView(APIView):
    permission_classes = [IsRider]
    
    def get(self, request):
        # 🌍 Open Pool Logistics with Proximity Intelligence
        # 🛡️ Hardening: Separate assigned orders from available pool to prevent filtering assigned tasks
        assigned_queryset = Order.objects.filter(assigned_rider=request.user, status__in=['assigned', 'picked_up', 'arrived']).select_related('store')
        pool_queryset = Order.objects.filter(assigned_rider__isnull=True, status__in=['pending', 'confirmed', 'processing']).select_related('store')
        
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        
        if lat is not None and lng is not None:
            try:
                u_lat = float(lat)
                u_lng = float(lng)
                
                # 🛡️ Bounding Box Filter (Approx 15km x 15km) applied ONLY to available pool
                deg = 0.15 
                pool_queryset = pool_queryset.filter(
                    store__latitude__range=(u_lat - deg, u_lat + deg),
                    store__longitude__range=(u_lng - deg, u_lng + deg)
                )

                # 🌍 Annotate distance using high-precision FloatField
                pool_queryset = pool_queryset.annotate(
                    distance=ExpressionWrapper(
                        Sqrt(Power(F('store__latitude') - u_lat, 2) + Power(F('store__longitude') - u_lng, 2)) * 111.0,
                        output_field=FloatField()
                    )
                )
                
                # Also annotate assigned with 0.0 distance to keep schema consistent for union if needed, 
                # but we can just use a list combine for simplicity since queryset sizes are small.
                assigned_queryset = assigned_queryset.annotate(distance=Value(0.0, output_field=FloatField()))

            except (ValueError, TypeError):
                pass
        else:
            if request.user.assigned_store:
                pool_queryset = pool_queryset.filter(store=request.user.assigned_store)
            
            # Annotate with default distance to keep it consistent
            assigned_queryset = assigned_queryset.annotate(distance=Value(0.0, output_field=FloatField()))
            pool_queryset = pool_queryset.annotate(distance=Value(0.0, output_field=FloatField()))

        # Combine both sets. Assigned tasks ALWAYS take priority.
        combined_list = list(assigned_queryset) + list(pool_queryset)
        
        serializer = OrderSerializer(combined_list, many=True)
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
        with transaction.atomic():
            rider = User.objects.select_for_update().get(pk=request.user.pk)
            if not rider.is_available:
                return Response(
                    {'error': 'Rider must be online to accept orders'},
                    status=status.HTTP_403_FORBIDDEN
                )

            try:
                order = Order.objects.select_for_update().get(
                    id=order_id,
                    assigned_rider__isnull=True,
                    status__in=['pending', 'confirmed', 'processing']
                )
            except Order.DoesNotExist:
                return Response({'error': 'Order no longer available'}, status=status.HTTP_404_NOT_FOUND)

            order.assigned_rider = request.user
            order.status = 'assigned'
            order.save(update_fields=['assigned_rider', 'status'])
        
        return Response({'status': 'accepted', 'order': OrderSerializer(order).data})

class RiderPayoutHistoryView(APIView):
    permission_classes = [IsRider]
    
    def get(self, request):
        stats = RiderWeeklyStat.objects.filter(rider=request.user).order_by('-week_start')
        return Response(RiderWeeklyStatSerializer(stats, many=True).data)

class RiderPayoutDisputeView(APIView):
    permission_classes = [IsRider]
    
    def post(self, request, pk):
        stat = get_object_or_404(RiderWeeklyStat, pk=pk, rider=request.user)
        
        reason = request.data.get('reason', 'Payment not received')
        stat.status = 'disputed'
        stat.save()
        
        # 🔔 Notify SuperAdmin via Telegram
        from .utils import send_telegram_message
        msg = (
            f"🚩 <b>PAYOUT DISPUTE RAISED</b>\n\n"
            f"Rider: {request.user.username}\n"
            f"Store: {stat.store.name}\n"
            f"Amount: KSh {stat.total_amount}\n"
            f"Week: {stat.week_start}\n"
            f"Reason: {reason}"
        )
        send_telegram_message(msg, bot_type='admin')
        
        return Response({'status': 'disputed', 'message': 'Dispute raised successfully'})

class RiderPanicAlertView(APIView):
    permission_classes = [IsRider]
    
    def post(self, request):
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        
        if not lat or not lng:
            return Response({'error': 'Coordinates required'}, status=400)
            
        panic = PanicAlert.objects.create(
            rider=request.user,
            latitude=lat,
            longitude=lng
        )
        
        # 🚨 TRIGGER EMERGENCY ALERTS
        from .utils import send_telegram_message, send_telegram_notification
        
        # 1. Notify SuperAdmin
        admin_msg = (
            f"🚨 <b>EMERGENCY: RIDER PANIC ALERT</b>\n\n"
            f"Rider: {request.user.get_full_name() or request.user.username}\n"
            f"Phone: {request.user.phone}\n"
            f"Location: https://www.google.com/maps?q={lat},{lng}\n"
            f"Time: {timezone.localtime(timezone.now()).strftime('%I:%M %p')}"
        )
        send_telegram_message(admin_msg, bot_type='admin')
        
        # 2. Notify Store Owner (if linked)
        if request.user.assigned_store and request.user.assigned_store.telegram_chat_id:
            send_telegram_notification(request.user.assigned_store.telegram_chat_id, admin_msg)
            
        return Response({'status': 'alert_sent', 'panic_id': panic.id})

class RiderReportIssueView(APIView):
    permission_classes = [IsRider]
    
    def post(self, request):
        issue_type = request.data.get('type', 'General')
        message = request.data.get('message')
        
        if not message:
            return Response({'error': 'Message content is required'}, status=400)
            
        # 🔔 Notify SuperAdmin via Telegram
        from .utils import send_telegram_message
        report_msg = (
            f"⚠️ <b>RIDER ISSUE REPORT</b>\n\n"
            f"Rider: {request.user.get_full_name() or request.user.username}\n"
            f"Phone: {request.user.phone}\n"
            f"Type: {issue_type}\n"
            f"Report: {message}\n"
            f"Time: {timezone.localtime(timezone.now()).strftime('%I:%M %p, %d %b %Y')}"
        )
        send_telegram_message(report_msg, bot_type='admin')
        
        return Response({'status': 'success', 'message': 'Issue reported successfully'})


class DirectionsView(APIView):
    """
    🛡️ Server-side proxy for Google Directions API, shared by rider and
    customer apps (both poll a route between two arbitrary coordinates).

    The Maps SDK key shipped in the Android app is (correctly) restricted to
    Android apps, which blocks direct client-side HTTP calls to the Directions
    REST API. Proxying through the backend keeps a Directions-only key
    server-side, never exposed in the APK. No order-specific authorization is
    needed here: inputs are plain coordinates, not order/user records.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'rider_directions'

    def get(self, request):
        origin = parse_rider_coordinates(
            request.query_params.get('origin_lat'), request.query_params.get('origin_lng')
        )
        destination = parse_rider_coordinates(
            request.query_params.get('dest_lat'), request.query_params.get('dest_lng')
        )
        if origin is None or destination is None:
            return Response({'success': False, 'message': 'Invalid coordinates'}, status=status.HTTP_400_BAD_REQUEST)

        origin_lat, origin_lng = origin
        dest_lat, dest_lng = destination

        api_key = getattr(settings, 'GOOGLE_DIRECTIONS_API_KEY', None)
        if not api_key:
            logger.error("DirectionsView: GOOGLE_DIRECTIONS_API_KEY is not configured")
            return Response({'success': False, 'message': 'Directions service unavailable'}, status=502)

        # Round to ~11m precision so nearby repeat requests (frequent GPS pings)
        # can share a cached route instead of billing Google on every call.
        cache_key = (
            f"directions:{round(float(origin_lat), 4)}:{round(float(origin_lng), 4)}:"
            f"{round(float(dest_lat), 4)}:{round(float(dest_lng), 4)}"
        )
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        try:
            response = requests.get(
                'https://maps.googleapis.com/maps/api/directions/json',
                params={
                    'origin': f'{origin_lat},{origin_lng}',
                    'destination': f'{dest_lat},{dest_lng}',
                    'mode': 'driving',
                    'key': api_key,
                },
                timeout=8,
            )
            data = response.json()
        except requests.RequestException:
            logger.exception("DirectionsView: request to Google Directions API failed")
            return Response({'success': False, 'message': 'Unable to reach directions service'}, status=502)

        if data.get('status') != 'OK' or not data.get('routes'):
            logger.warning("DirectionsView: Google Directions API error: %s", data.get('status'))
            return Response({'success': False, 'message': 'Route not found'}, status=502)

        route = data['routes'][0]
        legs = route.get('legs') or [{}]
        payload = {
            'success': True,
            'polyline': route.get('overview_polyline', {}).get('points'),
            'distance_meters': legs[0].get('distance', {}).get('value'),
            'duration_seconds': legs[0].get('duration', {}).get('value'),
        }
        cache.set(cache_key, payload, timeout=20)
        return Response(payload)
