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
import logging

logger = logging.getLogger(__name__)

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
    
    # 🛡️ PCI DSS: Encrypted PII Fields (Phase 2 Day 4)
    # Stored as ENCRYPTED:v1:... format, transparent encryption/decryption via EncryptedFieldManager
    phone_number_encrypted = models.TextField(
        null=True,
        blank=True,
        help_text='🛡️ Encrypted phone number (ENCRYPTED: prefix). Read via EncryptedFieldManager.'
    )
    email_encrypted = models.TextField(
        null=True,
        blank=True,
        help_text='🛡️ Encrypted email (ENCRYPTED: prefix). Read via EncryptedFieldManager.'
    )
    
    def __str__(self):
        return self.username


class WalletLedger(models.Model):
    """Append-only wallet movements; User.wallet_balance is the materialized balance."""

    class EntryType(models.TextChoices):
        CREDIT = 'credit', 'Credit'
        DEBIT = 'debit', 'Debit'
        REFUND = 'refund', 'Refund'
        REVERSAL = 'reversal', 'Reversal'

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='wallet_ledger')
    entry_type = models.CharField(max_length=20, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_type = models.CharField(max_length=50)
    reference_id = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=160, unique=True)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['user', 'created_at'], name='wallet_user_created_idx')]


class LoyaltyLedger(models.Model):
    """Append-only loyalty movements; User.loyalty_points is the materialized balance."""

    class EntryType(models.TextChoices):
        CREDIT = 'credit', 'Credit'
        DEBIT = 'debit', 'Debit'
        REFUND = 'refund', 'Refund'
        REVERSAL = 'reversal', 'Reversal'

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='loyalty_ledger')
    entry_type = models.CharField(max_length=20, choices=EntryType.choices)
    points = models.IntegerField()
    source_payment_id = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=160, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['user', 'created_at'], name='loyalty_user_created_idx')]

class HighRiskZone(models.Model):
    """Geofenced high-risk zones like schools, universities, or high-incident areas."""
    name = models.CharField(max_length=200)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_meters = models.IntegerField(default=500, help_text="Radius in meters to trigger verification")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.radius_meters}m)"

class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def __str__(self):
        return f"OTP for {self.user.username} - {self.token}"

