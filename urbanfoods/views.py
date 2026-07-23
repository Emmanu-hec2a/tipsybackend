from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .models import *
import json
import uuid
from urbanfoods.notifications import send_admin_order_notification, send_customer_order_confirmation
from urbanfoods.utils import notify_new_order
import logging
# from .mpesa_utils import mpesa  # Removed global instance
from .models import MpesaTransaction, OrderStatusHistory
from django.db import transaction
from django.conf import settings
from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, authentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from .permissions import IsCustomer, IsPartner, IsRider, IsSuperAdmin, QueryParamJWTAuthentication
from rest_framework.decorators import api_view
import requests
import os

# ==================== HOMEPAGE & FOOD CATALOG ====================

@api_view(['POST'])
def reverse_geocode(request):
    lat, lng = request.data.get('latitude'), request.data.get('longitude')
    if not lat or not lng:
        return Response({'error': 'latitude and longitude required'}, status=status.HTTP_400_BAD_REQUEST)
    
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=json"
    try:
        resp = requests.get(url, headers={'User-Agent': 'TipsyTheoryy/1.0'}, timeout=10)
        data = resp.json()
        return Response({
            'address': data.get('display_name', 'Unknown location'),
            'maps_link': f"https://www.google.com/maps?q={lat},{lng}"
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def offline(request):
    """Offline page for PWA"""
    return render(request, 'offline.html')

def get_delivery_fee_for_store(store_type, store=None, lat=None, lng=None):
    """
    Delivery fee logic:
    1. If lat/lng are provided, calculate based on distance using global SiteSettings.
    2. If a specific store is provided and no coordinates, use its configured delivery fee.
    3. Otherwise, fallback to the legacy global site settings.
    """
    from .utils import calculate_delivery_fee
    
    if lat is not None and lng is not None and store and store.latitude and store.longitude:
        return calculate_delivery_fee(lat, lng, store.latitude, store.longitude, store=store)

    if store:
        return store.delivery_fee
    
    if store_type == 'liquor':
        return SiteSettings.get_instance().delivery_fee
    return Decimal('0.00')

from django.db.models import Avg, Count, Q

from django.db.models import Avg, Count, Q

def homepage(request):
    # Use store from middleware if available (path-based routing /shop/<slug>/)
    store = getattr(request, 'store', None)
    
    store_type = request.session.get('store_type', 'liquor')
    delivery_fee = float(get_delivery_fee_for_store(store_type, store=store))

    categories = FoodCategory.objects.filter(store_type=store_type)

    category_id = request.GET.get('category')
    search_query = request.GET.get('q')

    food_items = FoodItem.objects.filter(is_available=True, store_type=store_type).annotate(
        avg_rating=Avg("reviews__rating"),
        reviews_count=Count("reviews")
    )

    # Filter by store if resolved via middleware
    if store:
        food_items = food_items.filter(store=store)
        categories = categories.filter(items__store=store).distinct()
    elif store_type == 'liquor':
        # Legacy/Global fallback for liquor store if no specific store resolved
        pass

    if category_id:
        food_items = food_items.filter(category_id=category_id)

    if search_query:
        food_items = food_items.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    meal_of_day = FoodItem.objects.filter(
        is_meal_of_day=True, is_available=True, store_type=store_type
    ).annotate(
        avg_rating=Avg("reviews__rating"),
        reviews_count=Count("reviews")
    ).first()

    featured_items = list(
        FoodItem.objects.filter(is_featured=True, is_available=True, store_type=store_type)
        .annotate(avg_rating=Avg("reviews__rating"), reviews_count=Count("reviews"))[:4]
    )

    popular_items = FoodItem.objects.filter(
        is_available=True, store_type=store_type
    ).annotate(
        avg_rating=Avg("reviews__rating"),
        reviews_count=Count("reviews")
    ).order_by('-times_ordered')[:6]

    return render(request, 'homepage.html', {
        'categories': categories,
        'food_items': food_items,
        'meal_of_day': meal_of_day,
        'featured_items': featured_items,
        'popular_items': popular_items,
        'store_type': store_type,
        'delivery_fee': delivery_fee,
    })


@require_http_methods(["POST"])
def switch_store(request):
    """Switch between food and liquor store"""
    data = json.loads(request.body)
    store_type = data.get('store_type', 'food')
    
    if store_type in ['food', 'liquor', 'grocery']:
        # Clear cart if user is authenticated and cart has items of different store type
        if request.user.is_authenticated:
            try:
                cart, _ = Cart.objects.get_or_create(user=request.user)
                if cart.items.exists():
                    # Check if cart has items of different store type
                    cart_items = cart.items.select_related('food_item').all()
                    has_different_store_type = any(
                        item.food_item.store_type != store_type for item in cart_items
                    )
                    
                    if has_different_store_type:
                        # Clear the cart
                        cart.items.all().delete()
            except Cart.DoesNotExist:
                pass
        
        request.session['store_type'] = store_type
        return JsonResponse({'success': True, 'store_type': store_type})
    
    return JsonResponse({'success': False, 'message': 'Invalid store type'}, status=400)

# ==================== AUTHENTICATION ====================

def signup_view(request):
    """User registration"""
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            data = json.loads(request.body)
            username = data.get('username')
            email = data.get('email')
            password = data.get('password')
            phone = data.get('phone')

            # Validation
            if User.objects.filter(username=username).exists():
                return JsonResponse({'success': False, 'message': 'Username already exists'})
            if User.objects.filter(email=email).exists():
                return JsonResponse({'success': False, 'message': 'Email already registered'})

            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                phone_number=phone
            )

            # Auto login
            login(request, user)

            return JsonResponse({
                'success': True,
                'message': 'Account created successfully!',
                'redirect': '/'
            })

    return render(request, 'signup.html')

def login_view(request):
    """User login"""
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            data = json.loads(request.body)
            username_or_email = data.get('username')
            password = data.get('password')
            remember = data.get('remember', False)

            user = None

            # Check if input is an email
            if '@' in username_or_email:
                try:
                    user_obj = User.objects.get(email=username_or_email)
                    user = authenticate(username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass
            else:
                # Treat as username
                user = authenticate(username=username_or_email, password=password)

            if user is not None:
                login(request, user)

                # Remember me functionality
                if not remember:
                    request.session.set_expiry(0)  # Browser close

                return JsonResponse({
                    'success': True,
                    'message': 'Login successful!',
                    'redirect': '/'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid username or password'
                })

    return render(request, 'login.html')

def logout_view(request):
    """User logout"""
    logout(request)
    return redirect('login')

# ==================== CART OPERATIONS ====================

@login_required
@require_http_methods(["POST"])
def add_to_cart(request):
    """Add item to cart"""
    data = json.loads(request.body)
    food_item_id = data.get('food_item_id')
    quantity = int(data.get('quantity', 1))

    food_item = get_object_or_404(FoodItem, id=food_item_id, is_available=True)
    cart, _ = Cart.objects.get_or_create(user=request.user)

    # Check if cart has items of different store type
    if cart.items.exists():
        cart_items = cart.items.select_related('food_item').all()
        existing_store_type = cart_items.first().food_item.store_type
        
        if existing_store_type != food_item.store_type:
            return JsonResponse({
                'success': False,
                'message': f'Cannot mix {existing_store_type} and {food_item.store_type} items in cart. Please clear your cart first or switch stores.'
            }, status=400)

    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        food_item=food_item,
        defaults={'quantity': quantity}
    )

    print("USER:", request.user, request.user.is_authenticated)

    if not created:
        cart_item.quantity += quantity
        cart_item.save()

    return JsonResponse({
        'success': True,
        'message': f'{food_item.name} added to cart',
        'cart_count': cart.item_count,
        'cart_total': float(cart.total)
    })

@login_required
@require_http_methods(["POST"])
def update_cart_item(request):
    """Update cart item quantity"""
    data = json.loads(request.body)
    cart_item_id = data.get('cart_item_id')
    quantity = int(data.get('quantity'))

    cart_item = get_object_or_404(CartItem, id=cart_item_id, cart__user=request.user)

    if quantity > 0:
        cart_item.quantity = quantity
        cart_item.save()
    else:
        cart_item.delete()

    cart = cart_item.cart if quantity > 0 else request.user.cart

    return JsonResponse({
        'success': True,
        'cart_count': cart.item_count,
        'cart_total': float(cart.total),
        'item_subtotal': float(cart_item.subtotal) if quantity > 0 else 0
    })

@login_required
@require_http_methods(["POST"])
def remove_from_cart(request):
    """Remove item from cart"""
    data = json.loads(request.body)
    cart_item_id = data.get('cart_item_id')

    cart_item = get_object_or_404(CartItem, id=cart_item_id, cart__user=request.user)
    cart_item.delete()

    cart = request.user.cart

    return JsonResponse({
        'success': True,
        'message': 'Item removed from cart',
        'cart_count': cart.item_count,
        'cart_total': float(cart.total)
    })

@login_required
def get_cart(request):
    """Get cart contents"""
    cart, _ = Cart.objects.get_or_create(user=request.user)

    items = []
    store_type = 'liquor'  # default
    store = None
    
    for item in cart.items.all():
        store_type = item.food_item.store_type
        store = item.food_item.store
        items.append({
            'id': item.id,
            'food_item_id': item.food_item.id,
            'name': item.food_item.name,
            'price': float(item.food_item.price),
            'quantity': item.quantity,
            'subtotal': float(item.subtotal),
            'image': item.food_item.image.url if item.food_item.image else None
        })

    delivery_fee = float(get_delivery_fee_for_store(store_type, store=store))

    subtotal = float(cart.total)
    total = subtotal + delivery_fee

    return JsonResponse({
        'success': True,
        'items': items,
        'cart_count': cart.item_count,
        'subtotal': subtotal,
        'delivery_fee': delivery_fee,
        'total': total
    })

# ==================== ORDER PLACEMENT ====================

# ==================== ORDER TRACKING ====================

@login_required
def my_orders(request):
    """User's order history"""
    orders = Order.objects.filter(user=request.user).prefetch_related('items')

    # Separate active and completed orders
    active_orders = orders.exclude(status__in=['delivered', 'cancelled'])
    order_history = orders.filter(status__in=['delivered', 'cancelled'])

    context = {
        'active_orders': active_orders,
        'order_history': order_history,
    }
    return render(request, 'my_orders.html', context)

@login_required
def order_detail(request, order_number):
    """View specific order details"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    status_history = order.status_history.all()
    has_food_reviews = FoodReview.objects.filter(order=order).exists()

    context = {
        'order': order,
        'status_history': status_history,
        "has_food_reviews": has_food_reviews
    }
    return render(request, 'order_detail.html', context)

@login_required
def order_status_api(request, order_number):
    """API endpoint for order status polling"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)

    return JsonResponse({
        'success': True,
        'status': order.status,
        'status_display': order.get_status_display(),
        'updated_at': order.updated_at.isoformat()
    })

# ==================== USER PROFILE ====================

@login_required
def profile(request):
    """User profile page"""
    if request.method == 'POST':
        user = request.user
        user.phone_number = request.POST.get('phone_number')
        user.default_hostel = request.POST.get('default_hostel')
        user.default_room = request.POST.get('default_room')
        user.save()

        return redirect('profile')

    recent_orders = Order.objects.filter(user=request.user)[:5]

    context = {
        'recent_orders': recent_orders,
    }
    return render(request, 'profile.html', context)

# ==================== ORDER RATING ====================

@login_required
@require_http_methods(["POST"])
def rate_order(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user, status='delivered')

    if order.rating:
        return JsonResponse({'success': False, 'message': 'Order already rated'}, status=400)

    rating = request.POST.get('rating')
    review = request.POST.get('review', '')

    if not rating or not rating.isdigit() or not (1 <= int(rating) <= 5):
        return JsonResponse({'success': False, 'message': 'Invalid rating'}, status=400)

    order.rating = int(rating)
    order.review = review
    order.has_reviewed_items = True  # add this boolean field
    order.save(update_fields=["rating", "review", "has_reviewed_items"])

    return JsonResponse({'success': True})

# ==================== FOOD REVIEWS ====================

import json

@login_required
@require_http_methods(["POST"])
def submit_food_review(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    
    if order.status != 'delivered':
        return JsonResponse({'success': False, 'message': 'Only delivered orders can be reviewed'}, status=400)
    
    # Prevent duplicate submissions
    if order.has_reviewed_items:
        return JsonResponse({'success': False, 'message': 'Already reviewed'}, status=400)

    try:
        reviews = json.loads(request.body)  # JS sends JSON, not form data
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid data'}, status=400)

    if not isinstance(reviews, list) or len(reviews) == 0:
        return JsonResponse({'success': False, 'message': 'No reviews provided'}, status=400)

    created_any = False
    for review_data in reviews:
        food_item_id = review_data.get('food_item_id')
        rating = review_data.get('rating')
        comment = review_data.get('comment', '')

        if not food_item_id or not rating:
            continue

        # Ensure the food item belongs to this order
        if not order.items.filter(food_item_id=food_item_id).exists():
            continue

        try:
            food_item = FoodItem.objects.get(id=food_item_id)
        except FoodItem.DoesNotExist:
            continue

        obj, created = FoodReview.objects.get_or_create(
            user=request.user,
            food_item=food_item,
            order=order,
            defaults={"rating": int(rating), "comment": comment}
        )
        if created:
            created_any = True

    if created_any:
        order.has_reviewed_items = True
        order.save(update_fields=["has_reviewed_items"])

    return JsonResponse({"success": True})


# ==================== REVIEW PROMPT ENDPOINTS ====================

@login_required
@require_http_methods(["GET"])
def pending_review_order(request):
    """Get the oldest delivered order without reviews, if under review prompt limit"""
    order = (
        Order.objects
        .filter(
            user=request.user,
            status='delivered',
            has_reviewed_items=False,
            review_prompted_count__lt=3
        )
        .order_by('delivered_at')
        .first()
    )
    
    if not order:
        return JsonResponse({'success': False, 'order': None})
    
    # Serialize order and items
    items_data = []
    for item in order.items.all():
        items_data.append({
            'id': item.id,
            'food_item_id': item.food_item.id,
            'name': item.food_item.name,
            'image_url': item.food_item.image.url if item.food_item.image else '',
            'quantity': item.quantity,
        })
    
    return JsonResponse({
        'success': True,
        'order': {
            'order_number': order.order_number,
            'items': items_data,
        }
    })


@login_required
@require_http_methods(["POST"])
def dismiss_review_prompt(request, order_number):
    """Increment review prompt count when user dismisses the modal"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    
    if order.review_prompted_count >= 3:
        return JsonResponse({'success': False, 'message': 'Maximum prompts reached'}, status=400)
    
    order.review_prompted_count += 1
    order.review_prompt_dismissed_at = timezone.now()
    order.save(update_fields=['review_prompted_count', 'review_prompt_dismissed_at'])
    
    return JsonResponse({'success': True})



# ==================== ORDER CANCELLATION ====================

@login_required
@require_http_methods(["POST"])
def cancel_order(request, order_number):
    """Cancel an order with reason"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)

    # Only allow cancellation for pending or preparing orders
    if order.status not in ['pending', 'preparing']:
        return JsonResponse({'success': False, 'message': 'Order cannot be cancelled at this stage'})

    reason = request.POST.get('reason', '').strip()
    if not reason:
        return JsonResponse({'success': False, 'message': 'Please provide a cancellation reason'})

    # Update order status
    order.status = 'cancelled'
    order.cancellation_reason = reason
    order.save()

    # Create status history
    OrderStatusHistory.objects.create(
        order=order,
        status='cancelled',
        notes=f'Cancelled by user: {reason}'
    )

    return JsonResponse({'success': True, 'message': 'Order cancelled successfully'})

# ================= ROBOTS.TXT VIEW =================
from django.http import HttpResponse
from django.views.decorators.http import require_GET

@require_GET
def robots_txt(request):
    content = (
        "User-agent: *\n"
        "Allow: /\n\n"
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml\n"
    )
    return HttpResponse(content, content_type="text/plain")


# ==================== MPESA INTEGRATION ====================

# Removed duplicate initiate_mpesa_payment from here.
# It is defined later in the file near line 1256.

import json
import logging
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Cart, MpesaTransaction, Order, OrderItem, OrderStatusHistory
# from .mpesa_utils import mpesa  # Removed global instance
from .utils import is_within_delivery_zone
import logging, json
from django.utils import timezone

mpesa_logger = logging.getLogger("mpesa")

def log_mpesa_event(event_type, user_id=None, order_number=None, phone=None, amount=None, extra=None):
    log_data = {
        "event_type": event_type,
        "user_id": user_id,
        "order_number": order_number,
        "phone": f"+2547XXX{phone[-4:]}" if phone else None,
        "amount": float(amount) if amount else None,
        "timestamp": timezone.now().isoformat(),
    }
    if extra:
        log_data.update(extra)
    mpesa_logger.info(json.dumps(log_data))


logger = logging.getLogger(__name__)



# ─────────────────────────────────────────────────────────────
#  SAFARICOM IP ALLOWLIST
#  https://developer.safaricom.co.ke/docs#callbacks
# ─────────────────────────────────────────────────────────────
SAFARICOM_IPS = {
    '196.201.214.200', '196.201.214.206', '196.201.213.114',
    '196.201.214.207', '196.201.214.208', '196.201.213.44',
    '196.201.212.127', '196.201.212.138', '196.201.212.129',
    '196.201.212.136', '196.201.212.74', '196.201.212.69',
}


def _get_client_ip(request):
    """Return the real client IP, respecting X-Forwarded-For from trusted proxies."""
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def safaricom_ip_required(view_func):
    """
    Decorator that rejects requests not originating from Safaricom's
    known callback IPs with a silent 403.
    """
    def wrapper(request, *args, **kwargs):
        if _get_client_ip(request) not in SAFARICOM_IPS:
            logger.warning(
                "Blocked callback attempt from unauthorized IP: %s",
                _get_client_ip(request)
            )
            return HttpResponse(status=403)
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


# ── Shared Payment Confirmation ──
def _confirm_payment(order, receipt_number=None, notes='Payment confirmed'):
    """Mark order as paid and handle inventory/loyalty side effects."""
    order.payment_status = 'paid'
    order.status = 'pending'
    order.payment_completed_at = timezone.now()
    if receipt_number:
        order.mpesa_receipt_number = receipt_number
    order.save()

    # Update stats
    items = list(order.items.select_related('food_item'))
    for item in items:
        item.food_item.times_ordered = F('times_ordered') + item.quantity

    from .models import FoodItem
    FoodItem.objects.bulk_update([item.food_item for item in items], ['times_ordered'])

    # Clear Cart
    from .models import CartItem
    CartItem.objects.filter(cart__user=order.user).delete()

    # Loyalty
    order.user.loyalty_points = F('loyalty_points') + int(order.total)
    order.user.save(update_fields=['loyalty_points'])

    OrderStatusHistory.objects.create(order=order, status='pending', notes=notes)

    # Notifications (Wrapped in try-except to prevent crashing the payment flow)
    try:
        from .utils import notify_payment_received, update_weekly_revenue_share
        update_weekly_revenue_share(order)
        notify_payment_received(order)
        send_customer_order_confirmation(order)
        send_admin_order_notification(order)
    except Exception as e:
        logger.error(f"Post-payment notifications failed for order {order.order_number}: {e}")


def _fail_payment(order, reason=''):
    """Mark an order payment as failed — no atomic block needed (simple update)."""
    order.payment_status = 'failed'
    order.status = 'cancelled'
    order.payment_failure_reason = reason
    order.save(update_fields=['payment_status', 'status', 'payment_failure_reason'])

    OrderStatusHistory.objects.create(
        order=order,
        status='cancelled',
        notes=f'Payment failed: {reason}'
    )


# ─────────────────────────────────────────────────────────────
#  PLACE ORDER
# ─────────────────────────────────────────────────────────────
@login_required
@require_http_methods(["POST"])
def place_order(request):
    """Place a new order (M-Pesa or Cash on Delivery)."""
    data = json.loads(request.body)

    cart = get_object_or_404(Cart, user=request.user)

    if not cart.items.exists():
        return JsonResponse({'success': False, 'message': 'Cart is empty'})

    hostel = data.get('hostel')
    room_number = data.get('room_number')
    phone_number = data.get('phone_number')
    delivery_notes = data.get('delivery_notes', '')
    payment_method = data.get('payment_method', 'cash')

    lat = data.get('latitude')
    lng = data.get('longitude')
    address_string = data.get('address_string')

    if payment_method not in ['mpesa', 'cash']:
        return JsonResponse({'success': False, 'message': 'Invalid payment method'})

    # ── Totals ──
    subtotal = cart.total
    first_item = cart.items.select_related('food_item').prefetch_related('food_item__store').first()
    store = first_item.food_item.store if first_item else None
    
    if not store:
        # Fallback for legacy items without store
        from .models import Store
        store = Store.objects.first()
        
    if lat and lng:
        within, distance = is_within_delivery_zone(store, float(lat), float(lng))
        if not within:
            return JsonResponse({
                'success': False,
                'error': 'outside_zone',
                'message': f'You are {distance}km away. We deliver within {store.delivery_radius_km}km.',
                'distance_km': distance
            }, status=400)

    store_type = first_item.food_item.store_type if first_item else 'liquor'
    
    delivery_fee = get_delivery_fee_for_store(store_type, store=store, lat=lat, lng=lng)
    
    total = subtotal + delivery_fee
    estimated_delivery = timezone.now() + timezone.timedelta(minutes=30)

    # ══════════════════════════════
    #  M-PESA PAYMENT
    # ══════════════════════════════
    if payment_method == 'mpesa':
        from .mpesa_utils import MpesaIntegration
        mpesa_service = MpesaIntegration(store=store)
        
        try:
            formatted_phone = mpesa_service.format_phone_number(phone_number)
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)})

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user,
                    hostel=hostel,
                    room_number=room_number,
                    phone_number=formatted_phone,
                    latitude=lat,
                    longitude=lng,
                    address_string=address_string,
                    google_maps_link=f"https://www.google.com/maps?q={lat},{lng}" if lat and lng else None,
                    delivery_notes=delivery_notes,
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    total=total,
                    payment_method='mpesa',
                    store=store,
                    store_type=store_type,
                    payment_type='paybill',
                    payment_status='pending',
                    status='payment_pending',
                    estimated_delivery=estimated_delivery,
                )

                OrderItem.objects.bulk_create([
                    OrderItem(
                        order=order,
                        food_item=item.food_item,
                        quantity=item.quantity,
                        price_at_order=item.food_item.price,
                    )
                    for item in cart.items.select_related('food_item')
                ])

                OrderStatusHistory.objects.create(
                    order=order,
                    status='payment_pending',
                    notes='Order created — awaiting M-Pesa STK payment',
                )

                # ── Initiate STK push ──
                stk_response = mpesa_service.initiate_stk_push(
                    phone_number=formatted_phone,
                    amount=int(total),
                    account_reference=order.order_number,
                    transaction_desc="Tipsy Theoryy Order"
                )

                if not stk_response.get('success'):
                    raise Exception(stk_response.get('message') or 'STK push failed')

                order.mpesa_checkout_request_id = stk_response.get('checkout_request_id')
                order.save(update_fields=['mpesa_checkout_request_id'])

        except Exception as e:
            logger.exception("M-Pesa STK push failed for user %s", request.user.id)
            return JsonResponse({
                'success': False,
                'message': f'Payment initiation failed: {e}',
            })

        return JsonResponse({
            'success': True,
            'message': stk_response.get('customer_message', 'STK push sent — check your phone'),
            'order_number': order.order_number,
            'checkout_request_id': order.mpesa_checkout_request_id,
            'payment_method': 'mpesa',
            'estimated_delivery': estimated_delivery.strftime('%I:%M %p'),
            'awaiting_payment': True,
        })

    # ══════════════════════════════
    #  CASH ON DELIVERY
    # ══════════════════════════════
    with transaction.atomic():
        order = Order.objects.create(
            user=request.user,
            hostel=hostel,
            room_number=room_number,
            phone_number=phone_number,
            latitude=lat,
            longitude=lng,
            address_string=address_string,
            google_maps_link=f"https://www.google.com/maps?q={lat},{lng}" if lat and lng else None,
            delivery_notes=delivery_notes,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            total=total,
            payment_method='cash',
            store=store,
            store_type=store_type,
            payment_status='pending',
            status='pending',
            estimated_delivery=estimated_delivery,
        )

        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                food_item=item.food_item,
                quantity=item.quantity,
                price_at_order=item.food_item.price,
            )
            for item in cart.items.select_related('food_item')
        ])

        # ── Update stats atomically ──
        cart_items = list(cart.items.select_related('food_item'))
        for cart_item in cart_items:
            cart_item.food_item.times_ordered = F('times_ordered') + cart_item.quantity

        from .models import FoodItem
        FoodItem.objects.bulk_update(
            [ci.food_item for ci in cart_items],
            ['times_ordered']
        )

        # ── Clear cart items (keep Cart row) ──
        cart.items.all().delete()

        # ── Award loyalty points ──
        order.user.loyalty_points = F('loyalty_points') + int(total)
        order.user.save(update_fields=['loyalty_points'])

        OrderStatusHistory.objects.create(
            order=order,
            status='pending',
            notes='Order placed — Cash on delivery',
        )

        notify_new_order(order)
        send_customer_order_confirmation(order)
        send_admin_order_notification(order)

    return JsonResponse({
        'success': True,
        'message': 'Order placed successfully!',
        'order_number': order.order_number,
        'payment_method': 'cash',
        'estimated_delivery': estimated_delivery.strftime('%I:%M %p'),
    })


