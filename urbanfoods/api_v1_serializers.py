from rest_framework import serializers
from django.utils import timezone
import datetime
from .models import User, Store, Order, OrderItem, FoodItem, Rating, RiderEarning, FoodCategory, Promotion, SubscriptionPayment, SavedAddress, RiderLocationPing

from django.core.cache import cache

class UserSerializer(serializers.ModelSerializer):
    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user
        user_qs = User.objects.filter(phone=normalized)
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'phone', 'first_name', 'last_name', 
            'role', 'loyalty_points', 'wallet_balance', 'profile_picture',
            'is_age_verified', 'risk_score'
        ]
        read_only_fields = ['loyalty_points', 'wallet_balance', 'role', 'is_age_verified', 'risk_score']

class RiderProfileSerializer(serializers.ModelSerializer):
    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user
        user_qs = User.objects.filter(phone=normalized)
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

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
    dynamic_delivery_fee = serializers.SerializerMethodField()
    is_favourite = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()
    has_active_promotions = serializers.SerializerMethodField()
    max_promo_discount = serializers.SerializerMethodField()
    
    # User fields (Writable)
    bank_name = serializers.CharField(source='owner.bank_name', required=False, allow_blank=True)
    bank_account_name = serializers.CharField(source='owner.bank_account_name', required=False, allow_blank=True)
    bank_account_number = serializers.CharField(source='owner.bank_account_number', required=False, allow_blank=True)
    phone = serializers.CharField(source='owner.phone', required=False, allow_blank=True)
    email = serializers.EmailField(source='owner.email', required=False, allow_blank=True)
    address_string = serializers.CharField(source='owner.business_location', required=False, allow_blank=True)
    
    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user (the owner of the store)
        user_qs = User.objects.filter(phone=normalized)
        if self.instance and hasattr(self.instance, 'owner'):
            user_qs = user_qs.exclude(pk=self.instance.owner.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'shop_name', 'logo', 'cover_image', 'tagline', 'primary_color',
            'rating', 'rating_count', 'delivery_fee', 'dynamic_delivery_fee', 'delivery_radius_km',
            'base_delivery_fee', 'base_distance_km', 'extra_distance_surcharge',
            'avg_delivery_minutes', 'latitude', 'longitude', 'is_pro', 'is_favourite', 
            'distance', 'bank_name', 'bank_account_name', 'bank_account_number',
            'phone', 'email', 'address_string', 'telegram_chat_id',
            'opening_time', 'closing_time', 'is_open', 'plan', 'plan_price',
            'subscription_expires', 'subscription_active', 'billing_status',
            'mpesa_shortcode', 'mpesa_consumer_key', 'mpesa_consumer_secret',
            'mpesa_passkey', 'mpesa_callback_url', 'has_active_promotions', 'max_promo_discount'
        ]
        read_only_fields = ['owner', 'rating', 'rating_count', 'is_pro', 'plan', 'plan_price', 'subscription_expires', 'billing_status']

    def get_dynamic_delivery_fee(self, obj):
        request = self.context.get('request')
        if not request:
            return float(obj.delivery_fee)
            
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        
        if lat and lng and obj.latitude and obj.longitude:
            from .utils import calculate_delivery_fee
            try:
                return calculate_delivery_fee(float(lat), float(lng), float(obj.latitude), float(obj.longitude), store=obj)
            except Exception:
                return float(obj.delivery_fee)
        return float(obj.delivery_fee)

    def get_is_open(self, obj):
        now = timezone.localtime().time()
        if obj.opening_time and obj.closing_time:
            if obj.opening_time <= obj.closing_time:
                return obj.opening_time <= now <= obj.closing_time
            else: # Overnight case
                return now >= obj.opening_time or now <= obj.closing_time
        return True # Default to open if no hours set

    def get_is_favourite(self, obj):
        # Check if the field was annotated in the queryset
        is_favourite = getattr(obj, 'is_favourite', None)
        if is_favourite is not None:
            return is_favourite

        request = self.context.get('request')
        if not request:
            return False
        user = request.user
        if user and user.is_authenticated:
            return user.favourite_stores.filter(id=obj.id).exists()
        return False

    def get_has_active_promotions(self, obj):
        now = timezone.now()
        return obj.promotions.filter(
            start_date__lte=now,
            end_date__gte=now,
            is_active=True
        ).exists()

    def get_max_promo_discount(self, obj):
        now = timezone.now()
        # Prioritize percentage discounts for the badge
        promo = obj.promotions.filter(
            start_date__lte=now,
            end_date__gte=now,
            is_active=True,
            discount_type='percentage'
        ).order_by('-discount_value').first()
        if promo:
            return f"{int(promo.discount_value)}% OFF"
        
        # Fallback to fixed amount if no percentage
        promo_fixed = obj.promotions.filter(
            start_date__lte=now,
            end_date__gte=now,
            is_active=True,
            discount_type='fixed'
        ).order_by('-discount_value').first()
        if promo_fixed:
            return f"KSh {int(promo_fixed.discount_value)} OFF"
            
        return None

    def update(self, instance, validated_data):
        # Extract owner data (source fields map to 'owner' dict in validated_data if using dots)
        owner_data = validated_data.pop('owner', {})
        owner = instance.owner
        
        # Update owner fields
        if owner:
            for attr, value in owner_data.items():
                setattr(owner, attr, value)
            owner.save()
        
        # Update store fields
        return super().update(instance, validated_data)

