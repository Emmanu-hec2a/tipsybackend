from rest_framework import generics, permissions, status
from datetime import date
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import os
from django.shortcuts import get_object_or_404
from django.db.models import Q, F, ExpressionWrapper, DecimalField, Avg, Exists, OuterRef, Value, BooleanField, Count
from django.db.models.functions import Sqrt, Power
from .models import Store, FoodItem, Order, Rating, SavedAddress, OrderItem, OrderStatusHistory, FoodCategory, Promotion, ChatMessage
from .api_v1_serializers import StoreSerializer, FoodItemSerializer, OrderSerializer, UserSerializer, SavedAddressSerializer, FoodCategorySerializer, PromotionSerializer, ChatMessageSerializer
from .permissions import IsCustomer
from .mpesa_utils import MpesaIntegration
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db import transaction
from .utils import calculate_risk_score
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
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        logger.warning(f"Profile Update Failed for {request.user.username}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(cache_page(60*5), name='dispatch')
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

        queryset = queryset.order_by('-is_pro', 'name')
        
        # Get coordinates from query params
        lat = self.request.query_params.get('lat')
        lng = self.request.query_params.get('lng')
        is_pro_only = self.request.query_params.get('is_pro_only')

        if is_pro_only == 'true':
            queryset = queryset.filter(is_pro=True)

        if lat and lng:
            try:
                u_lat = float(lat)
                u_lng = float(lng)
                
                # Annotate distance
                # We still keep -is_pro as the primary sort, then distance
                queryset = queryset.annotate(
                    distance=ExpressionWrapper(
                        Sqrt(Power(F('latitude') - u_lat, 2) + Power(F('longitude') - u_lng, 2)) * 111,
                        output_field=DecimalField()
                    )
                ).order_by('-is_pro', 'distance')
            except ValueError:
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
        return self.request.user.favourite_stores.filter(is_active=True)

class CustomerRedeemPointsView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request):
        user = request.user
        points = user.loyalty_points
        
        if points < 1000:
            return Response({'error': 'Minimum 1,000 points required to redeem.'}, status=400)
        
        # 100 points = 1 KSh
        redeem_value = points / 100
        
        user.loyalty_points = 0
        user.wallet_balance = F('wallet_balance') + redeem_value
        user.save()
        user.refresh_from_db()
        
        return Response({
            'message': f'Successfully redeemed {points} points for KSh {redeem_value}.',
            'new_balance': user.wallet_balance,
            'new_points': user.loyalty_points
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
        
        # Identify stores that are restricted due to debt
        # (This is a simplified check for performance, normally you'd use a flag or cache)
        restricted_store_ids = WeeklyRevenueStat.objects.filter(
            week_end__lt=today,
            is_paid=False,
            partner_share_40__gt=0
        ).values('store').annotate(unpaid_count=Count('id')).filter(unpaid_count__gte=2).values_list('store_id', flat=True)

        # Base filter: products from active stores with valid subscriptions (or inherited franchise validity)
        from django.db.models import Q
        queryset = FoodItem.objects.filter(
            Q(is_active=True, store__is_active=True, store__billing_status='active', store__subscription_expires__gte=date.today()) |
            Q(is_active=True, store__is_active=True, store__is_franchise=True, store__parent_store__billing_status='active', store__parent_store__subscription_expires__gte=date.today())
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
        return Order.objects.filter(user=self.request.user).order_by('-created_at')

class CustomerOrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)

class OrderChatMessagesView(generics.ListCreateAPIView):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        order_id = self.kwargs.get('order_id')
        # Security: Customer or Rider must be part of the order
        user = self.request.user
        queryset = ChatMessage.objects.filter(order_id=order_id)
        
        if user.role == 'customer':
            queryset = queryset.filter(order__user=user)
        elif user.role == 'rider':
            queryset = queryset.filter(order__assigned_rider=user)
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
        
        # Security: Sender must be the customer or the assigned rider
        if self.request.user != order.user and self.request.user != order.assigned_rider:
            raise permissions.PermissionDenied("You are not authorized to message on this order.")

        # Security: If no rider is assigned, customer cannot message
        # Use simple presence check for assigned_rider
        if order.assigned_rider is None and self.request.user.role == 'customer':
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'error': 'No rider assigned to this order yet.'})

        msg = serializer.save(order=order, sender=self.request.user)
        
        # Trigger FCM Notification to the other party
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

        from .mpesa_utils import MpesaIntegration
        mpesa = MpesaIntegration(store=order.store)
        try:
            # Use provided phone or fallback to order's existing phone
            raw_phone = request.data.get('mpesa_phone') or order.phone_number
            phone = mpesa.format_phone_number(raw_phone)
            
            # Update order phone if a new one was provided for this retry
            if raw_phone and phone != order.phone_number:
                order.phone_number = phone
                order.save(update_fields=['phone_number'])
            
            # Use a small amount for testing if not production
            is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
            amount = int(order.total) if is_production else 1
            
            stk_result = mpesa.initiate_stk_push(
                phone_number=phone,
                amount=amount,
                account_reference=f"ORD-{order.order_number}",
                transaction_desc=f"Retry Payment {order.order_number}"
            )
            
            if stk_result.get('success'):
                order.mpesa_checkout_request_id = stk_result.get('checkout_request_id')
                order.save(update_fields=['mpesa_checkout_request_id'])
                return Response({
                    'checkout_request_id': stk_result.get('checkout_request_id'),
                    'message': 'M-Pesa STK push initiated successfully.'
                })
            else:
                return Response({'error': stk_result.get('message')}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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

    def post(self, request):
        # 🛡️ Age Verification Guard
        user = request.user
        if not user.is_age_verified:
            # Check if this specific order requires immediate verification
            # (High value or High risk profile)
            risk = calculate_risk_score(user, request.data)
            user.risk_score = risk
            user.save(update_fields=['risk_score'])
            
            if risk >= 70: # High threshold for immediate block/escalation
                return Response({
                    'error': 'age_verification_required',
                    'message': 'Quick check to continue! Please verify your age to complete this order.',
                    'risk_score': risk
                }, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        items_data = data.get('items', [])
        if not items_data:
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

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

                # Calculate totals and validate single store
                subtotal = 0
                order_items_to_create = []
                for item in items_data:
                    food_item = get_object_or_404(FoodItem, id=item.get('product_id'))
                    
                    if food_item.store != store:
                        return Response(
                            {'error': f'Cart contains items from multiple stores ({store.name} and {food_item.store.name}).'}, 
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    quantity = item.get('quantity', 1)
                    subtotal += food_item.price * quantity
                    
                    order_items_to_create.append(OrderItem(
                        food_item=food_item,
                        quantity=quantity,
                        price_at_order=food_item.price
                    ))

                # Handle Promotion
                promo_code = data.get('promo_code')
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
                        # Check usage limit
                        if not promo.usage_limit or promo.times_used < promo.usage_limit:
                            # Check min order
                            if subtotal >= float(promo.min_order_amount):
                                if promo.discount_percentage:
                                    discount_amount = float(subtotal) * (float(promo.discount_percentage) / 100)
                                elif promo.discount_amount:
                                    discount_amount = float(promo.discount_amount)
                                
                                # Increment usage
                                promo.times_used = F('times_used') + 1
                                promo.save()
                            else:
                                logger.warning(f"Promo {promo_code} skipped: Subtotal {subtotal} < min {promo.min_order_amount}")
                        else:
                            logger.warning(f"Promo {promo_code} skipped: Usage limit reached")
                    else:
                        logger.warning(f"Invalid promo code provided: {promo_code}")

                # Dynamic delivery fee from store
                delivery_fee = store.delivery_fee
                total = float(subtotal) + float(delivery_fee) - discount_amount
                
                # 👛 Tipsy Wallet Logic
                wallet_used = 0
                if data.get('use_wallet') and user.wallet_balance > 0:
                    available_wallet = float(user.wallet_balance)
                    if available_wallet >= total:
                        wallet_used = total
                        total = 0
                        user.wallet_balance = available_wallet - wallet_used
                    else:
                        wallet_used = available_wallet
                        total = total - wallet_used
                        user.wallet_balance = 0
                    
                    user.save(update_fields=['wallet_balance'])
                    logger.info(f"User {user.username} used KSh {wallet_used} from wallet. New balance: {user.wallet_balance}")

                if total < 0: total = 0

                # 🛡️ Tiered Verification Logic
                risk = calculate_risk_score(request.user, data)
                # Auto-require for high-value (>15k) OR medium-risk users
                requires_verification = (subtotal >= 15000) or (risk >= 40)

                # Initial status is 'payment_pending' if M-Pesa is used, otherwise 'pending' for Cash
                initial_status = 'payment_pending' if data.get('payment_method') == 'mpesa' else 'pending'

                order = Order.objects.create(
                    user=request.user,
                    store=store,
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
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
                    requires_rider_verification=requires_verification
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

            # --- OUTSIDE TRANSACTION ---
            # Trigger M-Pesa STK Push if method is mpesa
            if order.payment_method == 'mpesa':
                logger.info(f"Triggering STK Push for Order {order.order_number} (ID: {order.id})")
                try:
                    mpesa = MpesaIntegration(store=order.store)
                    
                    # Use provided mpesa_phone or fallback to user.phone
                    raw_phone = data.get('mpesa_phone') or request.user.phone
                    phone = mpesa.format_phone_number(raw_phone)
                    
                    # Update order with the phone used for payment
                    order.phone_number = phone 
                    order.save(update_fields=['phone_number'])
                    
                    # Use a small amount for testing if not production
                    is_production = str(os.environ.get('MPESA_PRODUCTION', 'false')).lower() == 'true'
                    amount = int(order.total) if is_production else 1
                    
                    logger.info(f"Initiating STK: Phone={phone}, Amount={amount}, Store={order.store.name}")
                    
                    stk_result = mpesa.initiate_stk_push(
                        phone_number=phone,
                        amount=amount,
                        account_reference=f"ORD-{order.order_number}",
                        transaction_desc=f"Payment for Order {order.order_number}"
                    )
                    
                    if stk_result.get('success'):
                        order.mpesa_checkout_request_id = stk_result.get('checkout_request_id')
                        order.save(update_fields=['mpesa_checkout_request_id'])
                        response_data['checkout_request_id'] = stk_result.get('checkout_request_id')
                        response_data['message'] = "M-Pesa STK push initiated successfully."
                        logger.info(f"STK Push Success: {order.mpesa_checkout_request_id}")
                    else:
                        error_msg = stk_result.get('message', 'Unknown M-Pesa error')
                        response_data['mpesa_error'] = error_msg
                        logger.error(f"STK Push Failed: {error_msg}")
                except Exception as mpesa_err:
                    response_data['mpesa_error'] = str(mpesa_err)
                    logger.exception(f"STK Push Exception for Order {order.order_number}")

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