# ─────────────────────────────────────────────────────────────
#  M-PESA CALLBACK  (called by Safaricom — no auth, IP-guarded)
# ─────────────────────────────────────────────────────────────
@csrf_exempt                  # Safaricom cannot send CSRF tokens
@safaricom_ip_required        # Only accept known Safaricom IPs
@require_http_methods(["POST"])
def mpesa_callback(request):
    try:
        callback_data = json.loads(request.body)
        stk_callback = callback_data.get('Body', {}).get('stkCallback', {})
        result_code = stk_callback.get('ResultCode')
        result_desc = stk_callback.get('ResultDesc', '')
        checkout_request_id = stk_callback.get('CheckoutRequestID')

        if not checkout_request_id:
            return HttpResponse("OK")

        try:
            order = Order.objects.select_related('user').get(
                mpesa_checkout_request_id=checkout_request_id
            )
        except Order.DoesNotExist:
            logger.warning(
                "Callback received for unknown CheckoutRequestID: %s",
                checkout_request_id,
            )
            return HttpResponse("OK")

        # ── Idempotency guard ──
        if order.payment_status == 'paid':
            return HttpResponse("OK")

        # ── Parse callback metadata ──
        metadata = stk_callback.get('CallbackMetadata', {}).get('Item', [])
        mpesa_receipt = None
        callback_phone = None
        amount = None

        for item in metadata:
            name = item.get('Name')
            if name == 'MpesaReceiptNumber': mpesa_receipt = item.get('Value')
            elif name == 'PhoneNumber': callback_phone = item.get('Value')
            elif name == 'Amount': amount = item.get('Value')

        # ── Always persist the raw transaction (audit trail) ──
        MpesaTransaction.objects.create(
            order=order,
            checkout_request_id=checkout_request_id,
            mpesa_receipt_number=mpesa_receipt,
            phone_number=str(callback_phone) if callback_phone else '',
            amount=Decimal(str(amount)) if amount else Decimal('0.00'),
            result_code=result_code,
            result_desc=result_desc,
            raw_callback=callback_data,
        )

         # Log structured
        log_mpesa_event(
            event_type="callback_received",
            user_id=order.user.id,
            order_number=order.order_number,
            phone=str(callback_phone),
            amount=amount,
            extra={"checkout_request_id": checkout_request_id, "result_code": result_code, "result_desc": result_desc}
        )

        # ── Payment failed ──
        if result_code != 0:
            _fail_payment(order, reason=result_desc)
            return HttpResponse("OK")

        # ── Validate amount ──
        is_production = os.environ.get('MPESA_PRODUCTION', 'false').lower() == 'true'
        received_amount = Decimal(str(amount))
        
        # In sandbox/test mode, we often pay 1.0. 
        # In production, we expect the EXACT total.
        is_valid_amount = (received_amount == order.total) or (not is_production and received_amount == Decimal('1.0'))

        if not is_valid_amount:
            _fail_payment(order, reason=f'Amount mismatch: received {amount} expected {order.total}')
            logger.error(
                "Amount mismatch on order %s: received %s expected %s",
                order.order_number, amount, order.total,
            )
            return HttpResponse("OK")

        # ── Validate phone ──
        # Relaxed matching for testing/production flexibility
        def clean_phone(p):
            return ''.join(filter(str.isdigit, str(p)))[-9:]

        if callback_phone and order.phone_number:
            if clean_phone(callback_phone) != clean_phone(order.phone_number):
                logger.warning(
                    "Phone mismatch on order %s: received %s expected %s. Proceeding since CheckoutID matches.",
                    order.order_number, callback_phone, order.phone_number,
                )

    # ── All checks passed — confirm payment ──
        with transaction.atomic():
            _confirm_payment(
                order,
                receipt_number=mpesa_receipt,
                notes=f'Payment confirmed via callback. Receipt: {mpesa_receipt}',
            )

    except Exception:
        logger.exception("Unhandled error in mpesa_callback")

    return HttpResponse("OK")


