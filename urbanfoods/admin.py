from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin
from django.utils.html import format_html
from django.urls import reverse
from .mpesa_utils import encrypt_value, decrypt_value
from django.forms import PasswordInput, CharField
from .models import *

@admin.register(User)
class CustomUserAdmin(BaseUserAdmin, ModelAdmin):
    list_display = ('username', 'email', 'phone', 'role', 'assigned_store', 'is_approved', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_approved', 'is_verified', 'date_joined')
    search_fields = ('username', 'email', 'phone', 'business_name')
    ordering = ('-date_joined',)

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Age Verification', {'fields': ('is_age_verified', 'date_of_birth', 'risk_score', 'verification_metadata')}),
        ('SaaS Info', {'fields': ('role', 'phone', 'business_name', 'business_location', 'is_approved', 'assigned_store', 'is_available', 'telegram_chat_id', 'fcm_token')}),
        ('Rider Stats', {'fields': ('total_deliveries', 'avg_rating', 'acceptance_rate')}),
        ('Bank Info', {'fields': ('bank_account_name', 'bank_account_number', 'bank_name')}),
        ('Legacy Info', {'fields': ('phone_number', 'default_hostel', 'default_room', 'student_email', 'loyalty_points', 'is_verified')}),
    )

@admin.register(FoodCategory)
class FoodCategoryAdmin(ModelAdmin):
    list_display = ('name', 'order', 'icon')
    list_editable = ('order',)
    search_fields = ('name',)
    ordering = ('order', 'name')

@admin.register(FoodItem)
class FoodItemAdmin(ModelAdmin):
    list_display = ('name', 'category', 'category_fkey', 'price', 'is_available', 'is_active', 'sku')
    list_filter = ('category', 'category_fkey', 'is_available', 'is_active', 'store')
    search_fields = ('name', 'description', 'sku')
    list_editable = ('price', 'is_available', 'is_active')
    ordering = ('-is_featured', '-times_ordered', 'name')

    fieldsets = (
        ('Basic Information', {
            'fields': ('store', 'name', 'description', 'category', 'category_fkey', 'sku', 'price', 'original_price', 'discount_percent', 'image')
        }),
        ('Availability & Features', {
            'fields': ('is_available', 'is_active', 'is_featured', 'is_meal_of_day', 'prep_time', 'stock', 'low_stock_threshold')
        }),
        ('Statistics', {
            'fields': ('times_ordered',),
            'classes': ('collapse',)
        }),
    )

@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ('order_number', 'user', 'store_type', 'status', 'assigned_rider', 'total', 'payment_method', 'payment_status', 'payment_type', 'mpesa_receipt_number', 'payment_completed_at', 'created_at')
    list_filter = ('status', 'store_type', 'payment_status', 'payment_type', 'created_at', 'estimated_delivery', 'assigned_rider')
    search_fields = ('order_number', 'user__username', 'user__email', 'mpesa_receipt_number')
    readonly_fields = ('order_number', 'created_at', 'updated_at', 'payment_completed_at', 'mpesa_checkout_request_id', 'mpesa_transaction_date', 'verification_image_display')
    ordering = ('-created_at',)

    def verification_image_display(self, obj):
        if obj.verification_image:
            url = reverse('order_verification_image', args=[obj.order_number])
            return format_html('<a href="{}" target="_blank" style="color: #0D3B30; font-weight: bold;">View Midnight Mirror Verification (AES-256 Decrypted)</a>', url)
        return "No image provided"
    
    verification_image_display.short_description = "Midnight Mirror"

    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'user', 'store', 'store_type', 'status', 'created_at', 'updated_at')
        }),
        ('Delivery Details', {
            'fields': ('hostel', 'room_number', 'phone_number', 'latitude', 'longitude', 'address_string', 'google_maps_link', 'delivery_notes', 'assigned_rider', 'estimated_delivery', 'delivered_at')
        }),
        ('Age Verification (Midnight Mirror)', {
            'fields': ('requires_rider_verification', 'rider_verified_at', 'rider_verification_method', 'verification_image_display'),
            'description': 'Encrypted verification data taken during delivery.'
        }),
        ('Pricing', {
            'fields': ('subtotal', 'delivery_fee', 'tip_amount', 'rider_base_fare', 'total', 'rating_value', 'review_text')
        }),
        ('Payment Information', {
            'fields': ('payment_method', 'payment_status', 'payment_type', 'payment_completed_at', 'payment_failure_reason', 'mpesa_checkout_request_id', 'mpesa_receipt_number', 'mpesa_transaction_date'),
            'classes': ('collapse',)
        }),
    )

@admin.register(OrderItem)
class OrderItemAdmin(ModelAdmin):
    list_display = ('order', 'food_item', 'quantity', 'price_at_order', 'subtotal')
    list_filter = ('order__status', 'food_item__category')
    search_fields = ('order__order_number', 'food_item__name')
    readonly_fields = ('subtotal',)

