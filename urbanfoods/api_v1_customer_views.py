from rest_framework import generics, permissions, status
from datetime import date
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import os
from django.shortcuts import get_object_or_404
from django.db.models import Q, F, ExpressionWrapper, DecimalField, Avg, Exists, OuterRef, Value, BooleanField
from django.db.models.functions import Sqrt, Power
from .models import Store, FoodItem, Order, Rating, SavedAddress, OrderItem, OrderStatusHistory, FoodCategory
from .api_v1_serializers import StoreSerializer, FoodItemSerializer, OrderSerializer, UserSerializer, SavedAddressSerializer, FoodCategorySerializer
from .permissions import IsCustomer
from .mpesa_utils import MpesaIntegration
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db import transaction
from .utils import calculate_risk_score

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
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(cache_page(60*5), name='dispatch')
class CustomerStoreListView(generics.ListAPIView):
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Base queryset: active stores with valid subscriptions, prioritize Pro stores first
        queryset = Store.objects.filter(
            is_active=True, 
            subscription_expires__gte=date.today(),
            billing_status='active'
        ).select_related('owner')
        
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
        return Store.objects.filter(
            is_active=True, 
            subscription_expires__gte=date.today(),
            billing_status='active'
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
        queryset = FoodItem.objects.filter(
            is_active=True,
            store__is_active=True,
            store__subscription_expires__gte=date.today(),
            store__billing_status='active'
        ).order_by('-store__is_pro', 'name')
        
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

                # Dynamic delivery fee from store
                delivery_fee = store.delivery_fee
                total = subtotal + delivery_fee

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
                    total=total,
                    latitude=data.get('latitude'),
                    longitude=data.get('longitude'),
                    address_string=data.get('address_string'),
                    status=initial_status,
                    payment_status='pending',
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

                # Trigger M-Pesa STK Push if method is mpesa
                if order.payment_method == 'mpesa':
                    try:
                        mpesa = MpesaIntegration(store=order.store)
                        phone = mpesa.format_phone_number(request.user.phone)
                        
                        # Use a small amount for testing if not production
                        is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
                        amount = int(order.total) if is_production else 1
                        
                        stk_result = mpesa.initiate_stk_push(
                            phone_number=phone,
                            amount=amount,
                            account_reference=f"ORD-{order.order_number}",
                            transaction_desc=f"Payment for Order {order.order_number}"
                        )
                        
                        if stk_result.get('success'):
                            order.checkout_request_id = stk_result.get('checkout_request_id')
                            order.save()
                            response_data['checkout_request_id'] = stk_result.get('checkout_request_id')
                            response_data['message'] = "M-Pesa STK push initiated successfully."
                        else:
                            response_data['mpesa_error'] = stk_result.get('message')
                    except Exception as mpesa_err:
                        response_data['mpesa_error'] = str(mpesa_err)

                return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
