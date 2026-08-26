from rest_framework import generics, permissions, status
from datetime import date
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import os
import uuid
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.db.models import Q, F, ExpressionWrapper, DecimalField, FloatField, Avg, Exists, OuterRef, Value, BooleanField, Count
from django.db.models.functions import Sqrt, Power
from .models import (
    Store, FoodItem, Order, Rating, SavedAddress, OrderItem, 
    OrderStatusHistory, FoodCategory, Promotion, ChatMessage,
    ShirikiSession, ShirikiContribution, User
)
from .payment_initiation import InitiatePaymentService, PaymentInitiationConflict
from .api_v1_serializers import (
    StoreSerializer, FoodItemSerializer, OrderSerializer, 
    UserSerializer, SavedAddressSerializer, FoodCategorySerializer, 
    PromotionSerializer, ChatMessageSerializer,
    ShirikiSessionSerializer, ShirikiContributionSerializer
)

from decimal import Decimal, InvalidOperation
from django.db.models import Sum
from django.utils import timezone
from .permissions import IsCustomer
from .mpesa_utils import MpesaIntegration
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db import transaction, IntegrityError
from .utils import calculate_risk_score
from .order_idempotency import order_request_fingerprint, validate_idempotency_key
from .shiriki_service import ShirikiCapacityConflict, ShirikiService, ShirikiSessionConflict
from .payment_status import (
    TERMINAL_PAYMENT_STATUSES, cache_status, get_cached_status, next_poll_after, retry_after,
)
from .payment_throttles import PaymentAttemptThrottle
from .rate_limiting import (  # 🛡️ Day 2: Rate Limiting Classes
    PaymentStatusThrottle, 
    GlobalAuthenticatedThrottle,
    GlobalAnonymousThrottle,
    ListEndpointThrottle,
)
import logging

logger = logging.getLogger(__name__)

class SavedAddressViewSet(generics.ListCreateAPIView):
    serializer_class = SavedAddressSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return SavedAddress.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class SavedAddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SavedAddressSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return SavedAddress.objects.filter(user=self.request.user)

class CustomerProfileView(APIView):
    permission_classes = [IsCustomer]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        # 🛡️ AI Face Guard: Cross-verify selfie content
        selfie = request.FILES.get('profile_picture')
        if selfie and request.data.get('is_age_verified') == 'true':
            from .ai_utils import validate_face_in_image
            is_valid, msg = validate_face_in_image(selfie)
            if not is_valid:
                logger.warning(f"AI Face Guard Blocked {request.user.username}: {msg}")
                return Response({'error': 'verification_failed', 'message': msg}, status=status.HTTP_400_BAD_REQUEST)

        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        logger.warning(f"Profile Update Failed for {request.user.username}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CustomerStoreListView(generics.ListAPIView):
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Base queryset: active stores with valid subscriptions
        # Franchise branches inherit validity from their parent store
        from django.db.models import Q
        queryset = Store.objects.filter(
            Q(is_active=True, billing_status='active', subscription_expires__gte=date.today()) |
            Q(is_active=True, is_franchise=True, parent_store__billing_status='active', parent_store__subscription_expires__gte=date.today())
        ).select_related('owner', 'parent_store')
        
        # Annotate is_favourite if user is authenticated
        user = self.request.user
        if user.is_authenticated:
            queryset = queryset.annotate(
                is_favourite=Exists(
                    user.favourite_stores.filter(id=OuterRef('pk'))
                )
            )
        else:
            queryset = queryset.annotate(is_favourite=Value(False, output_field=BooleanField()))

        # 🛡️ Hardening: Default distance to 0.0 to prevent nulls in serializer when coordinates are missing
        queryset = queryset.annotate(distance=Value(0.0, output_field=FloatField()))

        queryset = queryset.order_by('-is_pro', 'name')
        
        # Get coordinates from query params
        lat = self.request.query_params.get('lat')
        lng = self.request.query_params.get('lng')
        is_pro_only = self.request.query_params.get('is_pro_only')

        if is_pro_only == 'true':
            queryset = queryset.filter(is_pro=True)

        if lat is not None and lng is not None:
            try:
                u_lat = float(lat)
                u_lng = float(lng)
                
                # 🛡️ Scalability Guard: Bounding Box Filter (Approx 165km x 165km)
                # We filter by a square first to use DB indexes before doing the heavy Sqrt math
                lat_deg = 1.5 
                lng_deg = 1.5
                queryset = queryset.filter(
                    latitude__range=(u_lat - lat_deg, u_lat + lat_deg),
                    longitude__range=(u_lng - lng_deg, u_lng + lng_deg)
                )

                # Filter by store radius (Strict radius enforcement)
                queryset = queryset.annotate(
                    distance=ExpressionWrapper(
                        Sqrt(Power(F('latitude') - u_lat, 2) + Power(F('longitude') - u_lng, 2)) * 111.0,
                        output_field=FloatField()
                    )
                ).filter(distance__lte=F('delivery_radius_km')).order_by('-is_pro', 'distance')
            except (ValueError, TypeError):
                pass
        
        # 🛡️ Limit for Home Screen / Popular List to prevent 1000+ items load
        limit = self.request.query_params.get('limit')
        if limit:
            try:
                queryset = queryset[:int(limit)]
            except ValueError:
                queryset = queryset[:20]
        else:
            # Default safety limit for generic listing
            queryset = queryset[:50]
                
        return queryset

class CustomerStoreDetailView(generics.RetrieveAPIView):
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from django.db.models import Q
        return Store.objects.filter(
            Q(is_active=True, billing_status='active', subscription_expires__gte=date.today()) |
            Q(is_active=True, is_franchise=True, parent_store__billing_status='active', parent_store__subscription_expires__gte=date.today())
        )

@method_decorator(cache_page(60*5), name='dispatch')
class CustomerCategoryListView(generics.ListAPIView):
    queryset = FoodCategory.objects.all().order_by('order', 'name')
    serializer_class = FoodCategorySerializer
    permission_classes = [permissions.IsAuthenticated]

class CustomerToggleFavouriteView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        store = get_object_or_404(Store, pk=pk)
        user = request.user
        if user.favourite_stores.filter(id=store.id).exists():
            user.favourite_stores.remove(store)
            return Response({'is_favourite': False})
        else:
            user.favourite_stores.add(store)
            return Response({'is_favourite': True})

class CustomerFavouriteStoresListView(generics.ListAPIView):
    serializer_class = StoreSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return self.request.user.favourite_stores.filter(is_active=True).annotate(
            distance=Value(0.0, output_field=FloatField())
        )

class CustomerRedeemPointsView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request):
        user = request.user
        from .ledger_service import FinancialLedgerService, LedgerConflict
        try:
            points, redeem_value, new_balance, new_points = FinancialLedgerService.redeem_points(
                user.id, request.headers.get('Idempotency-Key') or f'points-redemption-{user.id}-{uuid.uuid4()}'
            )
        except LedgerConflict as exc:
            return Response({'error': str(exc)}, status=409)
        
        return Response({
            'message': f'Successfully redeemed {points} points for KSh {redeem_value}.',
            'new_balance': new_balance,
            'new_points': new_points
        })