# ─────────────────────────────────────────────────────────────
#  STK QUERY  (client-side polling fallback)
# ─────────────────────────────────────────────────────────────
@login_required
@require_http_methods(["POST"])
def mpesa_stk_query(request):
    """
    Fallback for when the Safaricom callback is delayed.
    The frontend polls this endpoint while the payment modal is open.
    """
    data = json.loads(request.body)
    checkout_request_id = data.get('checkout_request_id')

    if not checkout_request_id:
        return JsonResponse({'success': False, 'message': 'checkout_request_id required'})

    # ── Guard: only allow the order owner to query ──
    try:
        order = Order.objects.select_related('user').get(
            mpesa_checkout_request_id=checkout_request_id,
            user=request.user,          # prevents other users querying someone else's order
        )
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'})

    # ── Idempotency: already done via callback ──
    if order.payment_status == 'paid':
        return JsonResponse({
            'success': True,
            'result_code': 0,
            'result_desc': 'Payment already confirmed',
            'payment_status': 'paid',
        })

    # ── Ask Safaricom ──
    from .mpesa_utils import MpesaIntegration
    mpesa_service = MpesaIntegration(store=order.store)
    result = mpesa_service.query_stk_status(checkout_request_id)

    # Log structured
    log_mpesa_event(
        event_type="stk_query",
        user_id=order.user.id,
        order_number=order.order_number,
        phone=order.phone_number,
        amount=order.total,
        extra={"checkout_request_id": checkout_request_id, "result": result}
    )

    if not result.get('success'):
        return JsonResponse(result)

    result_code = result.get('result_code')

    if result_code == 0:
        # Payment successful — reuse shared helper
        with transaction.atomic():
            _confirm_payment(
                order,
                notes='Payment confirmed via STK query',
            )
        result['payment_status'] = 'paid'

    elif result_code in [1, 1032, 1037]:
        # 1    = Insufficient funds
        # 1032 = Request cancelled by user
        # 1037 = DS timeout (user never responded)
        _fail_payment(order, reason=result.get('result_desc', 'Payment failed'))
        result['payment_status'] = 'failed'

    else:
        # Still pending — tell the frontend to keep polling
        result['payment_status'] = 'pending'

    return JsonResponse(result)


