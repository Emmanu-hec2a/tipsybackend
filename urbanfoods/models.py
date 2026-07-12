from django.db import models
from django.db.models import Sum
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os

class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER   = 'customer', 'Customer'
        PARTNER    = 'partner', 'Partner'
        RIDER      = 'rider', 'Rider'
        SUPERADMIN = 'superadmin', 'Super Admin'

    role = models.CharField(max_length=20, choices=Role.choices,
                             default=Role.CUSTOMER)
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    business_name = models.CharField(max_length=200, null=True, blank=True)
    business_location = models.CharField(max_length=300, null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    assigned_store = models.ForeignKey('Store', null=True, blank=True,
                         on_delete=models.SET_NULL, related_name='riders')
    is_available = models.BooleanField(default=False)
    telegram_chat_id = models.CharField(max_length=100, null=True, blank=True)
    total_deliveries = models.IntegerField(default=0)
    avg_rating = models.DecimalField(max_digits=2, decimal_places=1, default=0.0)
    acceptance_rate = models.DecimalField(max_digits=5, decimal_places=2, default=100.0)
    bank_account_name = models.CharField(max_length=100, null=True, blank=True)
    bank_account_number = models.CharField(max_length=50, null=True, blank=True)
    bank_name = models.CharField(max_length=100, null=True, blank=True)
    fcm_token = models.CharField(max_length=255, null=True, blank=True)

    # Age Verification & Risk Signals
    date_of_birth = models.DateField(null=True, blank=True)
    is_age_verified = models.BooleanField(default=False)
    risk_score = models.IntegerField(default=0, help_text="Calculated risk score (0-100)")
    verification_metadata = models.JSONField(default=dict, blank=True, help_text="Silent sentry behavior signals")

    # Legacy/Existing fields
    phone_number = models.CharField(max_length=15, blank=True)
    default_hostel = models.CharField(max_length=100, blank=True)
    default_room = models.CharField(max_length=50, blank=True)
    student_email = models.EmailField(unique=True, null=True, blank=True)
    loyalty_points = models.IntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    profile_picture = models.ImageField(upload_to='profiles/', null=True, blank=True)
    favourite_stores = models.ManyToManyField('Store', blank=True, related_name='favourited_by')
    wallet_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    def __str__(self):
        return self.username

class Store(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name='store')
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=False)
    is_pro = models.BooleanField(default=False)
    
    # Operational fields
    opening_time = models.TimeField(null=True, blank=True)
    closing_time = models.TimeField(null=True, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=200.0)
    delivery_radius_km = models.IntegerField(default=7)

    # Dynamic Fee Overrides (if null, uses SiteSettings)
    base_delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    base_distance_km = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    extra_distance_surcharge = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Branding
    shop_name = models.CharField(max_length=200, null=True, blank=True)
    subdomain = models.SlugField(unique=True, null=True, blank=True)
    logo = models.ImageField(upload_to='store_logos/', null=True, blank=True)
    cover_image = models.ImageField(upload_to='store_covers/', null=True, blank=True)
    primary_color = models.CharField(max_length=7, default='#F97316')
    secondary_color = models.CharField(max_length=7, default='#1F2937')
    tagline = models.CharField(max_length=200, null=True, blank=True)
    custom_domain = models.CharField(max_length=200, null=True, blank=True)

    # Discovery
    rating = models.DecimalField(max_digits=2, decimal_places=1, default=0.0)
    rating_count = models.IntegerField(default=0)
    avg_delivery_minutes = models.IntegerField(default=30)
    is_open = models.BooleanField(default=True)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)

    # Plan / billing
    plan = models.CharField(max_length=20, choices=[
        ('base', 'Base'), ('pro', 'Pro'), ('custom', 'Custom')], default='base')
    plan_price = models.DecimalField(max_digits=10, decimal_places=2, default=5000)
    subscription_active = models.BooleanField(default=False)
    subscription_expires = models.DateField(null=True, blank=True)
    billing_status = models.CharField(max_length=20, choices=[
        ('active', 'Active'), ('grace_period', 'Grace Period'),
        ('suspended', 'Suspended')], default='active')
    last_payment_date = models.DateField(null=True, blank=True)
    last_expiry_reminder_sent = models.DateField(null=True, blank=True)

    # M-Pesa Daraja Integration (Store-specific, Encrypted)
    mpesa_consumer_key = models.TextField(null=True, blank=True, help_text="Encrypted Consumer Key")
    mpesa_consumer_secret = models.TextField(null=True, blank=True, help_text="Encrypted Consumer Secret")
    mpesa_passkey = models.TextField(null=True, blank=True, help_text="Encrypted Passkey")
    mpesa_shortcode = models.CharField(max_length=50, null=True, blank=True, help_text="Business Short Code")
    mpesa_callback_url = models.URLField(null=True, blank=True, help_text="Store-specific callback URL")

    telegram_chat_id = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def display_name(self):
        if self.plan in ['pro', 'custom'] and self.shop_name:
            return self.shop_name
        return 'Tipsy Theoryy'

    @property
    def primary_color_rgb(self):
        hex_color = self.primary_color.lstrip('#')
        try:
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            return f"{rgb[0]}, {rgb[1]}, {rgb[2]}"
        except Exception:
            return "234, 88, 12" # Fallback orange-600