class CustomerProductListView(generics.ListAPIView):
    serializer_class = FoodItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Prioritize products from Pro stores with valid subscriptions
        # 🛡️ Debt Enforcement Guard: Exclude products from stores with 2+ weeks unpaid share
        from django.utils import timezone
        from .models import WeeklyRevenueStat
        today = timezone.localdate()
        
        # 🛡️ Debt Enforcement Guard: (Temporarily Disabled)
        # Identify stores that are restricted due to debt
        # restricted_store_ids = WeeklyRevenueStat.objects.filter(
        #     week_end__lt=today,
        #     is_paid=False,
        #     partner_share_40__gt=0
        # ).values('store').annotate(unpaid_count=Count('id')).filter(unpaid_count__gte=2).values_list('store_id', flat=True)
        restricted_store_ids = [] # Empty list to disable filtering

        # Base filter: products from active stores with valid subscriptions (or inherited franchise validity)
        # 🛡️ Inventory Guard: Exclude products with 0 stock and only show available
        from django.db.models import Q
        queryset = FoodItem.objects.filter(
            Q(is_active=True, is_available=True, stock__gt=0, store__is_active=True, store__billing_status='active', store__subscription_expires__gte=date.today()) |
            Q(is_active=True, is_available=True, stock__gt=0, store__is_active=True, store__is_franchise=True, store__parent_store__billing_status='active', store__parent_store__subscription_expires__gte=date.today())
        ).exclude(store_id__in=restricted_store_ids).order_by('-store__is_pro', 'name')
        
        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)
            
        is_featured = self.request.query_params.get('is_featured')
        if is_featured == 'true':
            queryset = queryset.filter(is_featured=True)
            
        category_name = self.request.query_params.get('category_name')
        if category_name:
            queryset = queryset.filter(category_fkey__name__iexact=category_name)
            
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | 
                Q(description__icontains=search)
            )
            
        return queryset

class CustomerOrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        # 🛡️ SHIRIKI GUARD: Include orders where user is host OR participant
        return Order.objects.filter(
            Q(user=self.request.user) | 
            Q(shiriki_session__contributions__user=self.request.user, shiriki_session__contributions__status='confirmed')
        ).distinct().order_by('-created_at')

class CustomerOrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        # 🛡️ SHIRIKI GUARD: Participants can see details too
        return Order.objects.filter(
            Q(user=self.request.user) | 
            Q(shiriki_session__contributions__user=self.request.user, shiriki_session__contributions__status='confirmed')
        ).distinct()