# ─────────────────────────────────────────────────────────────
#  PAYMENT STATUS POLL  (lightweight, cacheable)
# ─────────────────────────────────────────────────────────────
@login_required
@require_http_methods(["GET"])
def check_order_payment_status(request, order_number):
    """
    Lightweight endpoint for the frontend payment-waiting screen.
    Returns only what the UI needs — no sensitive data.
    """
    try:
        order = Order.objects.only(
            'payment_status', 'status', 'mpesa_receipt_number'
        ).get(order_number=order_number, user=request.user)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)

    return JsonResponse({
        'success': True,
        'payment_status': order.payment_status,
        'order_status': order.status,
        'mpesa_receipt_number': order.mpesa_receipt_number,
    })


# ─────────────────────────────────────────────────────────────
#  INITIATE MPESA PAYMENT  (retry for existing order)
# ─────────────────────────────────────────────────────────────
@login_required
@require_http_methods(["POST"])
def initiate_mpesa_payment(request):
    """Re-initiate an STK push for an existing unpaid order."""
    data = json.loads(request.body)
    order_number = data.get('order_number')

    if not order_number:
        return JsonResponse({'success': False, 'message': 'Order number required'})

    try:
        order = Order.objects.get(order_number=order_number, user=request.user)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'})

    if order.payment_status == 'paid':
        return JsonResponse({'success': False, 'message': 'Payment already completed'})

    from .mpesa_utils import MpesaIntegration
    mpesa_service = MpesaIntegration(store=order.store)

    try:
        formatted_phone = mpesa_service.format_phone_number(order.phone_number)
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)})

    stk_result = mpesa_service.initiate_stk_push(
        phone_number=formatted_phone,
        amount=int(order.total),
        account_reference=order.order_number,
        transaction_desc=f"Order {order.order_number}"
    )

    # Log initiation
    log_mpesa_event(
        event_type="stk_initiated",
        user_id=request.user.id,
        order_number=order.order_number,
        phone=formatted_phone,
        amount=int(order.total),
        extra={"checkout_request_id": stk_result.get("checkout_request_id")}
    )

    if not stk_result.get('success'):
        return JsonResponse({'success': False, 'message': stk_result.get('message')})

    order.mpesa_checkout_request_id = stk_result['checkout_request_id']
    order.payment_status = 'pending'
    order.save(update_fields=['mpesa_checkout_request_id', 'payment_status'])

    OrderStatusHistory.objects.create(
        order=order,
        status=order.status,
        notes=f"STK push re-sent to {formatted_phone}",
    )

    return JsonResponse({
        'success': True,
        'message': stk_result.get('customer_message', 'STK push sent'),
        'checkout_request_id': stk_result['checkout_request_id'],
    })