class MarketingBlast(models.Model):
    """History of marketing notifications sent by merchants"""
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='blasts')
    message = models.TextField()
    target_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.store.name} - {self.created_at.date()}"

class FoodCategory(models.Model):
    """Categories for organizing food items"""
    STORE_CHOICES = [
        ('food', 'Food Store'),
        ('liquor', 'Liquor Store'),
        ('grocery', 'Grocery Shop'),
    ]

    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)  # emoji or icon class
    order = models.IntegerField(default=0)  # for sorting
    store_type = models.CharField(max_length=10, choices=STORE_CHOICES, default='liquor')
    
    class Meta:
        verbose_name_plural = "Liquor Categories"
        ordering = ['order', 'name']
    
    def __str__(self):
        return self.name

class FoodItem(models.Model):
    """Individual food items available for order"""
    STORE_CHOICES = [
        ('food', 'Food Store'),
        ('liquor', 'Liquor Store'),
        ('grocery', 'Grocery Shop'),
    ]
    
    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True) # Nullable for migration
    name = models.CharField(max_length=100)
    description = models.TextField()
    category_fkey = models.ForeignKey(FoodCategory, on_delete=models.CASCADE, related_name='items', null=True, blank=True)
    
    # New category choices as requested
    CATEGORY_CHOICES = [
        ('whisky','Whisky'), ('wine','Wine'), ('beer','Beer'),
        ('gin','Gin'), ('spirits','Spirits'), ('champagne','Champagne')
    ]
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, null=True, blank=True)
    sku = models.CharField(max_length=50, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    discount_percent = models.IntegerField(default=0)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    stock = models.PositiveIntegerField(default=0, help_text="Available units in stock")
    low_stock_threshold = models.PositiveIntegerField(default=2, help_text="Alert when stock goes below this number")
    image = models.ImageField(upload_to='food_images/')
    prep_time = models.IntegerField(help_text="Preparation time in minutes", default=15)
    is_available = models.BooleanField(default=True)
    is_new_arrival = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    is_meal_of_day = models.BooleanField(default=False)
    times_ordered = models.IntegerField(default=0)  # for popularity tracking
    store_type = models.CharField(max_length=10, choices=STORE_CHOICES, default='liquor')
    bottle_size = models.CharField(max_length=20, blank=True, help_text="For liquor items (e.g., 250ml, 500ml, 750ml)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        should_optimize = False
        if self.image:
            try:
                if hasattr(self.image, 'file') and hasattr(self.image.file, 'read'):
                    should_optimize = True
            except:
                should_optimize = False
        
        if should_optimize:
            try:
                self.image.file.seek(0)
                img = Image.open(self.image.file)
                if img.mode in ("RGBA", "LA", "P"):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode in ("RGBA", "LA"):
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                
                max_size = (800, 800)
                if img.width > max_size[0] or img.height > max_size[1]:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=75, optimize=True, progressive=True)
                buffer.seek(0)
                
                original_filename = os.path.basename(self.image.name)
                filename_without_ext = os.path.splitext(original_filename)[0]
                new_filename = f"{filename_without_ext}.jpg"
                
                self.image.save(new_filename, ContentFile(buffer.read()), save=False)
            except Exception as e:
                print(f"⚠️ Optimization skipped for {self.name}: {e}")
        
        super().save(*args, **kwargs)
    
    @property
    def is_liquor(self):
        return self.store_type == 'liquor'

    @property
    def average_rating(self):
        reviews = self.reviews.all()
        if reviews.exists():
            return round(sum(review.rating for review in reviews) / reviews.count(), 1)
        return 0

    @property
    def review_count(self):
        return self.reviews.count()
    
    class Meta:
        ordering = ['-is_featured', '-times_ordered', 'name']
    
    def __str__(self):
        return f"{self.name} - KES {self.price}"

class Cart(models.Model):
    """Shopping cart for each user"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Cart for {self.user.username}"
    
    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())
    
    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

class CartItem(models.Model):
    """Individual items in a cart"""
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    food_item = models.ForeignKey(FoodItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['cart', 'food_item']
    
    @property
    def subtotal(self):
        return self.food_item.price * self.quantity
    
    def __str__(self):
        return f"{self.quantity}x {self.food_item.name}"

class Order(models.Model):
    """Customer orders"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('assigned', 'Assigned to Rider'),
        ('picked_up', 'Picked Up'),
        ('arrived', 'Rider Arrived'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed')
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, null=True, blank=True) # Nullable for migration
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    address_string = models.CharField(max_length=500, null=True, blank=True)
    google_maps_link = models.CharField(max_length=300, null=True, blank=True)
    assigned_rider = models.ForeignKey(User, null=True, blank=True,
                         on_delete=models.SET_NULL, related_name='deliveries')
    
    tip_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rider_base_fare = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    eta_minutes = models.IntegerField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_window_start = models.TimeField(null=True, blank=True)
    delivery_window_end = models.TimeField(null=True, blank=True)

    # Verification Handshake
    requires_rider_verification = models.BooleanField(default=False)
    rider_verified_at = models.DateTimeField(null=True, blank=True)
    rider_verification_method = models.CharField(max_length=50, null=True, blank=True)

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    is_test_order = models.BooleanField(default=False)
    has_reviewed_items = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Delivery information
    hostel = models.CharField(max_length=100, null=True, blank=True)
    room_number = models.CharField(max_length=50, null=True, blank=True)
    phone_number = models.CharField(max_length=15)
    delivery_notes = models.TextField(blank=True)
    
    # Pricing
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    
    # Payment information
    payment_method = models.CharField(max_length=10, choices=[('mpesa', 'MPESA'), ('till', 'TILL')], default='mpesa')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_type = models.CharField(max_length=20, choices=[
        ('till', 'Till Number'),
        ('paybill', 'Paybill Number')
    ], blank=True, null=True)
    payment_completed_at = models.DateTimeField(null=True, blank=True)
    payment_failure_reason = models.TextField(blank=True, null=True)

    # Store type for the order
    store_type = models.CharField(max_length=10, choices=[
        ('food', 'Food Store'),
        ('liquor', 'Liquor Store'),
        ('grocery', 'Grocery Shop')
    ], default='liquor')

    # MPESA specific fields
    mpesa_checkout_request_id = models.CharField(max_length=50, blank=True, null=True)
    mpesa_receipt_number = models.CharField(max_length=20, blank=True, null=True)
    mpesa_transaction_date = models.CharField(max_length=20, blank=True, null=True)

    # Additional fields
    cancellation_reason = models.TextField(blank=True)
    rating_value = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    review_text = models.TextField(blank=True)
    
    # Review prompt tracking
    review_prompted_count = models.IntegerField(default=0)
    review_prompt_dismissed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        is_new = self._state.adding
        old_status = None
        if not is_new:
            old_status = Order.objects.get(pk=self.pk).status

        if not self.order_number:
            self.order_number = f"TT{timezone.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

        # Handle inventory deduction on delivery
        if old_status != 'delivered' and self.status == 'delivered':
            for item in self.items.all():
                food_item = item.food_item
                if food_item.stock >= item.quantity:
                    food_item.stock -= item.quantity
                else:
                    food_item.stock = 0
                
                # Update popularity
                food_item.times_ordered += item.quantity
                food_item.save(update_fields=['stock', 'times_ordered'])
    
    def __str__(self):
        return f"Order {self.order_number} - {self.user.username}"

class OrderItem(models.Model):
    """Items in an order"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    food_item = models.ForeignKey(FoodItem, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    price_at_order = models.DecimalField(max_digits=10, decimal_places=2)  # Price snapshot
    
    @property
    def subtotal(self):
        return self.price_at_order * self.quantity
    
    def __str__(self):
        return f"{self.quantity}x {self.food_item.name} (Order: {self.order.order_number})"

class OrderStatusHistory(models.Model):
    """Track order status changes"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['timestamp']
        verbose_name_plural = "Order Status Histories"
    
    def __str__(self):
        return f"{self.order.order_number} - {self.status} at {self.timestamp}"

class FoodReview(models.Model):
    """Reviews for food items"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    food_item = models.ForeignKey(FoodItem, on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'food_item', 'order']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.food_item.name} ({self.rating}★)"

class Promotion(models.Model):
    """Promotional offers and deals"""
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='promotions', null=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    code = models.CharField(max_length=20)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    min_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    usage_limit = models.IntegerField(null=True, blank=True)
    times_used = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ['store', 'code']
    
    def __str__(self):
        return self.title
    
class PushSubscription(models.Model):
    endpoint = models.TextField(unique=True)
    keys = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.endpoint
    
class MpesaTransaction(models.Model):
    EVENT_CHOICES = [
    ('stk_initiated', 'STK Initiated'),
    ('callback_received', 'Callback Received'),
    ('stk_query', 'STK Query'),
    ]
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='mpesa_transactions')
    checkout_request_id = models.CharField(max_length=50, db_index=True)
    mpesa_receipt_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_date = models.CharField(max_length=20, blank=True, null=True)
    result_code = models.IntegerField()
    result_desc = models.TextField()
    raw_callback = models.JSONField()
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES, default='stk_initiated')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.mpesa_receipt_number or 'PENDING'} - {self.order.order_number}"

class DeliveryGuy(models.Model):
    """Legacy Delivery personnel for orders"""
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Delivery Guys"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.phone_number})"
    
    @property
    def total_deliveries(self):
        return self.orders.filter(status='delivered').count()
    
    @property
    def total_revenue(self):
        return self.orders.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0

class DeliveryGuyWeeklyPayment(models.Model):
    delivery_guy = models.ForeignKey(DeliveryGuy, on_delete=models.CASCADE, related_name='weekly_payments')
    week_start = models.DateField()
    week_end = models.DateField()
    deliveries_count = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Rating(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='order_rating')
    customer = models.ForeignKey(User, on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='store_ratings')
    rider = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                related_name='ratings_received')
    store_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    rider_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], null=True, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class RiderEarning(models.Model):
    rider = models.ForeignKey(User, on_delete=models.CASCADE, related_name='earnings')
    order = models.OneToOneField(Order, on_delete=models.CASCADE)
    base_fare = models.DecimalField(max_digits=10, decimal_places=2)
    tip = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

class RiderLocationPing(models.Model):
    rider = models.ForeignKey(User, on_delete=models.CASCADE, related_name='location_pings')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

class SubscriptionPayment(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='subscription_payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=[('success','Success'),('failed','Failed')])
    mpesa_receipt = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class PlatformConfig(models.Model):
    daraja_consumer_key = models.TextField(help_text="Encrypted Consumer Key")
    daraja_consumer_secret = models.TextField(help_text="Encrypted Consumer Secret")
    daraja_shortcode = models.CharField(max_length=50)
    daraja_passkey = models.TextField(help_text="Encrypted Passkey")

    def __str__(self):
        return f"Platform Config ({self.daraja_shortcode})"

class SiteSettings(models.Model):
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=20, help_text="Legacy global fee")
    
    # New Dynamic Fee Settings
    base_delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=100.0, help_text="Fee for base distance")
    base_distance_km = models.DecimalField(max_digits=5, decimal_places=2, default=2.0, help_text="Distance covered by base fee")
    extra_distance_surcharge = models.DecimalField(max_digits=10, decimal_places=2, default=30.0, help_text="Charge per extra KM")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Site Settings"
    
    def __str__(self):
        return "Site Settings"
    
    @classmethod
    def get_instance(cls):
        instance, _ = cls.objects.get_or_create(id=1)
        return instance

class SavedAddress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_addresses')
    name = models.CharField(max_length=100, help_text='e.g. Home, Office')
    address_string = models.TextField()
    latitude = models.DecimalField(max_digits=12, decimal_places=9)
    longitude = models.DecimalField(max_digits=12, decimal_places=9)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.name}: {self.address_string}"
    
    def save(self, *args, **kwargs):
        if self.is_default:
            SavedAddress.objects.filter(user=self.user).update(is_default=False)
        super().save(*args, **kwargs)