class CustomerOrderPaymentStatusView(APIView):
    permission_classes = [IsCustomer]
    throttle_classes = [PaymentStatusThrottle]  # 🛡️ 30 requests/hour per user (Day 2)

    def get(self, request, pk):
        # 🛡️ SHIRIKI GUARD: Allow access for participants
        cache_key = f'tipsy:order-payment-status:{request.user.id}:{pk}'
        try:
            cached = cache.get(cache_key)
        except Exception:
            cached = None
        if cached:
            response = Response(cached)
            response['Cache-Control'] = 'private, max-age=2'
            return response
        order = get_object_or_404(
            Order.objects.filter(
                Q(user=request.user) | 
                Q(shiriki_session__contributions__user=request.user, shiriki_session__contributions__status='confirmed')
            ).distinct(),
            pk=pk
        )
        cache_key = f'tipsy:order-payment-status:{request.user.id}:{order.id}'
        payload = {
            'order_id': order.id,
            'order_number': order.order_number,
            'payment_status': order.payment_status,
            'status': order.status,
            'mpesa_checkout_request_id': order.mpesa_checkout_request_id,
            'terminal': order.payment_status in ('paid', 'failed', 'cancelled'),
            'next_poll_after_seconds': 5 if order.payment_status == 'pending' else None,
        }
        try:
            cache.set(cache_key, payload, timeout=30 if payload['terminal'] else 2)
        except Exception:
            pass
        response = Response(payload)
        response['Cache-Control'] = 'private, max-age=30' if payload['terminal'] else 'private, max-age=2'
        return response

class CustomerMpesaQueryView(APIView):
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment_query'

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, user=request.user)
        
        if not order.mpesa_checkout_request_id:
            return Response({'error': 'No M-Pesa transaction found for this order'}, status=400)
            
        if order.payment_status == 'paid':
            return Response({'status': 'paid', 'message': 'Payment already confirmed'})

        from .mpesa_utils import MpesaIntegration
        mpesa = MpesaIntegration(store=order.store)
        
        # 🛡️ Hardening: Ensure store has credentials before querying
        if not mpesa.consumer_key or not mpesa.consumer_secret:
            return Response({
                'status': 'error', 
                'message': f'Payment status cannot be queried because {order.store.name} has not configured their M-Pesa API keys.'
            }, status=400)
        
        try:
            result = mpesa.query_stk_status(order.mpesa_checkout_request_id)
            
            if result.get('success'):
                from .payment_service import ConfirmPaymentService
                ConfirmPaymentService.process_payment_signal(
                    checkout_request_id=order.mpesa_checkout_request_id,
                    result_code=result.get('result_code'),
                    result_desc=result.get('result_desc', 'STK Query result'),
                    metadata=result.get('metadata', {}),
                    source='customer_stk_query',
                )
                order.refresh_from_db(fields=['payment_status'])
                if order.payment_status == 'paid':
                    return Response({'status': 'paid', 'message': 'Payment confirmed'})
                if order.payment_status == 'failed':
                    return Response({'status': 'failed', 'message': result.get('result_desc')})
            
            return Response({'status': order.payment_status, 'message': 'Still pending or query failed'})
        except Exception as e:
            logger.exception(f"Manual STK Query failed for Order {order.id}")
            return Response({'error': str(e)}, status=500)


class CustomerPaymentAttemptStatusView(APIView):
    permission_classes = [IsCustomer]
    throttle_classes = [PaymentStatusThrottle]  # 🛡️ 30 requests/hour per user (Day 2)

    def get(self, request, payment_id):
        from .models import PaymentAttempt
        cached = get_cached_status(request.user.id, payment_id)
        if cached:
            response = Response(cached)
            response['Cache-Control'] = 'private, max-age=30' if cached.get('terminal') else 'private, max-age=2'
            return response
        attempt = get_object_or_404(
            PaymentAttempt.objects.select_related('order', 'subscription_payment', 'shiriki_contribution'),
            public_payment_id=payment_id,
        )
        owner_id = (
            attempt.order.user_id if attempt.order_id else
            attempt.shiriki_contribution.user_id if attempt.shiriki_contribution_id else
            attempt.subscription_payment.store.owner_id
        )
        if owner_id != request.user.id:
            return Response({'error': 'Payment not found'}, status=status.HTTP_404_NOT_FOUND)
        target = attempt.order or attempt.shiriki_contribution or attempt.subscription_payment
        payload = {
            'payment_id': str(attempt.public_payment_id),
            'status': attempt.status,
            'amount': str(attempt.expected_amount),
            'currency': attempt.currency,
            'checkout_request_id': attempt.checkout_request_id,
            'order_id': attempt.order_id,
            'order_number': attempt.order.order_number if attempt.order_id else None,
            'reference': attempt.order.order_number if attempt.order_id else str(target.pk),
            'failure_code': attempt.failure_code,
            'failure_message': attempt.failure_message,
            'next_poll_after_seconds': next_poll_after(attempt),
            'retry_after_seconds': retry_after(attempt),
            'terminal': attempt.status in TERMINAL_PAYMENT_STATUSES,
        }
        cache_status(request.user.id, payment_id, payload, attempt.status)
        response = Response(payload)
        response['Cache-Control'] = 'private, max-age=30' if payload['terminal'] else 'private, max-age=2'
        return response