class FoodCategorySerializer(serializers.ModelSerializer):
    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user
        user_qs = User.objects.filter(phone=normalized)
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

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
            'store_type', 'bottle_size', 'store', 'is_new_arrival', 'is_featured'
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
            # First check cache for live position
            cached_pos = cache.get(f"rider_pos_{obj.assigned_rider.id}")
            if cached_pos:
                return cached_pos['lat']
            
            # Fallback to last known DB record if not in cache
            last_ping = RiderLocationPing.objects.filter(rider=obj.assigned_rider).order_by('-created_at').first()
            if last_ping:
                return last_ping.latitude
        return None

    def get_rider_longitude(self, obj):
        if obj.assigned_rider:
            # First check cache for live position
            cached_pos = cache.get(f"rider_pos_{obj.assigned_rider.id}")
            if cached_pos:
                return cached_pos['lng']

            # Fallback to last known DB record if not in cache
            last_ping = RiderLocationPing.objects.filter(rider=obj.assigned_rider).order_by('-created_at').first()
            if last_ping:
                return last_ping.longitude
        return None

    # Store coordinates for pickup
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_latitude = serializers.DecimalField(source='store.latitude', max_digits=9, decimal_places=6, read_only=True)
    store_longitude = serializers.DecimalField(source='store.longitude', max_digits=9, decimal_places=6, read_only=True)
    
    verification_image_url = serializers.SerializerMethodField()

    def get_verification_image_url(self, obj):
        if obj.verification_image:
            from django.urls import reverse
            # Use the name defined in api_v1_urls.py
            return reverse('order_verification_image', args=[obj.order_number])
        return None

    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user
        user_qs = User.objects.filter(phone=normalized)
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer_name', 'customer_phone', 'customer_email', 'rider_name', 'status', 
            'payment_status', 'payment_method', 'total', 'latitude', 'longitude', 'address_string',
            'google_maps_link', 'created_at', 'items', 'delivery_fee', 'tip_amount',
            'promo_code', 'discount_amount',
            'store_name', 'store_latitude', 'store_longitude',
            'rider_latitude', 'rider_longitude',
            'requires_rider_verification', 'rider_verified_at', 'rider_verification_method', 'verification_image_url'
        ]
        read_only_fields = ['order_number', 'created_at']

class PromotionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promotion
        fields = '__all__'
        read_only_fields = ['store']

class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user
        user_qs = User.objects.filter(phone=normalized)
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

    class Meta:
        model = SubscriptionPayment
        fields = '__all__'

class RiderEarningSerializer(serializers.ModelSerializer):
    order_number = serializers.ReadOnlyField(source='order.order_number')
    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user
        user_qs = User.objects.filter(phone=normalized)
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

    class Meta:
        model = RiderEarning
        fields = '__all__'

class SavedAddressSerializer(serializers.ModelSerializer):
    def validate_phone(self, value):
        """Clean and validate phone number for Kenya/Daraja."""
        if not value:
            return value
        
        # Remove any non-digits
        digits = ''.join(c for c in str(value) if c.isdigit())
        
        if digits.startswith('0') and len(digits) == 10:
            normalized = digits[1:] # Store as 9 digits (7XXXXXXXX)
        elif digits.startswith('254') and len(digits) == 12:
            normalized = digits[3:] # Store as 9 digits (7XXXXXXXX)
        elif len(digits) == 9:
            normalized = digits
        else:
            raise serializers.ValidationError("Please enter a valid Kenyan phone number.")

        # Check for uniqueness against the normalized value
        # excluding the current user
        user_qs = User.objects.filter(phone=normalized)
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
        
        if user_qs.exists():
            raise serializers.ValidationError("This phone number is already registered to another user.")
            
        return normalized

    def update(self, instance, validated_data):
        # Sync the main 'phone' field to the legacy 'phone_number' field for safety
        phone = validated_data.get('phone')
        if phone:
            # Always ensure legacy field has a zero-prefixed or clean version if needed
            # but M-Pesa utils handle the conversion.
            instance.phone_number = '0' + phone if not phone.startswith('0') else phone
            
        return super().update(instance, validated_data)

    class Meta:
        model = SavedAddress
        fields = '__all__'
        read_only_fields = ['user']