class Store(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stores')
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=False, db_index=True)
    is_pro = models.BooleanField(default=False, db_index=True)
    
    # Operational fields
    opening_time = models.TimeField(null=True, blank=True)
    closing_time = models.TimeField(null=True, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=200.0)
    delivery_radius_km = models.IntegerField(default=7)
    accepts_wallet_payments = models.BooleanField(default=True)

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
    is_open = models.BooleanField(default=True, db_index=True)
    opens_at = models.TimeField(null=True, blank=True)
    closes_at = models.TimeField(null=True, blank=True)

    # Plan / billing
    plan = models.CharField(max_length=20, choices=[
        ('free', 'Free (Pay As You Go)'), ('base', 'Base'), ('pro', 'Pro'), ('custom', 'Custom')], default='free')
    plan_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    subscription_expires = models.DateField(null=True, blank=True)
    billing_status = models.CharField(max_length=20, choices=[
        ('active', 'Active'), ('grace_period', 'Grace Period'),
        ('suspended', 'Suspended')], default='active')
    
    # Enterprise & Commission Logic
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, help_text="Custom commission rate for Enterprise partners")
    is_franchise = models.BooleanField(default=False)
    parent_store = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='branches')

    @property
    def subscription_active(self):
        """Returns True if subscription is active and not expired. Franchise branches inherit from parent."""
        if self.is_franchise and self.parent_store:
            return self.parent_store.subscription_active
            
        if self.billing_status == 'suspended':
            return False
        if not self.subscription_expires:
            return False
        from datetime import date
        return self.subscription_expires >= date.today()

    @property
    def effective_plan(self):
        """Inherit plan from parent if franchise."""
        if self.is_franchise and self.parent_store:
            return self.parent_store.plan
        return self.plan

    @property
    def effective_billing_status(self):
        """Inherit billing status from parent if franchise."""
        if self.is_franchise and self.parent_store:
            return self.parent_store.billing_status
        return self.billing_status

    @property
    def effective_subscription_expires(self):
        """Inherit expiry from parent if franchise."""
        if self.is_franchise and self.parent_store:
            return self.parent_store.subscription_expires
        return self.subscription_expires
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

    def save(self, *args, **kwargs):
        # 🛡️ MIDNIGHT MIRROR: Auto-encrypt sensitive credentials on save
        # This ensures security regardless of whether data comes from Admin, API, or Shell.
        from .mpesa_utils import encrypt_value
        for field in ['mpesa_consumer_key', 'mpesa_consumer_secret', 'mpesa_passkey']:
            val = getattr(self, field)
            # Only encrypt if it's a raw string (doesn't start with Fernet prefix)
            if val and not str(val).startswith('gAAAA'):
                setattr(self, field, encrypt_value(val))
        
        super().save(*args, **kwargs)

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
    description = models.TextField(blank=True, null=True)
    category_fkey = models.ForeignKey(FoodCategory, on_delete=models.CASCADE, related_name='items', null=True, blank=True)
    
    # New category choices as requested
    CATEGORY_CHOICES = [
        ('whisky','Whisky'), ('wine','Wine'), ('beer','Beer'),
        ('gin','Gin'), ('spirits','Spirits'), ('champagne','Champagne')
    ]
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, null=True, blank=True)
    sku = models.CharField(max_length=50, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    discount_percent = models.IntegerField(default=0)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    stock = models.PositiveIntegerField(default=0, help_text="Available units in stock")
    low_stock_threshold = models.PositiveIntegerField(default=2, help_text="Alert when stock goes below this number")
    image = models.ImageField(upload_to='food_images/')
    prep_time = models.IntegerField(help_text="Preparation time in minutes", default=15)
    is_available = models.BooleanField(default=True, db_index=True)
    is_new_arrival = models.BooleanField(default=False, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
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
                logger.error(f"⚠️ Optimization skipped for {self.name}: {e}")
        
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
    last_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    
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
    address = models.TextField(null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
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
    verification_image = models.FileField(upload_to='verifications/', null=True, blank=True)

    order_number = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    is_test_order = models.BooleanField(default=False)
    has_reviewed_items = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    
    # Delivery information
    hostel = models.CharField(max_length=100, null=True, blank=True)
    room_number = models.CharField(max_length=50, null=True, blank=True)
    phone_number = models.CharField(max_length=15)
    # 🛡️ PCI DSS: Encrypted customer phone (Phase 2 Day 4)
    customer_phone_encrypted = models.TextField(
        null=True,
        blank=True,
        help_text='🛡️ Encrypted customer phone (ENCRYPTED: prefix). Read via EncryptedFieldManager.'
    )
    delivery_notes = models.TextField(blank=True)
    
    # Pricing
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    promo_code = models.CharField(max_length=20, null=True, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    wallet_used = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
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
    payment_idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)
    idempotency_fingerprint = models.CharField(max_length=64, null=True, blank=True, editable=False)
    revenue_share_applied_at = models.DateTimeField(null=True, blank=True)

    # Store type for the order
    store_type = models.CharField(max_length=10, choices=[
        ('food', 'Food Store'),
        ('liquor', 'Liquor Store'),
        ('grocery', 'Grocery Shop')
    ], default='liquor')

    # MPESA specific fields
    mpesa_checkout_request_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    mpesa_receipt_number = models.CharField(max_length=20, blank=True, null=True, db_index=True)
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
            # 🛡️ Use local Nairobi time for order numbering to ensure sequential dates in Kenya
            self.order_number = f"TT{timezone.localtime(timezone.now()).strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

        # Reservations decrement stock at order creation. Delivery only
        # finalizes them; it must not deduct stock a second time.
        if old_status != 'delivered' and self.status == 'delivered':
            from .inventory_service import InventoryReservationService
            InventoryReservationService.finalize_order(self.pk)
    
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


class PromotionRedemption(models.Model):
    """One auditable, idempotent promotion use attached to an order."""

    promotion = models.ForeignKey('Promotion', on_delete=models.PROTECT, related_name='redemptions')
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name='promotion_redemption')
    code = models.CharField(max_length=20)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['promotion', 'order'], name='uniq_promotion_order_redemption'),
        ]


