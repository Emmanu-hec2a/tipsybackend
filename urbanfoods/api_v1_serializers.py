from rest_framework import serializers
from django.utils import timezone
import datetime
from .models import User, Store, Order, OrderItem, FoodItem, Rating, RiderEarning, FoodCategory, Promotion, SubscriptionPayment, SavedAddress, RiderLocationPing

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'phone', 'first_name', 'last_name', 
            'role', 'loyalty_points', 'wallet_balance', 'profile_picture'
        ]
        read_only_fields = ['loyalty_points', 'wallet_balance', 'role']

class RiderProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'phone', 'first_name', 'last_name', 
            'role', 'loyalty_points', 'profile_picture', 'is_available', 
            'avg_rating', 'total_deliveries',
            'bank_name', 'bank_account_name', 'bank_account_number'
        ]
        read_only_fields = ['avg_rating', 'total_deliveries', 'loyalty_points', 'role']

class StoreSerializer(serializers.ModelSerializer):
    distance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, required=False)
    is_favourite = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()
    
    # User fields (Writable)
    bank_name = serializers.CharField(source='owner.bank_name', required=False, allow_blank=True)
    bank_account_name = serializers.CharField(source='owner.bank_account_name', required=False, allow_blank=True)
    bank_account_number = serializers.CharField(source='owner.bank_account_number', required=False, allow_blank=True)
    phone = serializers.CharField(source='owner.phone', required=False, allow_blank=True)
    email = serializers.EmailField(source='owner.email', required=False, allow_blank=True)
    address_string = serializers.CharField(source='owner.business_location', required=False, allow_blank=True)
    
    class Meta:
        model = Store
        fields = [
            'id', 'name', 'shop_name', 'logo', 'tagline', 'primary_color',
            'rating', 'rating_count', 'delivery_fee', 'avg_delivery_minutes',
            'latitude', 'longitude', 'is_pro', 'is_favourite', 'distance',
            'bank_name', 'bank_account_name', 'bank_account_number',
            'phone', 'email', 'address_string',
            'opening_time', 'closing_time', 'is_open', 'plan', 'plan_price',
            'subscription_expires', 'billing_status',
            'payhero_username', 'payhero_api_key', 'payhero_account_number',
            'payment_provider', 'flutterwave_enabled', 'flutterwave_currency'
        ]
        read_only_fields = ['owner', 'rating', 'rating_count']

    def get_is_open(self, obj):
        now = timezone.localtime().time()
        if obj.opening_time and obj.closing_time:
            if obj.opening_time <= obj.closing_time:
                return obj.opening_time <= now <= obj.closing_time
            else: # Overnight case
                return now >= obj.opening_time or now <= obj.closing_time
        return True # Default to open if no hours set

    def get_is_favourite(self, obj):
        request = self.context.get('request')
        if not request:
            return False
        user = request.user
        if user and user.is_authenticated:
            return user.favourite_stores.filter(id=obj.id).exists()
        return False

    def update(self, instance, validated_data):
        # Extract owner data (source fields map to 'owner' dict in validated_data if using dots)
        owner_data = validated_data.pop('owner', {})
        owner = instance.owner
        
        # Update owner fields
        for attr, value in owner_data.items():
            setattr(owner, attr, value)
        owner.save()
        
        # Update store fields
        return super().update(instance, validated_data)

class FoodCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = FoodCategory
        fields = '__all__'

class FoodItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category_fkey.name', read_only=True)
    class Meta:
        model = FoodItem
        fields = [
            'id', 'name', 'description', 'category', 'category_fkey', 'category_name',
            'sku', 'price', 'original_price', 'discount_percent', 'stock',
            'low_stock_threshold', 'image', 'prep_time', 'is_available', 'is_active',
            'store_type', 'bottle_size', 'store', 'is_new_arrival'
        ]
        read_only_fields = ['store']

class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='food_item.name', read_only=True)
    class Meta:
        model = OrderItem
        fields = ['id', 'food_item', 'product_name', 'quantity', 'price_at_order', 'subtotal']

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='user.username', read_only=True)
    customer_phone = serializers.CharField(source='user.phone', read_only=True)
    customer_email = serializers.EmailField(source='user.email', read_only=True)
    rider_name = serializers.CharField(source='assigned_rider.username', read_only=True, allow_null=True)
    
    # Rider current location
    rider_latitude = serializers.SerializerMethodField()
    rider_longitude = serializers.SerializerMethodField()

    def get_rider_latitude(self, obj):
        if obj.assigned_rider:
            last_ping = RiderLocationPing.objects.filter(rider=obj.assigned_rider).order_by('-created_at').first()
            if last_ping:
                return last_ping.latitude
        return None

    def get_rider_longitude(self, obj):
        if obj.assigned_rider:
            last_ping = RiderLocationPing.objects.filter(rider=obj.assigned_rider).order_by('-created_at').first()
            if last_ping:
                return last_ping.longitude
        return None

    # Store coordinates for pickup
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_latitude = serializers.DecimalField(source='store.latitude', max_digits=9, decimal_places=6, read_only=True)
    store_longitude = serializers.DecimalField(source='store.longitude', max_digits=9, decimal_places=6, read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer_name', 'customer_phone', 'customer_email', 'rider_name', 'status', 
            'payment_status', 'payment_method', 'total', 'latitude', 'longitude', 'address_string',
            'google_maps_link', 'created_at', 'items', 'delivery_fee', 'tip_amount',
            'store_name', 'store_latitude', 'store_longitude',
            'rider_latitude', 'rider_longitude'
        ]
        read_only_fields = ['order_number', 'created_at']

class PromotionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promotion
        fields = '__all__'

class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPayment
        fields = '__all__'

class RiderEarningSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiderEarning
        fields = '__all__'

class SavedAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedAddress
        fields = '__all__'
        read_only_fields = ['user']
