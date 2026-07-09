from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.db.models import Q, F, ExpressionWrapper, DecimalField, Avg
from django.db.models.functions import Sqrt, Power
from .models import Store, FoodItem, Order, Rating, SavedAddress, OrderItem, OrderStatusHistory, FoodCategory
from .api_v1_serializers import StoreSerializer, FoodItemSerializer, OrderSerializer, UserSerializer, SavedAddressSerializer, FoodCategorySerializer
from .permissions import IsCustomer
from django.utils import timezone
from django.db import transaction

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
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CustomerStoreListView(generics.ListAPIView):
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Base queryset: active stores, prioritize Pro stores first
        queryset = Store.objects.filter(is_active=True).order_by('-is_pro', 'name')
        
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
                
        return queryset

class CustomerStoreDetailView(generics.RetrieveAPIView):
    queryset = Store.objects.all()
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

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
        # Prioritize products from Pro stores
        queryset = FoodItem.objects.filter(is_active=True).order_by('-store__is_pro', 'name')
        
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

                # Calculate totals
                subtotal = 0
                order_items_to_create = []
                for item in items_data:
                    food_item = get_object_or_404(FoodItem, id=item.get('product_id'))
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

                order = Order.objects.create(
                    user=request.user,
                    store=store,
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    total=total,
                    latitude=data.get('latitude'),
                    longitude=data.get('longitude'),
                    address_string=data.get('address_string'),
                    status='pending',
                    payment_status='pending',
                    payment_method=data.get('payment_method', 'mpesa')
                )

                for item in order_items_to_create:
                    item.order = order
                    item.save()

                OrderStatusHistory.objects.create(
                    order=order,
                    status='pending',
                    notes='Order placed from mobile app.'
                )

                return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