class InventoryReservation(models.Model):
    """Auditable stock reservation owned by an order."""

    class Status(models.TextChoices):
        RESERVED = 'reserved', 'Reserved'
        RELEASED = 'released', 'Released'
        FINALIZED = 'finalized', 'Finalized'

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='inventory_reservations')
    food_item = models.ForeignKey(FoodItem, on_delete=models.PROTECT, related_name='inventory_reservations')
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RESERVED, db_index=True)
    reserved_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['order', 'food_item'], name='uniq_inventory_reservation_order_item'),
            models.CheckConstraint(check=models.Q(quantity__gt=0), name='inventory_reservation_positive_quantity'),
        ]
        indexes = [
            models.Index(fields=['status', 'reserved_at'], name='inv_res_status_reserved_idx'),
            models.Index(fields=['food_item', 'status'], name='inv_res_food_status_idx'),
        ]

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
        indexes = [
            models.Index(fields=['store', 'code', 'is_active'], name='promo_store_code_active_idx'),
            models.Index(fields=['store', 'is_active', 'start_date', 'end_date'], name='promo_store_active_dates_idx'),
        ]
    
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


class PaymentAttempt(models.Model):
    """Durable identity and audit record for one provider payment attempt."""

    class Provider(models.TextChoices):
        MPESA = 'mpesa', 'M-Pesa'

    class PaymentType(models.TextChoices):
        ORDER = 'order', 'Order'
        SUBSCRIPTION = 'subscription', 'Subscription'
        SHIRIKI = 'shiriki', 'Shiriki Contribution'
        COMMISSION = 'commission', 'Commission'

    class Status(models.TextChoices):
        INITIATING = 'initiating', 'Initiating'
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        FAILED = 'failed', 'Failed'
        EXPIRED = 'expired', 'Expired'
        MANUAL_REVIEW = 'manual_review', 'Manual Review'
        OVERPAID = 'overpaid', 'Overpaid'
        REFUND_REQUIRED = 'refund_required', 'Refund Required'

    public_payment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.MPESA)
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices)

    order = models.ForeignKey(
        'Order', on_delete=models.PROTECT, null=True, blank=True,
        related_name='payment_attempts'
    )
    subscription_payment = models.ForeignKey(
        'SubscriptionPayment', on_delete=models.PROTECT, null=True, blank=True,
        related_name='payment_attempts'
    )
    shiriki_contribution = models.ForeignKey(
        'ShirikiContribution', on_delete=models.PROTECT, null=True, blank=True,
        related_name='payment_attempts'
    )

    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    checkout_request_id = models.CharField(max_length=100, null=True, blank=True)
    provider_receipt = models.CharField(max_length=50, null=True, blank=True)

    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    received_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default='KES')
    phone_number = models.CharField(max_length=15, blank=True)
    # 🛡️ PCI DSS: Encrypted M-Pesa phone (Phase 2 Day 4)
    phone_number_encrypted = models.TextField(
        null=True,
        blank=True,
        help_text='🛡️ Encrypted M-Pesa phone (ENCRYPTED: prefix). Read via EncryptedFieldManager.'
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INITIATING, db_index=True)
    provider_result_code = models.IntegerField(null=True, blank=True)
    provider_result_description = models.TextField(blank=True)
    failure_code = models.CharField(max_length=50, blank=True)
    failure_message = models.TextField(blank=True)

    raw_initiation_response = models.JSONField(null=True, blank=True)
    raw_callback_payload = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    initiation_started_at = models.DateTimeField(null=True, blank=True)
    initiation_completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciliation_started_at = models.DateTimeField(null=True, blank=True)
    next_reconciliation_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reconciliation_attempts = models.PositiveIntegerField(default=0)
    manual_review_reason = models.TextField(blank=True)
    processing_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'checkout_request_id'],
                condition=models.Q(checkout_request_id__isnull=False),
                name='uniq_payment_provider_checkout',
            ),
            models.UniqueConstraint(
                fields=['provider', 'provider_receipt'],
                condition=models.Q(provider_receipt__isnull=False),
                name='uniq_payment_provider_receipt',
            ),
            models.CheckConstraint(
                check=(
                    (
                        models.Q(order__isnull=False)
                        & models.Q(subscription_payment__isnull=True)
                        & models.Q(shiriki_contribution__isnull=True)
                    )
                    | (
                        models.Q(order__isnull=True)
                        & models.Q(subscription_payment__isnull=False)
                        & models.Q(shiriki_contribution__isnull=True)
                    )
                    | (
                        models.Q(order__isnull=True)
                        & models.Q(subscription_payment__isnull=True)
                        & models.Q(shiriki_contribution__isnull=False)
                    )
                ),
                name='payment_attempt_one_target',
            ),
            models.CheckConstraint(
                check=models.Q(expected_amount__gt=0),
                name='payment_attempt_positive_expected_amount',
            ),
            models.CheckConstraint(
                check=models.Q(received_amount__isnull=True) | models.Q(received_amount__gte=0),
                name='payment_attempt_nonnegative_received_amount',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'created_at'], name='payment_status_created_idx'),
            models.Index(fields=['payment_type', 'status'], name='payment_type_status_idx'),
            models.Index(fields=['order', 'status'], name='payment_order_status_idx'),
            models.Index(fields=['status', 'checkout_request_id'], name='payment_status_checkout_idx'),
            models.Index(fields=['status', 'next_reconciliation_at'], name='payment_status_next_recon_idx'),
        ]

    def __str__(self):
        return f"{self.public_payment_id} - {self.status}"