class OrderChatMessagesView(generics.ListCreateAPIView):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        order_id = self.kwargs.get('order_id')
        # Security: User must be part of the order
        user = self.request.user
        queryset = ChatMessage.objects.filter(order_id=order_id)
        
        # Flexible participant check: Allow customer, assigned rider, or the store owner
        if user.role == 'customer':
            queryset = queryset.filter(order__user=user)
        elif user.role == 'rider':
            queryset = queryset.filter(order__assigned_rider=user)
        elif user.role == 'partner':
            # Partners can view chats for their store's orders
            queryset = queryset.filter(order__store__owner=user)
        else:
            return ChatMessage.objects.none()
            
        # Optimization: Mark unread messages from OTHER as read
        ChatMessage.objects.filter(
            order_id=order_id,
            is_read=False
        ).exclude(sender=user).update(is_read=True)
            
        return queryset.order_by('created_at')

    def perform_create(self, serializer):
        order_id = self.kwargs.get('order_id')
        order = get_object_or_404(Order, id=order_id)
        
        # Security: Sender must be authorized (Customer, Assigned Rider, or Store Owner)
        is_authorized = (
            self.request.user == order.user or 
            self.request.user == order.assigned_rider or
            (order.store and self.request.user == order.store.owner)
        )
        
        if not is_authorized:
            logger.warning(f"Unauthorized chat attempt by user {self.request.user.id} for order {order_id}")
            raise permissions.PermissionDenied("You are not authorized to message on this order.")

        # Business Rule: Customer cannot message if no rider is assigned yet
        if self.request.user.role == 'customer' and order.assigned_rider is None:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'error': 'no_rider', 'message': 'No rider assigned to this order yet.'})

        msg = serializer.save(order=order, sender=self.request.user)
        
        # Trigger FCM Notification to the other party
        # If customer sends, notify rider. If rider sends, notify customer.
        recipient = order.assigned_rider if self.request.user == order.user else order.user
        
        if recipient:
            from .utils import send_fcm_notification
            send_fcm_notification(
                user=recipient,
                title=f"Message from {self.request.user.get_full_name() or self.request.user.username}",
                body=msg.message,
                data={
                    'type': 'chat',
                    'order_id': str(order.id),
                    'order_number': order.order_number
                }
            )