class SaveFCMTokenView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({'error': 'Token required'}, status=status.HTTP_400_BAD_REQUEST)
        request.user.fcm_token = token
        request.user.save()
        logger.info(f"FCM Token updated for user {request.user.username}")
        return Response({'status': 'ok'})

class TestFCMNotificationView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        if not request.user.is_staff:
            return Response({'error': 'Admin only'}, status=status.HTTP_403_FORBIDDEN)
        
        target_username = request.data.get('username')
        title = request.data.get('title', 'Test Notification')
        body = request.data.get('body', 'This is a test notification from TipsyTheoryy')
        
        try:
            from .models import User
            from .utils import send_fcm_notification
            user = User.objects.get(username=target_username)
            success = send_fcm_notification(user, title, body, {'type': 'test'})
            return Response({'status': 'sent' if success else 'failed', 'token_exists': bool(user.fcm_token)})
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ==================== API v1 AUTH & PERMISSIONS ====================

def get_tokens(user):
    refresh = RefreshToken.for_user(user)
    refresh['role'] = user.role
    refresh['store_id'] = getattr(getattr(user, 'store', None), 'id', None)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'role': user.role
    }

class CustomerLoginView(APIView):
    permission_classes = []
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if not user or user.role != 'customer':
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(get_tokens(user))