class CallbackInbox(models.Model):
    """Durable provider callback inbox processed independently from HTTP receipt."""

    class Provider(models.TextChoices):
        MPESA = 'mpesa', 'M-Pesa'

    class Status(models.TextChoices):
        RECEIVED = 'received', 'Received'
        PROCESSING = 'processing', 'Processing'
        PROCESSED = 'processed', 'Processed'
        RETRY = 'retry', 'Retry'
        UNMATCHED = 'unmatched', 'Unmatched'
        MANUAL_REVIEW = 'manual_review', 'Manual Review'

    event_hash = models.CharField(max_length=64, unique=True)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.MPESA)
    checkout_request_id = models.CharField(max_length=100, blank=True, db_index=True)
    payment_attempt = models.ForeignKey(
        PaymentAttempt, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='callback_events'
    )
    raw_payload = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    processing_attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['received_at']
        indexes = [
            models.Index(fields=['status', 'received_at'], name='callback_status_received_idx'),
            models.Index(fields=['provider', 'checkout_request_id'], name='callback_provider_checkout_idx'),
            models.Index(fields=['status', 'next_attempt_at'], name='callback_status_next_idx'),
        ]

    def __str__(self):
        return f"{self.provider}:{self.event_hash} - {self.status}"


class PaymentReconciliation(models.Model):
    """Immutable audit record for each provider status query."""

    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Confirmed'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'
        ERROR = 'error', 'Error'
        MANUAL_REVIEW = 'manual_review', 'Manual Review'

    payment_attempt = models.ForeignKey(PaymentAttempt, on_delete=models.PROTECT, related_name='reconciliations')
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices)
    result_code = models.IntegerField(null=True, blank=True)
    result_description = models.TextField(blank=True)
    raw_response = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['payment_attempt', 'attempt_number'],
            name='uniq_reconciliation_attempt_number',
        )]
        indexes = [models.Index(fields=['payment_attempt', 'created_at'], name='recon_attempt_created_idx')]