@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(ModelAdmin):
    list_display = ('order', 'status', 'timestamp', 'notes')
    list_filter = ('status', 'timestamp')
    search_fields = ('order__order_number', 'notes')
    readonly_fields = ('timestamp',)

@admin.register(FoodReview)
class FoodReviewAdmin(ModelAdmin):
    list_display = ('user', 'food_item', 'order', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('user__username', 'food_item__name', 'comment')
    readonly_fields = ('created_at',)

@admin.register(Promotion)
class PromotionAdmin(ModelAdmin):
    list_display = ('title', 'code', 'discount_percentage', 'discount_amount', 'is_active', 'start_date', 'end_date')
    list_filter = ('is_active', 'start_date', 'end_date')
    search_fields = ('title', 'code', 'description')
    list_editable = ('is_active',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'code')
        }),
        ('Discount Details', {
            'fields': ('discount_percentage', 'discount_amount', 'min_order_amount')
        }),
        ('Validity', {
            'fields': ('is_active', 'start_date', 'end_date', 'usage_limit', 'times_used')
        }),
    )

@admin.register(Store)
class StoreAdmin(ModelAdmin):
    list_display = ('name', 'owner', 'subdomain', 'is_active', 'plan', 'is_pro', 'subscription_active')
    list_filter = ('is_active', 'plan', 'is_pro', 'billing_status')
    search_fields = ('name', 'subdomain', 'owner__username')
    prepopulated_fields = {'subdomain': ('name',)}

    fieldsets = (
        (None, {'fields': ('owner', 'name', 'subdomain', 'is_active', 'is_pro')}),
        ('Operations', {'fields': ('opening_time', 'closing_time', 'latitude', 'longitude', 'delivery_fee', 'delivery_radius_km')}),
        ('Branding', {'fields': ('shop_name', 'logo', 'cover_image', 'primary_color', 'secondary_color', 'tagline', 'custom_domain')}),
        ('M-Pesa Daraja Credentials', {
            'fields': ('mpesa_shortcode', 'mpesa_consumer_key', 'mpesa_consumer_secret', 'mpesa_passkey', 'mpesa_callback_url'),
            'description': 'Sensitive credentials will be encrypted automatically on save.'
        }),
        ('Billing', {'fields': ('plan', 'plan_price', 'subscription_active', 'subscription_expires', 'billing_status', 'last_payment_date')}),
    )
    readonly_fields = ('subscription_active',)

    def save_model(self, request, obj, form, change):
        for field in ['mpesa_consumer_key', 'mpesa_consumer_secret', 'mpesa_passkey']:
            val = getattr(obj, field)
            if val and not val.startswith('gAAAA'):
                setattr(obj, field, encrypt_value(val))
        super().save_model(request, obj, form, change)

@admin.register(Rating)
class RatingAdmin(ModelAdmin):
    list_display = ('order', 'customer', 'store', 'store_rating', 'rider_rating', 'created_at')
    list_filter = ('store_rating', 'rider_rating', 'created_at')
    search_fields = ('order__order_number', 'customer__username', 'comment')

@admin.register(RiderEarning)
class RiderEarningAdmin(ModelAdmin):
    list_display = ('rider', 'order', 'base_fare', 'tip', 'total', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('rider__username', 'order__order_number')

@admin.register(RiderLocationPing)
class RiderLocationPingAdmin(ModelAdmin):
    list_display = ('rider', 'order', 'latitude', 'longitude', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('rider__username', 'order__order_number')

@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(ModelAdmin):
    list_display = ('store', 'amount', 'status', 'mpesa_receipt', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('store__name', 'mpesa_receipt')

@admin.register(PlatformConfig)
class PlatformConfigAdmin(ModelAdmin):
    list_display = ('daraja_shortcode',)

    def save_model(self, request, obj, form, change):
        for field in ['daraja_consumer_key', 'daraja_consumer_secret', 'daraja_passkey']:
            val = getattr(obj, field)
            if val and not val.startswith('gAAAA'):
                setattr(obj, field, encrypt_value(val))
        super().save_model(request, obj, form, change)

@admin.register(DeliveryGuy)
class DeliveryGuyAdmin(ModelAdmin):
    list_display = ('name', 'phone_number', 'is_active', 'total_deliveries', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'phone_number')
    list_editable = ('is_active',)
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('name', 'phone_number')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')

@admin.register(SiteSettings)
class SiteSettingsAdmin(ModelAdmin):
    list_display = ('delivery_fee', 'updated_at')
    
    fieldsets = (
        ('Settings', {
            'fields': ('delivery_fee',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    def has_add_permission(self, request):
        """Only allow one SiteSettings instance"""
        return not SiteSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of the singleton"""
        return False