class CustomerRetryPaymentView(APIView):
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment_initiation'

    def post(self, request):
        order_number = request.data.get('order_number')
        if not order_number:
            return Response({'error': 'Order number required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = Order.objects.get(order_number=order_number, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        if order.payment_status == 'paid':
            return Response({'error': 'Payment already completed'}, status=status.HTTP_400_BAD_REQUEST)

        # 🛡️ IDEMPOTENCY GUARD: Prevent duplicate STK pushes within 2 minutes
        from django.core.cache import cache
        from .mpesa_utils import MpesaIntegration
        mpesa = MpesaIntegration(store=order.store)
        try:
            # Use provided phone or fallback to order's existing phone or user's phone
            raw_phone = request.data.get('mpesa_phone') or order.phone_number or request.user.phone
            
            if not raw_phone:
                return Response({'error': 'No phone number found. Please provide an M-Pesa phone number.'}, status=status.HTTP_400_BAD_REQUEST)
                
            phone = mpesa.format_phone_number(raw_phone)
            
            # Update order phone if a new one was provided for this retry
            if raw_phone:
                order.phone_number = phone
                order.save(update_fields=['phone_number'])
            
            # 🛡️ Fail-Closed Production Guard
            is_production = str(os.environ.get('MPESA_PRODUCTION', 'false')).lower() == 'true'
            amount = int(order.total) if is_production else 1
            
            key = request.headers.get('Idempotency-Key') or request.data.get('idempotency_key')
            attempt, _ = InitiatePaymentService.create_or_get_for_order(order, phone, key)
            
            return Response({
                'message': 'Retry payment initiated. Please check your phone for the M-Pesa prompt.',
                'is_async': True,
                'payment_id': str(attempt.public_payment_id),
                'payment_status': attempt.status,
                'checkout_request_id': attempt.checkout_request_id,
                'idempotency_key': attempt.idempotency_key,
            })
        except PaymentInitiationConflict as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValueError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception(f"Retry Payment failed for Order {order.order_number}")
            return Response({'error': 'An unexpected error occurred while initiating payment.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CustomerRateOrderView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, user=request.user)
        store_rating = request.data.get('store_rating')
        rider_rating = request.data.get('rider_rating')
        comment = request.data.get('comment', '')

        if not store_rating:
            return Response({'error': 'Store rating is required'}, status=status.HTTP_400_BAD_REQUEST)

        rating, created = Rating.objects.update_or_create(
            order=order,
            defaults={
                'customer': request.user,
                'store': order.store,
                'rider': order.assigned_rider,
                'store_rating': store_rating,
                'rider_rating': rider_rating,
                'comment': comment
            }
        )
        
        # Recalculate store rating
        avg = Rating.objects.filter(store=order.store).aggregate(Avg('store_rating'))['store_rating__avg']
        if avg:
            order.store.rating = avg
            order.store.rating_count = Rating.objects.filter(store=order.store).count()
            order.store.save()

        # Recalculate rider rating
        if order.assigned_rider:
            r_avg = Rating.objects.filter(rider=order.assigned_rider).aggregate(Avg('rider_rating'))['rider_rating__avg']
            if r_avg:
                order.assigned_rider.avg_rating = r_avg
                order.assigned_rider.save()

        return Response({'status': 'rating saved'})

class AvailablePromotionsView(generics.ListAPIView):
    serializer_class = PromotionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from django.utils import timezone
        store_id = self.request.query_params.get('store_id')
        if not store_id:
            return Promotion.objects.none()
        
        return Promotion.objects.filter(
            store_id=store_id,
            is_active=True,
            start_date__lte=timezone.now(),
            end_date__gte=timezone.now()
        ).filter(
            Q(usage_limit__isnull=True) | Q(times_used__lt=F('usage_limit'))
        )

class ValidatePromotionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        code = request.data.get('code')
        store_id = request.data.get('store_id')
        subtotal = float(request.data.get('subtotal', 0))

        if not code or not store_id:
            return Response({'error': 'Code and store_id are required'}, status=400)

        promo = Promotion.objects.filter(
            store_id=store_id,
            code__iexact=code,
            is_active=True,
            start_date__lte=timezone.now(),
            end_date__gte=timezone.now()
        ).first()

        if not promo:
            return Response({'error': 'Invalid or expired promo code'}, status=400)

        if promo.usage_limit and promo.times_used >= promo.usage_limit:
            return Response({'error': 'This promo code has reached its usage limit'}, status=400)

        if subtotal < float(promo.min_order_amount):
            diff = float(promo.min_order_amount) - subtotal
            return Response({
                'error': f'Minimum order amount for this promo is KSh {promo.min_order_amount}. Add KSh {int(diff)} more to unlock this offer.'
            }, status=400)

        # Calculate discount
        discount = 0
        if promo.discount_percentage:
            discount = subtotal * (float(promo.discount_percentage) / 100)
        elif promo.discount_amount:
            discount = float(promo.discount_amount)

        return Response({
            'success': True,
            'discount_amount': discount,
            'promo_id': promo.id,
            'title': promo.title
        })

class CustomerPlaceOrderView(APIView):
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment_initiation'

    def post(self, request):
        # 🛡️ Age Verification Guard
        user = request.user
        risk = calculate_risk_score(user, request.data)
        user.risk_score = risk
        user.save(update_fields=['risk_score'])

        if not user.is_age_verified:
            # 🚀 Progressive Friction: 
            # If risk is VERY high (85+), block immediately.
            # If risk is Moderate (40-84), allow payment BUT mark order for Post-Order Verification.
            if risk >= 85:
                return Response({
                    'error': 'age_verification_required',
                    'message': 'Quick check to continue! Please verify your age to complete this order.',
                    'risk_score': risk,
                    'is_immediate': True
                }, status=status.HTTP_403_FORBIDDEN)
            
        data = request.data
        items_data = data.get('items', [])
        if not items_data:
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        request_key = request.headers.get('Idempotency-Key') or data.get('idempotency_key')
        try:
            validate_idempotency_key(request_key)
        except ValueError as exc:
            return Response({'error': 'invalid_idempotency_key', 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        request_fingerprint = order_request_fingerprint(data) if request_key else None
        if request_key:
            existing_order = Order.objects.filter(payment_idempotency_key=request_key).first()
            if existing_order:
                if existing_order.user_id != request.user.id:
                    return Response({'error': 'idempotency_key_conflict'}, status=status.HTTP_409_CONFLICT)
                if existing_order.idempotency_fingerprint and existing_order.idempotency_fingerprint != request_fingerprint:
                    return Response({'error': 'idempotency_key_payload_conflict'}, status=status.HTTP_409_CONFLICT)
                attempt = existing_order.payment_attempts.order_by('-created_at').first()
                response_data = OrderSerializer(existing_order).data
                if not attempt and existing_order.payment_method == 'mpesa' and existing_order.total > 0:
                    attempt, _ = InitiatePaymentService.create_or_get_for_order(
                        existing_order, data.get('mpesa_phone') or request.user.phone, request_key
                    )
                if attempt:
                    response_data.update({
                        'payment_id': str(attempt.public_payment_id),
                        'payment_status': attempt.status,
                        'checkout_request_id': attempt.checkout_request_id,
                        'idempotency_key': attempt.idempotency_key,
                        'is_async': True,
                    })
                return Response(response_data, status=status.HTTP_200_OK)

        try:
            with transaction.atomic():
                # Get the first item to resolve the store
                first_item_id = items_data[0].get('product_id')
                first_food_item = get_object_or_404(FoodItem, id=first_item_id)
                store = first_food_item.store

                if not store:
                    return Response({'error': 'Store not found for items'}, status=status.HTTP_400_BAD_REQUEST)

                # 🛡️ Wallet Accept Check
                if data.get('use_wallet') and not store.accepts_wallet_payments:
                    return Response({
                        'error': 'wallet_not_accepted',
                        'message': f'{store.name} does not accept Tipsy Wallet payments currently.'
                    }, status=status.HTTP_400_BAD_REQUEST)

                # 🛡️ Distance Radius Enforcement
                u_lat = data.get('latitude')
                u_lng = data.get('longitude')
                if u_lat and u_lng and store.latitude and store.longitude:
                    from .utils import haversine_distance_km
                    dist = haversine_distance_km(u_lat, u_lng, store.latitude, store.longitude)
                    if dist > store.delivery_radius_km:
                        return Response({
                            'error': 'out_of_radius',
                            'message': f'This store only delivers within {store.delivery_radius_km}KM. You are approximately {dist:.1f}KM away.',
                            'distance': dist,
                            'radius': store.delivery_radius_km
                        }, status=status.HTTP_400_BAD_REQUEST)

                # Calculate totals and validate single store and stock
                subtotal = 0
                order_items_to_create = []
                for item in items_data:
                    food_item = get_object_or_404(FoodItem, id=item.get('product_id'))
                    
                    if food_item.store != store:
                        return Response(
                            {'error': f'Cart contains items from multiple stores ({store.name} and {food_item.store.name}).'}, 
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    requested_quantity = item.get('quantity', 1)
                    
                    # 🛡️ Stock Validation: Only charge for what is in stock
                    requested_quantity = int(requested_quantity)
                    if requested_quantity <= 0:
                        return Response({'error': 'Invalid item quantity.'}, status=status.HTTP_400_BAD_REQUEST)
                    actual_quantity = requested_quantity
                    
                    if actual_quantity <= 0:
                        continue # Skip items that went out of stock
                    
                    subtotal += food_item.price * actual_quantity
                    
                    order_items_to_create.append(OrderItem(
                        food_item=food_item,
                        quantity=actual_quantity,
                        price_at_order=food_item.price
                    ))

                if not order_items_to_create:
                    return Response({'error': 'All items in your cart are currently out of stock.'}, status=status.HTTP_400_BAD_REQUEST)

                # Handle Promotion
                promo_code = data.get('promo_code')
                promo = None
                discount_amount = 0
                if promo_code:
                    from django.utils import timezone
                    promo = Promotion.objects.filter(
                        store=store,
                        code__iexact=promo_code,
                        is_active=True,
                        start_date__lte=timezone.now(),
                        end_date__gte=timezone.now()
                    ).first()

                    if promo:
                        from .promotion_service import PromotionReservationService
                        promo, discount_amount = PromotionReservationService.reserve(
                            promo.id, Decimal(str(subtotal))
                        )
                        discount_amount = float(discount_amount)
                    else:
                        logger.warning(f"Invalid promo code provided: {promo_code}")

                # 🛡️ DYNAMIC DELIVERY FEE Logic
                # Instead of the legacy store.delivery_fee, we calculate it based on distance
                from .utils import calculate_delivery_fee
                delivery_fee = calculate_delivery_fee(
                    data.get('latitude'), 
                    data.get('longitude'), 
                    store.latitude, 
                    store.longitude, 
                    store=store
                )

                total = float(subtotal) + float(delivery_fee) - discount_amount
                
                # 👛 Tipsy Wallet Logic
                wallet_used = 0
                if data.get('use_wallet'):
                    from .ledger_service import FinancialLedgerService
                    from .models import WalletLedger
                    user.refresh_from_db(fields=['wallet_balance'])
                    available_wallet = float(user.wallet_balance)
                if data.get('use_wallet') and available_wallet > 0:
                    if available_wallet >= total:
                        wallet_used = total
                        total = 0
                    else:
                        wallet_used = available_wallet
                        total = total - wallet_used
                    FinancialLedgerService.wallet_entry(
                        user.id, WalletLedger.EntryType.DEBIT, wallet_used,
                        'order_wallet_debit', request_key or uuid.uuid4(),
                        f'order-wallet-{request_key or uuid.uuid4()}',
                    )

                if total < 0: total = 0

                # 🛡️ Tiered Verification Logic (Progressive Friction)
                # Auto-require for high-value (>15k) OR users flagged by risk engine
                requires_verification = (subtotal >= 15000) or (not user.is_age_verified and risk >= 40)

                # Initial status is 'payment_pending' if M-Pesa is used, otherwise 'pending' for Cash
                initial_status = 'pending'
                if data.get('payment_method') == 'mpesa' and total > 0:
                    initial_status = 'payment_pending'

                idempotency_key = request_key

                order = Order.objects.create(
                    user=request.user,
                    store=store,
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    rider_base_fare=delivery_fee, # 💰 Align rider pay with delivery fee
                    promo_code=promo_code if discount_amount > 0 else None,
                    discount_amount=discount_amount,
                    total=total,
                    latitude=data.get('latitude'),
                    longitude=data.get('longitude'),
                    address_string=data.get('address_string'),
                    status=initial_status,
                    wallet_used=wallet_used,
                    payment_status='paid' if total == 0 else 'pending', # Auto-pay if wallet covered everything
                    payment_method=data.get('payment_method', 'mpesa'),
                    requires_rider_verification=requires_verification,
                    payment_idempotency_key=idempotency_key,
                    idempotency_fingerprint=request_fingerprint,
                )

                from .inventory_service import InventoryReservationService
                InventoryReservationService.reserve_order(
                    order,
                    [(item.food_item_id, item.quantity) for item in order_items_to_create],
                )

                if promo and discount_amount > 0:
                    from .models import PromotionRedemption
                    PromotionRedemption.objects.create(
                        promotion=promo,
                        order=order,
                        code=promo.code,
                        discount_amount=Decimal(str(discount_amount)),
                    )

                for item in order_items_to_create:
                    item.order = order
                    item.save()

                OrderStatusHistory.objects.create(
                    order=order,
                    status=initial_status,
                    notes='Order placed from mobile app.'
                )

                response_data = OrderSerializer(order).data

            is_shiriki = data.get('is_shiriki', False)

            # --- ASYNC CHECKOUT Logic (High-Concurrency Ready) ---
            if order.payment_method == 'mpesa' and order.total > 0 and not is_shiriki:
                logger.info(f"Queuing STK Push Task for Order {order.order_number}, User {request.user.id}")
                
                raw_phone = data.get('mpesa_phone') or request.user.phone
                logger.info(f"STK Phone: {raw_phone}, Idempotency Key: {idempotency_key}")
                
                try:
                    attempt, _ = InitiatePaymentService.create_or_get_for_order(
                        order, raw_phone, idempotency_key
                    )
                    logger.info(f"✅ Payment attempt created: {attempt.public_payment_id}, status={attempt.status}, checkout_id={attempt.checkout_request_id}")
                    
                    response_data['message'] = "Payment processing started. Please look out for the M-Pesa prompt."
                    response_data['is_async'] = True
                    response_data['payment_id'] = str(attempt.public_payment_id)
                    response_data['payment_status'] = attempt.status
                    response_data['checkout_request_id'] = attempt.checkout_request_id
                    response_data['idempotency_key'] = attempt.idempotency_key
                except Exception as e:
                    logger.error(f"❌ STK initiation failed for Order {order.order_number}: {type(e).__name__}: {str(e)}", exc_info=True)
                    return Response(
                        {'error': 'payment_initiation_failed', 'message': str(e)},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            return Response(response_data, status=status.HTTP_201_CREATED)

        except IntegrityError:
            if request_key:
                existing_order = Order.objects.filter(payment_idempotency_key=request_key).first()
                if existing_order and existing_order.user_id == request.user.id:
                    if existing_order.idempotency_fingerprint and existing_order.idempotency_fingerprint != request_fingerprint:
                        return Response({'error': 'idempotency_key_payload_conflict'}, status=status.HTTP_409_CONFLICT)
                    attempt = existing_order.payment_attempts.order_by('-created_at').first()
                    if not attempt and existing_order.payment_method == 'mpesa' and existing_order.total > 0:
                        attempt, _ = InitiatePaymentService.create_or_get_for_order(
                            existing_order, data.get('mpesa_phone') or request.user.phone, request_key
                        )
                    response_data = OrderSerializer(existing_order).data
                    if attempt:
                        response_data.update({
                            'payment_id': str(attempt.public_payment_id),
                            'payment_status': attempt.status,
                            'checkout_request_id': attempt.checkout_request_id,
                            'idempotency_key': attempt.idempotency_key,
                            'is_async': True,
                        })
                    return Response(response_data, status=status.HTTP_200_OK)
                if existing_order:
                    return Response({'error': 'idempotency_key_conflict'}, status=status.HTTP_409_CONFLICT)
            logger.exception('Order idempotency conflict could not be recovered')
            return Response({'error': 'order_conflict'}, status=status.HTTP_409_CONFLICT)
        except Exception as e:
            from .inventory_service import InventoryConflict
            if isinstance(e, InventoryConflict):
                return Response({'error': 'out_of_stock', 'message': str(e)}, status=status.HTTP_409_CONFLICT)
            logger.exception(f"Order Creation Failed for user {request.user.username}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ShirikiCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'shiriki_session'

    def post(self, request):
        order_number = request.data.get('order_number')
        if not order_number:
            return Response({'error': 'Order number required'}, status=400)
            
        try:
            order = Order.objects.get(order_number=order_number, user=request.user, payment_status='pending')
        except Order.DoesNotExist:
            return Response({'error': 'Order not found or already paid'}, status=404)
            
        try:
            session = ShirikiService.create_session(order.id, request.user.id)
        except ShirikiSessionConflict as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        
        return Response(ShirikiSessionSerializer(session).data, status=201)

class ShirikiSessionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, invite_code):
        try:
            session = ShirikiSession.objects.get(invite_code=invite_code)
        except ShirikiSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=404)
            
        return Response(ShirikiSessionSerializer(session).data)

class ShirikiContributeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment_initiation'

    def post(self, request):
        invite_code = request.data.get('invite_code')
        amount = request.data.get('amount')
        phone = request.data.get('phone')

        if not all([invite_code, amount, phone]):
            return Response({'error': 'Missing required fields'}, status=400)

        request_key = request.headers.get('Idempotency-Key') or request.data.get('idempotency_key')
        if request_key:
            existing_contribution = ShirikiContribution.objects.filter(
                user=request.user, payment_idempotency_key=request_key
            ).first()
            if existing_contribution:
                attempt = existing_contribution.payment_attempts.order_by('-created_at').first()
                return Response({
                    'success': True,
                    'contribution_id': existing_contribution.id,
                    'payment_id': str(attempt.public_payment_id) if attempt else None,
                    'payment_status': attempt.status if attempt else existing_contribution.status,
                    'checkout_request_id': attempt.checkout_request_id if attempt else existing_contribution.checkout_request_id,
                    'idempotency_key': request_key,
                    'is_async': True,
                }, status=200)

        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                raise ValueError
        except (ValueError, InvalidOperation):
            return Response({'error': 'Invalid amount'}, status=400)

        try:
            with transaction.atomic():
                try:
                    session = ShirikiSession.objects.select_for_update().get(
                        invite_code=invite_code, status='active'
                    )
                except ShirikiSession.DoesNotExist:
                    return Response({'error': 'Active session not found'}, status=404)

                # 🛡️ FIX: Calculate 'In-Flight' contributions to prevent overflow.
                # We subtract both CONFIRMED and RECENT PENDING (less than 2 mins old) contributions.
                from django.utils import timezone
                from datetime import timedelta
                
                if session.contributions.filter(status='pending').count() >= ShirikiService.MAX_ACTIVE_PENDING_CONTRIBUTIONS:
                    return Response({'error': 'This Shiriki pot has reached its pending payment limit'}, status=409)

                # Sum of confirmed payments
                confirmed_sum = session.contributions.filter(
                    status='confirmed'
                ).aggregate(Sum('amount_applied_to_pot'))['amount_applied_to_pot__sum'] or Decimal('0')

                # Sum of pending payments that haven't timed out yet
                pending_sum = session.contributions.filter(
                    status='pending'
                ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

                total_reserved = confirmed_sum + pending_sum
                remaining = session.order.total - total_reserved

                if amount > (remaining + Decimal('0.01')):
                    return Response(
                        {
                            'error': f'Amount exceeds remaining available balance of {max(0, float(remaining))}. '
                                     f'(Note: KSh {float(pending_sum)} is currently reserved by other pending payments).',
                            'remaining': max(0, float(remaining))
                        }, 
                        status=400
                    )

                contribution = ShirikiContribution.objects.create(
                    session=session,
                    user=request.user,
                    amount=amount,
                    phone_number=phone,
                    payment_idempotency_key=request_key,
                    status='pending'
                )
        except Exception:
            logger.exception("Error creating Shiriki contribution")
            return Response({'error': 'Something went wrong. Please try again.'}, status=500)

        key = request_key
        try:
            attempt, _ = InitiatePaymentService.create_or_get_for_contribution(contribution, phone, key)
        except PaymentInitiationConflict as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response({
            'success': True,
            'contribution_id': contribution.id,
            'message': f'Contribution of KSh {amount} initiated. Please enter your PIN.',
            'is_async': True,
            'payment_id': str(attempt.public_payment_id),
            'payment_status': attempt.status,
            'checkout_request_id': attempt.checkout_request_id,
            'idempotency_key': attempt.idempotency_key,
        })