class OutboxEvent(models.Model):
    """Transactional event record for reliable downstream processing."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        PROCESSED = 'processed', 'Processed'
        RETRY = 'retry', 'Retry'
        DEAD = 'dead', 'Dead Letter'

    event_type = models.CharField(max_length=80)
    aggregate_type = models.CharField(max_length=50)
    aggregate_id = models.CharField(max_length=100)
    payment_attempt = models.ForeignKey(
        PaymentAttempt, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='outbox_events'
    )
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    idempotency_key = models.CharField(max_length=180, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [models.UniqueConstraint(
            fields=['event_type', 'aggregate_type', 'aggregate_id'],
            name='uniq_outbox_event_aggregate',
        )]
        indexes = [models.Index(fields=['status', 'next_attempt_at'], name='outbox_status_next_idx')]

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

class ChatMessage(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='chat_messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"From {self.sender.username} for Order {self.order.order_number}"

class WeeklyRevenueStat(models.Model):
    PAYOUT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('pending', 'Pending Verification'),
        ('paid', 'Paid'),
    ]
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='revenue_stats')
    week_start = models.DateField()
    week_end = models.DateField()
    total_liquor_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    partner_share_40 = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=PAYOUT_STATUS_CHOICES, default='unpaid')
    is_paid = models.BooleanField(default=False, help_text="Legacy field, use status instead")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['store', 'week_start']
        ordering = ['-week_start']

    def __str__(self):
        return f"{self.store.name} - Week {self.week_start}"

class PartnerPayout(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='payouts')
    week_stat = models.OneToOneField(WeeklyRevenueStat, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    mpesa_code = models.CharField(max_length=20)
    paid_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.store.name} - {self.mpesa_code} ({self.amount})"

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
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], default='pending')
    payment_type = models.CharField(max_length=20, choices=[
        ('subscription', 'Monthly Subscription'),
        ('commission', 'Pay As You Go Commission'),
    ], default='subscription')
    week_stat = models.ForeignKey('WeeklyRevenueStat', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    plan = models.CharField(max_length=20, choices=[
        ('base', 'Base'), ('pro', 'Pro'), ('custom', 'Custom')
    ], null=True, blank=True)
    checkout_request_id = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)
    phone_number = models.CharField(max_length=15, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.TextField(blank=True)
    transaction_date = models.CharField(max_length=20, blank=True)
    mpesa_receipt = models.CharField(max_length=50, null=True, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)
    payment_idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

class PlatformConfig(models.Model):
    daraja_consumer_key = models.TextField(help_text="Encrypted Consumer Key")
    daraja_consumer_secret = models.TextField(help_text="Encrypted Consumer Secret")
    daraja_shortcode = models.CharField(max_length=50)
    daraja_passkey = models.TextField(help_text="Encrypted Passkey")

    def save(self, *args, **kwargs):
        from .mpesa_utils import encrypt_value
        for field in ['daraja_consumer_key', 'daraja_consumer_secret', 'daraja_passkey']:
            val = getattr(self, field)
            if val and not str(val).startswith('gAAAA'):
                setattr(self, field, encrypt_value(val))
        super().save(*args, **kwargs)

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

class ShirikiSession(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    order = models.OneToOneField('Order', on_delete=models.CASCADE, related_name='shiriki_session')
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hosted_shiriki_sessions')
    invite_code = models.CharField(max_length=10, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['status', 'expires_at'], name='shiriki_sess_status_exp_idx'),
        ]

    def __str__(self):
        return f"Shiriki {self.invite_code} - {self.order.order_number}"

class ShirikiContribution(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]
    session = models.ForeignKey(ShirikiSession, on_delete=models.CASCADE, related_name='contributions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shiriki_contributions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=15)
    checkout_request_id = models.CharField(max_length=100, unique=True, db_index=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    amount_applied_to_pot = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    wallet_credit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    payment_idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['session', 'status', 'created_at'], name='shiriki_contrib_state_idx'),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.amount} for {self.session.invite_code}"

class RiderWeeklyStat(models.Model):
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('disputed', 'Disputed'),
    ]
    rider = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weekly_stats')
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='rider_weekly_stats')
    week_start = models.DateField()
    week_end = models.DateField()
    total_base_fare = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_tips = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unpaid')
    mpesa_code = models.CharField(max_length=20, blank=True, null=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['rider', 'store', 'week_start']
        ordering = ['-week_start']

    def __str__(self):
        return f"{self.rider.username} - {self.store.name} - Week {self.week_start}"

class PanicAlert(models.Model):
    rider = models.ForeignKey(User, on_delete=models.CASCADE, related_name='panic_alerts')
    latitude = models.DecimalField(max_digits=12, decimal_places=9)
    longitude = models.DecimalField(max_digits=12, decimal_places=9)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"PANIC: {self.rider.username} at {self.timestamp}"


# 🛡️ PCI DSS: Fraud Detection & Incident Tracking (Phase 2 Day 5)
class FraudIncident(models.Model):
    """
    Tracks fraudulent payment patterns detected by FraudDetectionEngine.
    Provides audit trail for investigation and post-incident analysis.
    
    Severity scores:
    - 0.75-0.89: High confidence fraud (auto-blocked, investigation required)
    - 0.90-1.00: Critical fraud (escalate to authorities)
    """
    
    class PatternType(models.TextChoices):
        FAILED_VELOCITY = 'failed_velocity', 'Failed Attempt Velocity'
        UNUSUAL_AMOUNT = 'unusual_amount', 'Unusual Amount'
        TEST_TRANSACTIONS = 'test_transactions', 'Test Transactions'
        ORDER_VELOCITY = 'order_velocity', 'Order Velocity'
        GEOGRAPHIC_ANOMALY = 'geographic_anomaly', 'Geographic Anomaly'
        RATE_LIMIT_BYPASS = 'rate_limit_bypass', 'Rate Limit Bypass'
        CALLBACK_MANIPULATION = 'callback_manipulation', 'Callback Manipulation'
    
    class Severity(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'
    
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        INVESTIGATING = 'investigating', 'Investigating'
        ESCALATED = 'escalated', 'Escalated to Authorities'
        RESOLVED = 'resolved', 'Resolved'
        FALSE_POSITIVE = 'false_positive', 'False Positive'
    
    # Unique ID & Classification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pattern_type = models.CharField(
        max_length=30,
        choices=PatternType.choices,
        db_index=True
    )
    confidence = models.FloatField(
        help_text='Confidence score (0.0-1.0). Auto-blocked at 75%+ confidence.',
        db_index=True
    )
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        db_index=True
    )
    
    # Affected Entity
    customer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fraud_incidents',
        help_text='Customer associated with fraud pattern'
    )
    phone_number = models.CharField(
        max_length=15,
        help_text='Phone number used in fraudulent attempt'
    )
    
    # Status & Investigation
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True
    )
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text='Pattern-specific details (e.g., attempt count, amount, IP, timestamp)'
    )
    
    # Related Payment
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fraud_incidents',
        help_text='Order associated with fraud (if applicable)'
    )
    
    # Investigation & Assignment
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_fraud_incidents',
        limit_choices_to={'role': User.Role.SUPERADMIN},
        help_text='Security team member investigating this incident'
    )
    investigation_notes = models.TextField(
        blank=True,
        help_text='Investigation findings and actions taken'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'status'], name='fraud_customer_status_idx'),
            models.Index(fields=['created_at', 'severity'], name='fraud_time_severity_idx'),
            models.Index(fields=['pattern_type', 'confidence'], name='fraud_pattern_confidence_idx'),
        ]
    
    def __str__(self):
        return f"[{self.severity.upper()}] {self.pattern_type} - {self.customer.username} ({self.status})"
    
    def mark_as_investigating(self, assigned_to, reason=''):
        """Mark incident as being investigated."""
        self.status = self.Status.INVESTIGATING
        self.assigned_to = assigned_to
        if reason:
            self.investigation_notes = f"Reason: {reason}\n{self.investigation_notes}"
        self.save()
    
    def resolve(self, outcome, notes=''):
        """Resolve incident with outcome (RESOLVED or FALSE_POSITIVE)."""
        if outcome not in [self.Status.RESOLVED, self.Status.FALSE_POSITIVE]:
            raise ValueError(f"Invalid outcome: {outcome}")
        self.status = outcome
        self.resolved_at = timezone.now()
        if notes:
            self.investigation_notes = f"{self.investigation_notes}\n\nResolution: {notes}"
        self.save()