class PartnerLoginView(APIView):
    permission_classes = []
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if not user or user.role != 'partner':
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        if not user.is_approved:
            return Response({'error': 'Account pending approval.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(get_tokens(user))

class RiderLoginView(APIView):
    permission_classes = []
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=username, password=password)
        if not user or user.role != 'rider':
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(get_tokens(user))

class PartnerSignupView(APIView):
    permission_classes = []
    def post(self, request):
        try:
            email = request.data['email']
            username = request.data.get('username', email) # Use email as username if not provided
            password = request.data['password']
            business_name = request.data['business_name']
            business_location = request.data['business_location']
            phone = request.data.get('phone', '')
            
            user = User.objects.create_user(
                username=username, 
                email=email,
                password=password, 
                role='partner',
                phone=phone,
                business_name=business_name,
                business_location=business_location,
                is_approved=False,
            )
            from .utils import notify_superadmin_new_partner
            notify_superadmin_new_partner(user)
            return Response({'message': 'Application received. We will contact you within 24 hours.'}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class PartnerApprovalView(APIView):
    permission_classes = [IsSuperAdmin]
    def post(self, request, user_id):
        try:
            partner = User.objects.get(id=user_id, role='partner')
            partner.is_approved = True
            partner.save()
            
            from .models import Store
            Store.objects.get_or_create(
                owner=partner, 
                defaults={
                    'name': partner.business_name,
                    'is_active': True,
                    'latitude': -1.286389,
                    'longitude': 36.817223
                }
            )
            
            from .utils import notify_partner_approved
            notify_partner_approved(partner)
            return Response({'message': f'{partner.business_name} is now live.'})
        except User.DoesNotExist:
            return Response({'error': 'Partner not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class TestCustomerView(APIView):
    permission_classes = [IsCustomer]
    def get(self, request):
        return Response({'message': 'Hello Customer!'})

class TestPartnerView(APIView):
    permission_classes = [IsPartner]
    def get(self, request):
        return Response({'message': 'Hello Partner!'})

class TestRiderView(APIView):
    permission_classes = [IsRider]
    def get(self, request):
        return Response({'message': 'Hello Rider!'})

class TestSuperAdminView(APIView):
    permission_classes = [IsSuperAdmin]
    def get(self, request):
        return Response({'message': 'Hello SuperAdmin!'})

class OrderVerificationImageView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [QueryParamJWTAuthentication, authentication.SessionAuthentication]

    def get(self, request, order_number):
        from .models import Order
        from .utils import decrypt_verification_image
        from django.http import HttpResponse, Http404
        
        try:
            order = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            raise Http404

        # Permission check: Admin or Partner who owns the store
        if not (request.user.role == 'superadmin' or 
                (request.user.role == 'partner' and order.store and order.store.owner == request.user)):
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        if not order.verification_image:
            return Response({'error': 'No verification image found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            # Handle potential Cloudinary or local storage
            encrypted_data = order.verification_image.read()
            decrypted_data = decrypt_verification_image(encrypted_data)
            return HttpResponse(decrypted_data, content_type="image/jpeg")
        except Exception as e:
            return Response({'error': f'Decryption failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class TheoryAIChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_message = request.data.get('message', '').lower()
        lat = request.data.get('lat')
        lng = request.data.get('lng')

        if not user_message:
            return Response({'error': 'Message required'}, status=400)

        # 1. Intent Detection
        intent = 'conversation'
        action = None
        action_data = {}

        # Basic Intent Mapping
        if any(kw in user_message for kw in ['checkout', 'pay', 'done', 'buy now']):
            intent = 'checkout'
            action = 'NAVIGATE'
            action_data = {'screen': '/checkout'}
            response_text = "Sure thing. Heading to checkout now."
        
        elif any(kw in user_message for kw in ['cart', 'basket']):
            intent = 'view_cart'
            action = 'NAVIGATE'
            action_data = {'screen': '/cart'}
            response_text = "Of course. Opening your cart."

        elif any(kw in user_message for kw in ['add', 'get me', 'want to buy']):
            intent = 'add_to_cart'
            search_query = user_message.replace('add', '').replace('get me', '').replace('to my cart', '').strip()
            
            product = self._search_best_match(search_query, lat, lng)
            if product:
                action = 'ADD_TO_CART'
                action_data = {
                    'product_id': product.id,
                    'name': product.name,
                    'price': float(product.price),
                    'store_id': product.store.id,
                    'store_name': product.store.name,
                    'delivery_fee': float(product.store.delivery_fee)
                }
                response_text = f"Done. Added {product.name} to your cart. Anything else?"
            else:
                response_text = "Sorry, I couldn't find that one. Try another brand?"

        else:
            # Default to Search/Recommendation
            intent = 'search'
            products = self._search_nearby_products(user_message, lat, lng)
            
            if products:
                action = 'SEARCH_RESULTS'
                action_data = {'query': user_message}
                top_p = products[0]
                response_text = f"Found it! {top_p.name} from {top_p.store.name} is available. Check the list."
            else:
                if 'party' in user_message or 'friends' in user_message:
                    response_text = "For a crowd, I'd suggest some Gin and tonics. I've found a few options nearby."
                elif 'emergency' in user_message or 'out of' in user_message:
                    response_text = "On it. Here's the closest open store for mixers and ice."
                else:
                    response_text = "Welcome to the Theory. What can I get for you tonight?"

        return Response({
            'text': response_text,
            'intent': intent,
            'action': action,
            'action_data': action_data
        })

    def _search_best_match(self, query, lat, lng):
        products = self._search_nearby_products(query, lat, lng)
        return products[0] if products else None

    def _search_nearby_products(self, query, lat, lng):
        from .models import FoodItem, Store
        
        today = timezone.now().date()
        
        # Base filter: active items from active stores with valid subscriptions
        queryset = FoodItem.objects.filter(
            is_active=True,
            store__is_active=True,
            store__subscription_expires__gte=today,
            store__billing_status='active'
        ).select_related('store')

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) | 
                Q(description__icontains=query) |
                Q(category_fkey__name__icontains=query)
            )

        # 🛡️ Radius Enforcement in AI Search
        if lat and lng:
            try:
                u_lat = float(lat)
                u_lng = float(lng)
                from .utils import haversine_distance_km
                
                # Fetch candidate products first (limited set to avoid heavy distance calc on all)
                candidates = list(queryset[:50])
                filtered = []
                for p in candidates:
                    if p.store.latitude and p.store.longitude:
                        dist = haversine_distance_km(u_lat, u_lng, p.store.latitude, p.store.longitude)
                        if dist <= p.store.delivery_radius_km:
                            p.ai_distance = dist # Temporarily attach distance
                            filtered.append(p)
                    else:
                        filtered.append(p) # If store has no coords, keep it? or skip?
                
                # Sort by Pro then distance
                filtered.sort(key=lambda x: (-x.store.is_pro, getattr(x, 'ai_distance', 999)))
                return filtered[:5]
            except Exception:
                pass

        # Pro stores and name priority fallback
        queryset = queryset.order_by('-store__is_pro', 'name')
        return queryset[:5]

class TempVoiceUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=400)

        # 🛡️ Save to R2 (Cloudflare) or local media
        # Since 'django-storages' is likely configured for R2/S3
        from django.core.files.storage import default_storage
        from django.utils.crypto import get_random_string
        
        # Generate a unique filename with .m4a extension
        ext = file_obj.name.split('.')[-1] if '.' in file_obj.name else 'm4a'
        file_name = f"temp_voice/{get_random_string(12)}.{ext}"
        
        saved_path = default_storage.save(file_name, file_obj)
        public_url = default_storage.url(saved_path)
        
        return Response({'url': public_url})

class SecureTranscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=400)

        # 1. Save to R2 to get a public URL for Netmind
        from django.core.files.storage import default_storage
        from django.utils.crypto import get_random_string
        
        ext = file_obj.name.split('.')[-1] if '.' in file_obj.name else 'm4a'
        file_name = f"temp_voice/{get_random_string(12)}.{ext}"
        saved_path = default_storage.save(file_name, file_obj)
        audio_url = default_storage.url(saved_path)

        # 2. Netmind Orchestration
        netmind_key = os.environ.get('NETMIND_API_KEY')
        if not netmind_key:
            return Response({'error': 'Transcription service not configured'}, status=500)

        try:
            # Initiate
            headers = {"Authorization": f"Bearer {netmind_key}", "Content-Type": "application/json"}
            init_resp = requests.post(
                "https://api.netmind.ai/v1/generation",
                headers=headers,
                json={
                    "model": "openai/whisper",
                    "config": {
                        "audio_url": audio_url,
                        "task": "transcribe",
                        "chunk_level": "segment",
                        "version": "3",
                        "batch_size": 64
                    }
                },
                timeout=10
            )
            
            init_data = init_resp.json()
            gen_id = init_data.get('generation_id')
            if not gen_id:
                logger.error(f"Netmind Initiation Error: {init_data}")
                return Response({
                    'error': 'Failed to initiate transcription',
                    'details': init_data.get('message', 'No details from service')
                }, status=status.HTTP_502_BAD_GATEWAY)

            # 3. Polling
            import time
            attempts = 0
            while attempts < 30:
                poll_resp = requests.get(f"https://api.netmind.ai/v1/generation/{gen_id}", headers=headers, timeout=10)
                data = poll_resp.json()
                
                if data.get('status') in ['completed', 'success']:
                    results = data.get('results', [])
                    text = " ".join([s['text'] for s in results]) if isinstance(results, list) else data.get('text', '')
                    return Response({'text': text})
                elif data.get('status') == 'failed':
                    return Response({'error': 'Transcription failed'}, status=502)
                
                time.sleep(1)
                attempts += 1
            
            return Response({'error': 'Transcription timed out'}, status=504)

        except Exception as e:
            return Response({'error': str(e)}, status=500)

class SecureTTSView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        text = request.data.get('text')
        if not text:
            return Response({'error': 'Text required'}, status=400)

        openai_key = os.environ.get('OPENAI_API_KEY')
        if not openai_key:
            return Response({'error': 'TTS service not configured'}, status=500)

        try:
            # 1. Call OpenAI TTS
            resp = requests.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {openai_key}"},
                json={
                    "model": "tts-1",
                    "input": text,
                    "voice": "onyx"
                },
                timeout=30
            )

            if resp.status_code != 200:
                return Response({'error': 'OpenAI TTS failed'}, status=resp.status_code)

            # 2. Save to R2
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            from django.utils.crypto import get_random_string
            
            file_name = f"tts/{get_random_string(12)}.mp3"
            saved_path = default_storage.save(file_name, ContentFile(resp.content))
            audio_url = default_storage.url(saved_path)

            return Response({'url': audio_url})

        except Exception as e:
            return Response({'error': str(e)}, status=500)
