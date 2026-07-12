from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST, require_GET
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.hashers import check_password
from django.http import JsonResponse, HttpResponse
from django.db.models.functions import ExtractHour, TruncDate
from django.db.models import Count, Sum, Avg, Max, F, Q
from django.db import models
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from datetime import timedelta, datetime
from .utils import send_push_to_all, notify_low_stock
from .models import *
import json

def staff_member_required(view_func=None, login_url='admin_login'):
    actual_decorator = user_passes_test(
        lambda u: u.is_active and (u.is_staff or (hasattr(u, 'role') and u.role == 'partner')),
        login_url=login_url
    )
    if view_func:
        return actual_decorator(view_func)
    return actual_decorator

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.http import JsonResponse
import json

def admin_login(request):
    """Admin login page with AJAX support"""
    # If staff user or partner is already logged in
    if request.user.is_authenticated and (request.user.is_staff or (hasattr(request.user, 'role') and request.user.role == 'partner')):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # AJAX request: return JSON
            return JsonResponse({
                'success': True,
                'redirect': '/admin-panel/liquor/dashboard/'
            })
        # Normal request: redirect
        return redirect('/admin-panel/liquor/dashboard/')

    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return JsonResponse({'success': False, 'message': 'Username and password are required'}, status=400)

        user = authenticate(username=username, password=password)

        if user is not None and (user.is_staff or (hasattr(user, 'role') and user.role == 'partner')):
            login(request, user)
            return JsonResponse({
                'success': True,
                'message': 'Admin login successful!',
                'redirect': '/admin-panel/liquor/dashboard/'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Invalid admin credentials or insufficient permissions'
            }, status=401)

    # For non-AJAX GET requests, render the login page
    return render(request, 'custom_admin/login.html')

@staff_member_required
@require_GET
def mpesa_payment_details(request):
    order_number = request.GET.get('order_number')
    if not order_number:
        return JsonResponse({'success': False, 'message': 'order_number required'}, status=400)

    try:
        order = Order.objects.get(order_number=order_number)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)

    payment = order.mpesa_transactions.order_by('-created_at').first()

    if not payment:
        return JsonResponse({'success': True, 'payment': None})

    # Convert result_code to status
    if payment.result_code == 0:
        status = 'completed'
    elif payment.result_code is None:
        status = 'pending'
    else:
        status = 'failed'

    data = {
        'amount': str(payment.amount),
        'mpesa_receipt_number': payment.mpesa_receipt_number,
        'checkout_request_id': payment.checkout_request_id,
        'phone_number': payment.phone_number,
        'order_number': order.order_number,
        'status': status,
        'result_description': payment.result_desc,
        'transaction_date': payment.transaction_date,
        'created_at': payment.created_at.isoformat(),
    }

    return JsonResponse({'success': True, 'payment': data})


# ==================== ADMIN DASHBOARD ====================

VALID_STATUSES = ['delivered', 'completed']

from django.db.models import Sum, F, ExpressionWrapper, DecimalField

def get_liquor_stats(date, week_start):
    """Return today's and weekly stats for liquor store"""
    today_orders = Order.objects.filter(
        created_at__date=date,
        items__food_item__store_type='liquor'
    ).distinct()

    today_revenue = OrderItem.objects.filter(
        order__created_at__date=date,
        food_item__store_type='liquor',
        order__status__in=['delivered', 'completed']
    ).aggregate(
        total=Sum(
            ExpressionWrapper(
                F('price_at_order') * F('quantity'),
                output_field=DecimalField()
            )
        )
    )['total'] or 0

    pending_orders = Order.objects.filter(
        status='pending',
        items__food_item__store_type='liquor'
    ).distinct().count()

    out_for_delivery = Order.objects.filter(
        status='out_for_delivery',
        items__food_item__store_type='liquor'
    ).distinct().count()

    weekly_orders = Order.objects.filter(
        created_at__date__gte=week_start,
        items__food_item__store_type='liquor'
    ).distinct()

    weekly_revenue = OrderItem.objects.filter(
        order__created_at__date__gte=week_start,
        food_item__store_type='liquor',
        order__status__in=['delivered', 'completed']
    ).aggregate(
        total=Sum(
            ExpressionWrapper(
                F('price_at_order') * F('quantity'),
                output_field=DecimalField()
            )
        )
    )['total'] or 0

    weekly_order_count = weekly_orders.count()
    average_order_value = weekly_revenue / weekly_order_count if weekly_order_count else 0

    return {
        'today_orders_count': today_orders.count(),
        'today_revenue': today_revenue,
        'pending_orders': pending_orders,
        'out_for_delivery': out_for_delivery,
        'weekly_order_count': weekly_order_count,
        'weekly_revenue': weekly_revenue,
        'average_order_value': average_order_value,
    }

def get_popular_liquor_items(date):
    return OrderItem.objects.filter(
        order__created_at__date=date,
        order__status__in=VALID_STATUSES,
        order__store_type='liquor'
    ).values('food_item__name').annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('price_at_order')
    ).order_by('-total_quantity')[:5]

def get_peak_hours(days=7):
    from django.db.models.functions import ExtractHour
    from django.utils import timezone
    start = timezone.now() - timezone.timedelta(days=days)
    return Order.objects.filter(
        created_at__gte=start,
        status__in=VALID_STATUSES,
        store_type='liquor'
    ).annotate(hour=ExtractHour('created_at')).values('hour').annotate(
        order_count=Count('id')
    ).order_by('-order_count')[:5]


@staff_member_required(login_url='admin_login')
def admin_dashboard(request):
    """Main admin dashboard with overview"""
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())

    stats = get_liquor_stats(date=today, week_start=week_start)
    popular_today = get_popular_liquor_items(date=today)
    peak_hours = get_peak_hours(days=7)

    # Weekly revenue trend (daily)
    weekly_items = OrderItem.objects.filter(
        order__created_at__date__gte=week_start,
        order__status__in=['delivered', 'completed'],
        order__store_type='liquor'
    ).annotate(day=TruncDate('order__created_at')).values('day').annotate(
        daily_revenue=Sum('price_at_order'),
        order_count=Count('order', distinct=True)
    ).order_by('day')

    context = {
        'today_orders_count': stats['today_orders_count'],
        'today_revenue': stats['today_revenue'],
        'weekly_revenue': stats['weekly_revenue'],
        'weekly_order_count': stats['weekly_order_count'],
        'average_order_value': stats['average_order_value'],
        'popular_today': popular_today,
        'peak_hours': peak_hours,
        'revenue_trend': list(weekly_items),
    }

    # If AJAX request, return JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(context)

    return render(request, 'custom_admin/liqour_dashboard.html', context)

@staff_member_required(login_url='admin_login')
def admin_dashboard_stats(request):
    """AJAX endpoint for liquor dashboard stats"""
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())

    # Today's orders
    today_orders = Order.objects.filter(created_at__date=today, store_type='liquor')

    # Revenue including delivery fee (only delivered/completed)
    today_items_revenue = OrderItem.objects.filter(
        order__in=today_orders,
        food_item__store_type='liquor',
        order__status__in=VALID_STATUSES
    ).aggregate(revenue=Sum('price_at_order'))['revenue'] or 0

    today_delivery_fee = today_orders.filter(
        status__in=VALID_STATUSES
    ).aggregate(fee=Sum('delivery_fee'))['fee'] or 0

    today_revenue = float(today_items_revenue + today_delivery_fee)

    # Pending and out-for-delivery orders
    pending_orders = Order.objects.filter(status='pending', store_type='liquor').count()
    out_for_delivery = Order.objects.filter(status='out_for_delivery', store_type='liquor').count()

    # Weekly revenue trend
    weekly_orders = Order.objects.filter(
        created_at__date__gte=week_start,
        store_type='liquor'
    )

    weekly_items = OrderItem.objects.filter(
        order__in=weekly_orders,
        food_item__store_type='liquor',
        order__status__in=VALID_STATUSES
    ).annotate(day=TruncDate('order__created_at')).values('day').annotate(
        revenue=Sum('price_at_order'),
        orders=Count('order', distinct=True)
    ).order_by('day')

    # Add delivery fee per day (only delivered/completed)
    daily_delivery_fees = {}
    for o in weekly_orders.filter(status__in=VALID_STATUSES):
        day = o.created_at.date()
        daily_delivery_fees[day] = daily_delivery_fees.get(day, 0) + float(o.delivery_fee)

    revenue_trend = [
        {
            'day': item['day'].strftime('%Y-%m-%d'),
            'revenue': float(item['revenue'] or 0) + daily_delivery_fees.get(item['day'], 0),
            'orders': item['orders']
        }
        for item in weekly_items
    ]

    return JsonResponse({
        'success': True,
        'today_orders_count': today_orders.count(),
        'today_revenue': today_revenue,
        'pending_orders': pending_orders,
        'out_for_delivery': out_for_delivery,
        'revenue_trend': revenue_trend
    })


# ==================== ORDER MANAGEMENT ====================

@staff_member_required(login_url='admin_login')
def admin_orders(request):
    """Order management page"""
    status_filter = request.GET.get('status', 'all')
    payment_method_filter = request.GET.get('payment_method', 'all')
    payment_status_filter = request.GET.get('payment_status', 'all')

    orders = Order.objects.all().select_related('user').prefetch_related('items')

    if status_filter != 'all':
        orders = orders.filter(status=status_filter)

    if payment_method_filter != 'all':
        orders = orders.filter(payment_method=payment_method_filter)

    if payment_status_filter != 'all':
        orders = orders.filter(payment_status=payment_status_filter)

    # Recent orders first
    orders = orders.order_by('-created_at')

    context = {
        'orders': orders[:50],  # Limit to recent 50
        'status_filter': status_filter,
        'payment_method_filter': payment_method_filter,
        'payment_status_filter': payment_status_filter,
    }

    return render(request, 'custom_admin/liquor_orders.html', context)

@staff_member_required(login_url='admin_login')
def get_new_orders(request):
    """API endpoint to check for new orders (for auto-refresh)"""
    last_check = request.GET.get('last_check')

    if last_check:
        last_check_time = parse_datetime(last_check)
        if last_check_time is not None and timezone.is_naive(last_check_time):
            last_check_time = timezone.make_aware(last_check_time, timezone.get_current_timezone())

        new_orders = Order.objects.filter(
            created_at__gt=last_check_time,
            status='pending'
        ) if last_check_time else Order.objects.filter(status='pending')
    else:
        new_orders = Order.objects.filter(status='pending')

    orders_data = []
    for order in new_orders:
        orders_data.append({
            'order_number': order.order_number,
            'user': order.user.username,
            'total': float(order.total),
            'hostel': order.hostel,
            'room': order.room_number,
            'phone': order.phone_number,
            'created_at': order.created_at.isoformat(),
        })

        # Send push for each new order
        send_push_to_all(
            title="New Order Received 🍔",
            body=f"Order #{order.order_number} by {order.user.username} for KES {order.total}",
            url=f"/admin-panel/liquor/orders/{order.id}/"  # optional admin link
        )

    return JsonResponse({
        'success': True,
        'new_orders_count': len(orders_data),
        'orders': orders_data,
        'timestamp': timezone.now().isoformat()
    })

@staff_member_required(login_url='admin_login')
def admin_order_detail(request, order_number):
    """View detailed order information"""
    order = get_object_or_404(Order.objects.select_related('user', 'delivery_guy'), order_number=order_number)
    status_history = order.status_history.all()
    active_delivery_guys = DeliveryGuy.objects.filter(is_active=True).order_by('name')

    context = {
        'order': order,
        'status_history': status_history,
        'active_delivery_guys': active_delivery_guys,
    }


    return render(request, 'custom_admin/order_detail.html', context)

from django.db import transaction
from django.views.decorators.http import require_http_methods
from .utils import notify_low_stock

@staff_member_required(login_url='admin_login')
@require_http_methods(["POST"])
def update_order_status(request):
    """Update order status and handle stock reduction"""
    data = json.loads(request.body)
    order_number = data.get('order_number')
    new_status = data.get('status')
    notes = data.get('notes', '')
    delivery_guy_id = data.get('delivery_guy_id')

    order = get_object_or_404(Order, order_number=order_number)

    old_status = order.status
    order.status = new_status

    # Assign or clear delivery guy if provided
    if delivery_guy_id is not None:
        if delivery_guy_id:
            try:
                delivery_guy = DeliveryGuy.objects.get(id=int(delivery_guy_id), is_active=True)
                order.delivery_guy = delivery_guy
            except (DeliveryGuy.DoesNotExist, ValueError):
                return JsonResponse({
                    'success': False,
                    'message': 'Selected delivery guy not found or inactive'
                }, status=400)
        else:
            order.delivery_guy = None


    # ✅ When order is delivered → reduce PRODUCT stock
    if new_status == 'delivered' and old_status != 'delivered':
        order.delivered_at = timezone.now()

        with transaction.atomic():
            for item in order.items.select_related('food_item'):
                product = item.food_item

                # Only track liquor stock
                if product.store_type != 'liquor':
                    continue

                old_stock = product.stock
                new_stock = old_stock - item.quantity

                # Prevent negative stock
                if new_stock < 0:
                    new_stock = 0

                product.stock = new_stock

                # Auto hide if out of stock
                if new_stock == 0:
                    product.is_available = False

                product.save()

                # 🚨 LOW STOCK ALERT (only when crossing threshold)
                if (
                    old_stock > product.low_stock_threshold and
                    new_stock <= product.low_stock_threshold
                ):
                    notify_low_stock(product)

    order.save()

    # 📝 Status history
    OrderStatusHistory.objects.create(
        order=order,
        status=new_status,
        notes=notes or f'Status changed from {old_status} to {new_status}'
    )

    return JsonResponse({
        'success': True,
        'message': f'Order {order_number} status updated to {new_status}',
        'new_status': new_status,
        'status_display': order.get_status_display(),
        'delivery_guy_name': order.delivery_guy.name if order.delivery_guy else None,
    })



@staff_member_required(login_url='admin_login')
@require_http_methods(["POST"])
def restock_product(request):
    data = json.loads(request.body)
    product_id = data.get("product_id")
    amount = int(data.get("amount", 0))

    product = get_object_or_404(FoodItem, id=product_id)

    if not product_id:
        return JsonResponse({"Success": False, "message": "Product ID is required"})

    if amount <= 0:
        return JsonResponse({"success": False, "message": "Invalid restock amount"})

    product.stock += amount
    product.is_available = True
    product.save()

    return JsonResponse({
        "success": True,
        "new_stock": product.stock,
        "message": f"{product.name} restocked successfully"
    })


@staff_member_required(login_url='admin_login')
def cancel_order(request):
    """Cancel an order"""
    if request.method == 'POST':
        data = json.loads(request.body)
        order_number = data.get('order_number')
        reason = data.get('reason', 'Cancelled by admin')

        order = get_object_or_404(Order, order_number=order_number)
        order.status = 'cancelled'
        order.cancellation_reason = reason
        order.save()

        # Create status history entry
        OrderStatusHistory.objects.create(
            order=order,
            status='cancelled',
            notes=reason
        )

        return JsonResponse({
            'success': True,
            'message': f'Order {order_number} cancelled'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
def get_payment_details(request, order_number):
    """Get payment details for an order"""
    order = get_object_or_404(Order, order_number=order_number)

    if order.payment_method != 'mpesa':
        return JsonResponse({'success': False, 'message': 'Payment details only available for M-PESA payments'})

    payment_details = {
        'mpesa_receipt_number': order.mpesa_receipt_number,
        'transaction_date': order.created_at.isoformat() if order.created_at else None,
        'phone_number': order.phone_number,
        'checkout_request_id': order.mpesa_checkout_request_id,
        'payment_completed_at': order.payment_completed_at.isoformat() if order.payment_completed_at else None,
    }

    return JsonResponse({
        'success': True,
        'payment_details': payment_details
    })

# ==================== LIQUOR ADMIN VIEWS ====================

@staff_member_required(login_url='admin_login')
def liquor_dashboard(request):
    """Liquor store admin dashboard"""
    today = timezone.now().date()

    # Delivered/completed liquor orders for revenue calculation
    delivered_orders = Order.objects.filter(
        created_at__date=today,
        status__in=['delivered', 'completed'],
        items__food_item__store_type='liquor'
    ).distinct()

    # Today's revenue (items + delivery fees)
    today_items_revenue = OrderItem.objects.filter(
        order__in=delivered_orders,
        food_item__store_type='liquor'
    ).aggregate(revenue=Sum('price_at_order'))['revenue'] or 0
    today_delivery_fee = delivered_orders.aggregate(fee=Sum('delivery_fee'))['fee'] or 0
    today_revenue = float(today_items_revenue + today_delivery_fee)

    # Pending and out-for-delivery orders (all liquor orders, not yet delivered)
    pending_orders = Order.objects.filter(
        status='pending',
        items__food_item__store_type='liquor'
    ).distinct().count()
    preparing_orders = Order.objects.filter(
        status='preparing',
        items__food_item__store_type='liquor'
    ).distinct().count()
    out_for_delivery = Order.objects.filter(
        status='out_for_delivery',
        items__food_item__store_type='liquor'
    ).distinct().count()

    # Popular liquor items today (delivered only)
    popular_today = OrderItem.objects.filter(
        order__created_at__date=today,
        order__status__in=['delivered', 'completed'],
        food_item__store_type='liquor'
    ).values(
        'food_item__name'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('price_at_order')
    ).order_by('-total_quantity')[:5]

    # Weekly delivered/completed orders
    week_start = today - timedelta(days=today.weekday())
    weekly_orders = Order.objects.filter(
        created_at__date__gte=week_start,
        status__in=['delivered', 'completed'],
        items__food_item__store_type='liquor'
    ).distinct()

    weekly_items_revenue = OrderItem.objects.filter(
        order__in=weekly_orders,
        food_item__store_type='liquor'
    ).aggregate(total=Sum('price_at_order'))['total'] or 0
    weekly_delivery_fee = weekly_orders.aggregate(total=Sum('delivery_fee'))['total'] or 0
    weekly_revenue = float(weekly_items_revenue + weekly_delivery_fee)
    weekly_order_count = weekly_orders.count()
    average_order_value = weekly_revenue / weekly_order_count if weekly_order_count > 0 else 0

    # Revenue trend (daily) including delivery fee
    revenue_trend = weekly_orders.annotate(day=TruncDate('created_at')).values('day').annotate(
        items_revenue=Sum('items__price_at_order'),
        delivery_fee=Sum('delivery_fee'),
        daily_revenue=F('items_revenue') + F('delivery_fee'),
        order_count=Count('id')
    ).order_by('day')

    # Peak hours (last 7 days, delivered/completed only)
    peak_hours = Order.objects.filter(
        created_at__gte=timezone.now() - timedelta(days=7),
        status__in=['delivered', 'completed'],
        items__food_item__store_type='liquor'
    ).distinct().annotate(hour=ExtractHour('created_at')).values('hour').annotate(
        order_count=Count('id')
    ).order_by('-order_count')[:5]

    context = {
        'today_orders_count': delivered_orders.count(),
        'today_revenue': today_revenue,
        'pending_orders': pending_orders,
        'preparing_orders': preparing_orders,
        'out_for_delivery': out_for_delivery,
        'popular_today': popular_today,
        'weekly_orders': weekly_order_count,
        'weekly_revenue': weekly_revenue,
        'average_order_value': average_order_value,
        'peak_hours': peak_hours,
        'revenue_trend': list(revenue_trend),
        'store_type': 'liquor',
    }

    return render(request, 'custom_admin/liquor_dashboard.html', context)


@staff_member_required(login_url='admin_login')
def liquor_orders(request):
    """Liquor order management page"""
    status_filter = request.GET.get('status', 'all')
    status_choices = Order.STATUS_CHOICES
    valid_statuses = {value for value, _ in status_choices}
    if status_filter != 'all' and status_filter not in valid_statuses:
        status_filter = 'all'

    orders = Order.objects.filter(store_type='liquor').select_related('user').prefetch_related('items')

    if status_filter != 'all':
        orders = orders.filter(status=status_filter)

    # Recent orders first
    orders = orders.order_by('-created_at')

    context = {
        'orders': orders[:50],  # Limit to recent 50
        'status_filter': status_filter,
        'status_choices': status_choices,
        'store_type': 'liquor',
    }

    return render(request, 'custom_admin/liquor_orders.html', context)

@staff_member_required
def liquor_order_detail(request, order_number):
    return redirect('admin_order_detail', order_number=order_number)

@staff_member_required(login_url='admin_login')
def liquor_analytics(request):
    """Liquor analytics and reports"""
    # Date range - support both preset and custom dates
    days = request.GET.get('days', '7')
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')
    
    # Handle custom date range
    if from_date_str and to_date_str:
        try:
            from_date_obj = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            to_date_obj = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            start_date = timezone.make_aware(datetime.combine(from_date_obj, datetime.min.time()))
            end_date = timezone.make_aware(datetime.combine(to_date_obj, datetime.max.time()))
            days = 'custom'
        except (ValueError, TypeError):
            # Fall back to preset days
            days = int(days)
            start_date = timezone.now() - timedelta(days=days)
            end_date = timezone.now()
    else:
        try:
            days = int(days)
        except (ValueError, TypeError):
            days = 7
        start_date = timezone.now() - timedelta(days=days)
        end_date = timezone.now()

    # Delivered/completed liquor orders in the period
    delivered_orders = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        status__in=['delivered', 'completed'],
        items__food_item__store_type='liquor'
    ).distinct()

    # Daily revenue (items + delivery fees)
    daily_revenue = delivered_orders.annotate(day=TruncDate('created_at')).values('day').annotate(
        items_revenue=Sum('items__price_at_order'),
        delivery_fee=Sum('delivery_fee'),
        revenue=F('items_revenue') + F('delivery_fee'),
        orders=Count('id')
    ).order_by('day')

    # Top selling liquor items
    top_items = OrderItem.objects.filter(
        order__created_at__gte=start_date,
        food_item__store_type='liquor'
    ).values(
        'food_item__name',
        'food_item__category__name',
        'food_item__bottle_size'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('price_at_order')
    ).order_by('-total_quantity')[:10]

    # Top liquor customers
    top_customers = delivered_orders.values(
        'user__username',
        'user__phone_number'
    ).annotate(
        total_orders=Count('id'),
        total_spent=Sum('total')
    ).order_by('-total_orders')[:10]

    # Liquor order status distribution (all statuses)
    status_distribution = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        items__food_item__store_type='liquor'
    ).values('status').annotate(
        count=Count('id')
    ).order_by('status')

    # Totals
    total_revenue = sum(float(item['revenue'] or 0) for item in daily_revenue)
    total_orders = sum(item['orders'] for item in daily_revenue)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0

    # Peak hours (last X days, delivered/completed)
    peak_hours = delivered_orders.annotate(hour=ExtractHour('created_at')).values('hour').annotate(
        order_count=Count('id')
    ).order_by('-order_count')[:10]

    # Liquor metrics
    liquor_orders = delivered_orders
    liquor_revenue = total_revenue
    liquor_items_sold = OrderItem.objects.filter(
        order__in=delivered_orders,
        food_item__store_type='liquor'
    ).aggregate(total=Sum('quantity'))['total'] or 0
    top_liquor_items = top_items
    liquor_daily_revenue = daily_revenue
    
    # Format dates for display
    from_date_display = start_date.date().isoformat() if hasattr(start_date, 'date') else str(start_date)
    to_date_display = end_date.date().isoformat() if hasattr(end_date, 'date') else str(end_date)

    context = {
        'daily_revenue': json.dumps(list(daily_revenue), default=str),
        'top_items': json.dumps(list(top_items), default=str),
        'top_customers': json.dumps(list(top_customers), default=str),
        'status_distribution': json.dumps(list(status_distribution), default=str),
        'days': days,
        'from_date': from_date_display,
        'to_date': to_date_display,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'avg_order_value': avg_order_value,
        'peak_hours': json.dumps(list(peak_hours), default=str),
        # Liquor metrics
        'liquor_revenue': liquor_revenue,
        'liquor_orders_count': liquor_orders.count(),
        'liquor_items_sold': liquor_items_sold,
        'top_liquor_items': json.dumps(list(top_liquor_items), default=str),
        'liquor_daily_revenue': json.dumps(list(liquor_daily_revenue), default=str),
        'store_type': 'liquor',
    }

    return render(request, 'custom_admin/liquor_analytics.html', context)

# ==================== FOOD MENU MANAGEMENT ====================

@staff_member_required(login_url='admin_login')
def admin_menu(request):
    """Food menu management"""
    categories = FoodCategory.objects.filter(store_type='food')
    food_items = FoodItem.objects.filter(store_type='food').select_related('category')

    context = {
        'categories': categories,
        'food_items': food_items,
        'store_type': 'food',
    }

    return render(request, 'custom_admin/menu.html', context)

@staff_member_required(login_url='admin_login')
def admin_liquor(request):
    """Liquor store management"""
    categories = FoodCategory.objects.filter(store_type='liquor')
    food_items = FoodItem.objects.filter(store_type='liquor').select_related('category')

    context = {
        'categories': categories,
        'food_items': food_items,
        'store_type': 'liquor',
    }

    return render(request, 'custom_admin/liquor.html', context)

@staff_member_required(login_url='admin_login')
def admin_grocery(request):
    """Grocery store management"""
    categories = FoodCategory.objects.filter(store_type='grocery')
    food_items = FoodItem.objects.filter(store_type='grocery').select_related('category')

    context = {
        'categories': categories,
        'food_items': food_items,
        'store_type': 'grocery',
    }

    return render(request, 'custom_admin/grocery.html', context)

@staff_member_required(login_url='admin_login')
def toggle_food_availability(request):
    """Toggle food item availability"""
    if request.method == 'POST':
        data = json.loads(request.body)
        food_item_id = data.get('food_item_id')

        food_item = get_object_or_404(FoodItem, id=food_item_id)
        food_item.is_available = not food_item.is_available
        food_item.save()

        return JsonResponse({
            'success': True,
            'is_available': food_item.is_available,
            'message': f'{food_item.name} is now {"available" if food_item.is_available else "unavailable"}'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
def update_food_price(request):
    """Update food item price"""
    if request.method == 'POST':
        data = json.loads(request.body)
        food_item_id = data.get('food_item_id')
        new_price = data.get('price')

        food_item = get_object_or_404(FoodItem, id=food_item_id)
        food_item.price = new_price
        food_item.save()

        return JsonResponse({
            'success': True,
            'message': f'{food_item.name} price updated to KES {new_price}'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
def add_category(request):
    """Add a new food category"""
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        description = data.get('description', '')
        order = data.get('order', 0)
        #stock_quantity = data.get('stock_quantity', 0)

        if not name:
            return JsonResponse({'success': False, 'message': 'Category name is required'})

        store_type = data.get('store_type', 'food')
        category = FoodCategory.objects.create(
            name=name,
            description=description,
            order=order,
            #stock_quantity=stock_quantity,
            store_type=store_type
        )

        return JsonResponse({
            'success': True,
            'message': f'Category "{name}" added successfully',
            'category_id': category.id
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
def edit_category(request):
    """Edit an existing food category"""
    if request.method == 'POST':
        data = json.loads(request.body)
        category_id = data.get('id')
        name = data.get('name')
        description = data.get('description', '')
        order = data.get('order', 0)

        if not category_id or not name:
            return JsonResponse({'success': False, 'message': 'Category ID and name are required'})

        category = get_object_or_404(FoodCategory, id=category_id)
        category.name = name
        category.description = description
        category.order = order
        # Note: Stock is tracked on Products (FoodItem), not Categories
        category.save()

        return JsonResponse({
            'success': True,
            'message': f'Category "{name}" updated successfully'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
@require_POST
def delete_category(request):
    try:
        data = json.loads(request.body)
        category_id = data.get('id')

        if not category_id:
            return JsonResponse({'success': False, 'message': 'Category ID is required'}, status=400)

        try:
            category = FoodCategory.objects.get(id=category_id)
        except FoodCategory.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Category not found'}, status=404)

        if category.items.exists():
            return JsonResponse({
                'success': False,
                'message': 'Cannot delete category with existing food items. Please move or delete the items first.'
            }, status=400)

        category_name = category.name
        category.delete()

        return JsonResponse({
            'success': True,
            'message': f'Category "{category_name}" deleted successfully'
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@staff_member_required(login_url='admin_login')
def get_food_item_api(request, item_id):
    item = get_object_or_404(FoodItem, id=item_id)
    return JsonResponse({
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "category": item.category.id,
        "price": str(item.price),
        "prep_time": item.prep_time,
        "stock": item.stock,
        "bottle_size": item.bottle_size
    })


@staff_member_required(login_url='admin_login')
def add_food_item(request):
    """Add a new food item"""
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        category_id = request.POST.get('category')
        price = request.POST.get('price')
        prep_time = request.POST.get('prep_time')
        image = request.FILES.get('image')

        if not all([name, description, category_id, price, prep_time]):
            return JsonResponse({'success': False, 'message': 'All fields are required'})

        try:
            category = FoodCategory.objects.get(id=category_id)
        except FoodCategory.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Invalid category'})

        bottle_size = request.POST.get('bottle_size', '')
        store_type = request.POST.get('store_type', 'food')
        stock = request.POST.get('stock', 0)
        
        food_item = FoodItem.objects.create(
            name=name,
            description=description,
            category=category,
            price=price,
            prep_time=prep_time,
            image=image,
            bottle_size=bottle_size,
            store_type=store_type,
            stock=stock
        )

        return JsonResponse({
            'success': True,
            'message': f'Food item "{name}" added successfully',
            'item_id': food_item.id
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
@require_http_methods(["POST"])
def edit_food_item(request):
    """Edit an existing food item"""
    item_id = request.POST.get('id')
    name = request.POST.get('name')
    description = request.POST.get('description')
    category_id = request.POST.get('category')
    price = request.POST.get('price')
    prep_time = request.POST.get('prep_time')
    image = request.FILES.get('image')
    stock = request.POST.get('stock')  # ✅ NEW

    if not item_id or not all([name, description, category_id, price, prep_time]):
        return JsonResponse({'success': False, 'message': 'All fields are required'})

    try:
        food_item = FoodItem.objects.get(id=item_id)
        category = FoodCategory.objects.get(id=category_id)
    except (FoodItem.DoesNotExist, FoodCategory.DoesNotExist):
        return JsonResponse({'success': False, 'message': 'Invalid food item or category'})

    food_item.name = name
    food_item.description = description
    food_item.category = category
    food_item.price = price
    food_item.prep_time = prep_time

    bottle_size = request.POST.get('bottle_size', '')
    if bottle_size:
        food_item.bottle_size = bottle_size

    if image:
        food_item.image = image

    # ✅ Fix: Update stock properly
    if stock is not None and stock != "":
        try:
            stock = int(stock)
            food_item.stock = max(0, stock)
            food_item.is_available = stock > 0
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid stock value'})

    food_item.save()

    return JsonResponse({
        'success': True,
        'message': f'Food item "{name}" updated successfully',
        'new_stock': food_item.stock
    })

@staff_member_required(login_url='admin_login')
@require_POST
def delete_food_item(request):
    try:
        data = json.loads(request.body)
        item_id = data.get('id')

        if not item_id:
            return JsonResponse({'success': False, 'message': 'Food item ID is required'}, status=400)

        try:
            food_item = FoodItem.objects.get(id=item_id)
        except FoodItem.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Food item not found'}, status=404)

        item_name = food_item.name
        food_item.delete()

        return JsonResponse({
            'success': True,
            'message': f'Food item "{item_name}" deleted successfully'
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# ==================== ANALYTICS ====================

@staff_member_required(login_url='admin_login')
def admin_analytics(request):
    """Analytics and reports"""
    # Date range - support both preset and custom dates
    days = request.GET.get('days', '7')
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')
    
    # Handle custom date range
    if from_date_str and to_date_str:
        try:
            from_date_obj = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            to_date_obj = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            start_date = timezone.make_aware(datetime.combine(from_date_obj, datetime.min.time()))
            end_date = timezone.make_aware(datetime.combine(to_date_obj, datetime.max.time()))
            days = 'custom'
        except (ValueError, TypeError):
            # Fall back to preset days
            days = int(days)
            start_date = timezone.now() - timedelta(days=days)
            end_date = timezone.now()
    else:
        try:
            days = int(days)
        except (ValueError, TypeError):
            days = 7
        start_date = timezone.now() - timedelta(days=days)
        end_date = timezone.now()

    # Revenue over time
    daily_revenue = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        status='delivered'
    ).extra(
        select={'day': 'DATE(created_at)'}
    ).values('day').annotate(
        revenue=Sum('total'),
        orders=Count('id')
    ).order_by('day')

    # Top selling items (food and grocery only)
    top_items = OrderItem.objects.filter(
        order__created_at__gte=start_date,
        order__created_at__lte=end_date,
        food_item__store_type__in=['food', 'grocery']
    ).values(
        'food_item__name',
        'food_item__category__name'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('price_at_order')
    ).order_by('-total_quantity')[:10]

    # Top customers
    top_customers = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        status='delivered'
    ).values(
        'user__username',
        'user__phone_number'
    ).annotate(
        total_orders=Count('id'),
        total_spent=Sum('total')
    ).order_by('-total_orders')[:10]

    # Order status distribution
    status_distribution = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date
    ).values('status').annotate(
        count=Count('id')
    )

    # Calculate totals
    total_revenue = sum(item['revenue'] for item in daily_revenue)
    total_orders = sum(item['orders'] for item in daily_revenue)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0

    # Peak hours
    peak_hours = (Order.objects.filter(created_at__gte=start_date, created_at__lte=end_date).annotate(hour=ExtractHour('created_at')).values('hour').annotate(order_count=Count('id')).order_by('-order_count')[:10])

    # M-PESA Payment Analytics
    mpesa_orders = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        payment_method='mpesa'
    )

    # M-PESA revenue and success rate
    mpesa_revenue = mpesa_orders.filter(payment_status='paid').aggregate(total=Sum('total'))['total'] or 0
    mpesa_success_rate = (mpesa_orders.filter(payment_status='paid').count() / mpesa_orders.count() * 100) if mpesa_orders.count() > 0 else 0
    mpesa_avg_transaction = mpesa_revenue / mpesa_orders.filter(payment_status='paid').count() if mpesa_orders.filter(payment_status='paid').count() > 0 else 0

    # M-PESA payment timeline
    mpesa_payment_timeline = mpesa_orders.filter(payment_status='paid').annotate(day=TruncDate('payment_completed_at')).values('day').annotate(
        successful_payments=Count('id'),
        revenue=Sum('total')
    ).order_by('day')

    # Failed payment reasons
    failed_payments = mpesa_orders.filter(payment_status='failed').values('payment_failure_reason').annotate(
        count=Count('id')
    ).order_by('-count')[:5]

    # Peak payment hours
    peak_payment_hours = mpesa_orders.filter(payment_status='paid').annotate(hour=ExtractHour('payment_completed_at')).values('hour').annotate(
        payment_count=Count('id')
    ).order_by('-payment_count')[:10]

    # Liquor-specific metrics
    liquor_orders = Order.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        items__food_item__store_type='liquor'
    ).distinct()

    liquor_revenue = OrderItem.objects.filter(
        order__created_at__gte=start_date,
        order__created_at__lte=end_date,
        food_item__store_type='liquor'
    ).aggregate(total=Sum('price_at_order'))['total'] or 0

    liquor_items_sold = OrderItem.objects.filter(
        order__created_at__gte=start_date,
        order__created_at__lte=end_date,
        food_item__store_type='liquor'
    ).aggregate(total=Sum('quantity'))['total'] or 0

    # Top selling liquor items
    top_liquor_items = OrderItem.objects.filter(
        order__created_at__gte=start_date,
        order__created_at__lte=end_date,
        food_item__store_type='liquor'
    ).values(
        'food_item__name',
        'food_item__category__name',
        'food_item__bottle_size'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('price_at_order')
    ).order_by('-total_quantity')[:10]

    # Liquor revenue trend
    liquor_daily_revenue = (
    OrderItem.objects.filter(
        order__created_at__gte=start_date,
        order__created_at__lte=end_date,
        food_item__store_type='liquor'
    )
    .annotate(day=TruncDate('order__created_at'))
    .values('day')
    .annotate(
        revenue=Sum('price_at_order'),
        orders=Count('order', distinct=True)
    )
    .order_by('day')
    )

    # Format dates for display
    from_date_display = start_date.date().isoformat() if hasattr(start_date, 'date') else str(start_date)
    to_date_display = end_date.date().isoformat() if hasattr(end_date, 'date') else str(end_date)

    context = {
        'daily_revenue': json.dumps(list(daily_revenue), default=str),
        'top_items': json.dumps(list(top_items), default=str),
        'top_customers': json.dumps(list(top_customers), default=str),
        'status_distribution': json.dumps(list(status_distribution), default=str),
        'days': days,
        'from_date': from_date_display,
        'to_date': to_date_display,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'avg_order_value': avg_order_value,
        'peak_hours': json.dumps(list(peak_hours), default=str),
        # M-PESA Payment metrics
        'mpesa_revenue': mpesa_revenue,
        'mpesa_success_rate': mpesa_success_rate,
        'mpesa_avg_transaction': mpesa_avg_transaction,
        'mpesa_payment_timeline': json.dumps(list(mpesa_payment_timeline), default=str),
        'failed_payments': json.dumps(list(failed_payments), default=str),
        'peak_payment_hours': json.dumps(list(peak_payment_hours), default=str),
        # Liquor metrics
        'liquor_revenue': liquor_revenue,
        'liquor_orders_count': liquor_orders.count(),
        'liquor_items_sold': liquor_items_sold,
        'top_liquor_items': json.dumps(list(top_liquor_items), default=str),
        'liquor_daily_revenue': json.dumps(list(liquor_daily_revenue), default=str),
    }

    return render(request, 'custom_admin/analytics.html', context)

# ==================== CUSTOMER MANAGEMENT ====================

@staff_member_required(login_url='admin_login')
def admin_customers(request):
    """Customer management"""
    customers = User.objects.filter(role='customer').annotate(
        total_orders=Count('orders'),
        total_spent=Sum('orders__total')
    ).order_by('-total_orders')

    total_customers = customers.count()
    avg_orders_per_customer = customers.aggregate(avg_orders=Avg('total_orders'))['avg_orders'] or 0

    context = {
        'customers': customers,
        'total_customers': total_customers,
        'active_customers': customers.filter(total_orders__gt=0).count(),
        'new_customers': customers.filter(date_joined__gte=timezone.now()-timedelta(days=30)).count(),
        'avg_orders_per_customer': avg_orders_per_customer,
    }

    return render(request, 'custom_admin/customers.html', context)

@staff_member_required(login_url='admin_login')
def admin_customer_detail(request, customer_id):
    customer = get_object_or_404(User, id=customer_id)
    # Fetch orders for the customer
    orders = Order.objects.filter(user=customer).order_by('-created_at')

    context = {
        'customer': customer,
        'orders': orders,
    }
    return render(request, 'custom_admin/customer_detail.html', context)

@staff_member_required(login_url='admin_login')
def get_customer_orders(request, customer_id):
    """API endpoint to get customer orders"""
    customer = get_object_or_404(User, id=customer_id)
    orders = Order.objects.filter(user=customer).order_by('-created_at')[:10]  # Limit to recent 10

    orders_data = []
    for order in orders:
        orders_data.append({
            'order_number': order.order_number,
            'created_at': order.created_at.isoformat(),
            'total': float(order.total),
            'status': order.status,
            'status_display': order.get_status_display(),
            'items': [
                {
                    'quantity': item.quantity,
                    'food_item': {
                        'name': item.food_item.name
                    }
                } for item in order.items.all()
            ]
        })

    return JsonResponse({
        'success': True,
        'orders': orders_data
    })

@staff_member_required(login_url='admin_login')
def send_customer_message(request):
    """Send message to customer"""
    if request.method == 'POST':
        data = json.loads(request.body)
        customer_id = data.get('customer_id')
        subject = data.get('subject')
        content = data.get('content')

        customer = get_object_or_404(User, id=customer_id)

        # Here you would implement actual message sending logic
        # For now, we'll just return success
        # You could integrate with email service, SMS, or in-app notifications

        return JsonResponse({
            'success': True,
            'message': f'Message sent to {customer.username}'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
def update_customer_status(request):
    """Update customer active status"""
    if request.method == 'POST':
        data = json.loads(request.body)
        customer_id = data.get('customer_id')
        is_active = data.get('is_active')

        customer = get_object_or_404(User, id=customer_id)
        customer.is_active = is_active
        customer.save()

        return JsonResponse({
            'success': True,
            'message': f'Customer {customer.username} {"activated" if is_active else "deactivated"} successfully'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
def admin_profile(request):
    """Admin profile page"""
    return render(request, 'custom_admin/profile.html')

@staff_member_required(login_url='admin_login')
def update_admin_profile(request):
    """Update admin profile information"""
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()

        if not username or not email:
            return JsonResponse({
                'success': False,
                'message': 'Username and email are required'
            })

        # Check if username is already taken by another user
        user = request.user
        if User.objects.filter(username=username).exclude(id=user.id).exists():
            return JsonResponse({
                'success': False,
                'message': 'Username already taken'
            })

        # Update the admin user
        user.username = username
        user.email = email
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        user.save()

        return JsonResponse({
            'success': True,
            'message': 'Profile updated successfully'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@staff_member_required(login_url='admin_login')
def update_admin_password(request):
    """Update admin password"""
    if request.method == 'POST':
        data = json.loads(request.body)
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if not old_password or not new_password or not confirm_password:
            return JsonResponse({
                'success': False,
                'message': 'All password fields are required'
            })

        if new_password != confirm_password:
            return JsonResponse({
                'success': False,
                'message': 'New passwords do not match'
            })

        if len(new_password) < 8:
            return JsonResponse({
                'success': False,
                'message': 'Password must be at least 8 characters long'
            })

        # Verify old password
        user = request.user
        if not user.check_password(old_password):
            return JsonResponse({
                'success': False,
                'message': 'Current password is incorrect'
            })

        # Set new password
        user.set_password(new_password)
        user.save()

        return JsonResponse({
            'success': True,
            'message': 'Password updated successfully'
        })

    return JsonResponse({'success': False, 'message': 'Invalid request'})


# ==================== DELIVERY GUYS MANAGEMENT ====================

@staff_member_required(login_url='admin_login')
def delivery_guys_list(request):
    """List all delivery guys"""
    # Don't use annotate since total_deliveries and delivered_orders are @property methods
    delivery_guys = DeliveryGuy.objects.all().order_by('name')
    
    # Prepare delivery guy data with this week's deliveries
    delivery_guys_data = []
    for guy in delivery_guys:
        this_week_deliveries = guy.get_this_week_deliveries()
        this_week_revenue = guy.get_this_week_revenue()
        week_start = guy.get_current_week_start()
        week_end = guy.get_current_week_end()
        
        # Check if already paid this week
        is_paid = DeliveryGuyWeeklyPayment.objects.filter(
            delivery_guy=guy,
            week_start=week_start,
            week_end=week_end,
            is_paid=True
        ).exists()
        
        delivery_guys_data.append({
            'guy': guy,
            'this_week_deliveries': this_week_deliveries,
            'this_week_revenue': this_week_revenue,
            'week_start': week_start,
            'week_end': week_end,
            'is_paid_this_week': is_paid,
        })
    
    context = {
        'delivery_guys': delivery_guys_data,
    }
    
    return render(request, 'custom_admin/delivery_guys_list.html', context)

@staff_member_required(login_url='admin_login')
def delivery_guy_dashboard(request, delivery_guy_id):
    """Dashboard for a specific delivery guy"""
    delivery_guy = get_object_or_404(DeliveryGuy, id=delivery_guy_id)
    
    # Get all delivered orders for this delivery guy
    delivered_orders = Order.objects.filter(
        delivery_guy=delivery_guy,
        status='delivered'
    ).order_by('-delivered_at').select_related('user')
    
    # Statistics
    total_deliveries = delivered_orders.count()
    total_revenue = delivered_orders.aggregate(total=Sum('total'))['total'] or 0
    
    # Orders per day (last 7 days)
    seven_days_ago = timezone.now() - timedelta(days=7)
    recent_deliveries = delivered_orders.filter(
        delivered_at__gte=seven_days_ago
    ).annotate(day=TruncDate('delivered_at')).values('day').annotate(
        count=Count('id'),
        revenue=Sum('total')
    ).order_by('day')
    
    context = {
        'delivery_guy': delivery_guy,
        'total_deliveries': total_deliveries,
        'total_revenue': total_revenue,
        'delivered_orders': delivered_orders,
        'recent_deliveries': list(recent_deliveries),
    }
    
    return render(request, 'custom_admin/delivery_guy_dashboard.html', context)

@staff_member_required(login_url='admin_login')
@require_http_methods(["POST"])
@staff_member_required(login_url='admin_login')
@require_http_methods(["POST"])
def add_delivery_guy(request):
    """Add a new delivery guy"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    name = data.get('name', '').strip()
    phone_number = data.get('phone_number', '').strip()

    if not name:
        return JsonResponse({'success': False, 'message': 'Name is required'}, status=400)

    if not phone_number:
        return JsonResponse({'success': False, 'message': 'Phone number is required'}, status=400)

    delivery_guy = DeliveryGuy.objects.create(
        name=name,
        phone_number=phone_number,
        is_active=True
    )

    return JsonResponse({
        'success': True,
        'message': f'Delivery guy "{name}" added successfully',
        'delivery_guy_id': delivery_guy.id,
        'name': delivery_guy.name,
        'phone_number': delivery_guy.phone_number,
    })


@staff_member_required(login_url='admin_login')
@require_http_methods(["PUT"])
def edit_delivery_guy(request, delivery_guy_id):
    """Edit delivery guy"""
    delivery_guy = get_object_or_404(DeliveryGuy, id=delivery_guy_id)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    name = data.get('name', '').strip()
    phone_number = data.get('phone_number', '').strip()
    is_active = data.get('is_active', delivery_guy.is_active)

    if not name:
        return JsonResponse({'success': False, 'message': 'Name is required'}, status=400)

    if not phone_number:
        return JsonResponse({'success': False, 'message': 'Phone number is required'}, status=400)

    delivery_guy.name = name
    delivery_guy.phone_number = phone_number
    delivery_guy.is_active = is_active
    delivery_guy.save()

    return JsonResponse({
        'success': True,
        'message': f'Delivery guy "{name}" updated successfully',
        'delivery_guy_id': delivery_guy.id,
    })


@staff_member_required(login_url='admin_login')
@require_http_methods(["POST"])
def toggle_delivery_guy_status(request, delivery_guy_id):
    """Toggle delivery guy active status"""
    delivery_guy = get_object_or_404(DeliveryGuy, id=delivery_guy_id)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    is_active = data.get('is_active')
    if is_active is None:
        is_active = not delivery_guy.is_active
    
    delivery_guy.is_active = is_active
    delivery_guy.save()

    status = 'activated' if is_active else 'deactivated'
    return JsonResponse({
        'success': True,
        'message': f'Delivery guy "{delivery_guy.name}" {status}',
        'is_active': delivery_guy.is_active,
    })


@staff_member_required(login_url='admin_login')
@require_http_methods(["DELETE"])
def delete_delivery_guy(request, delivery_guy_id):
    """Delete delivery guy"""
    delivery_guy = get_object_or_404(DeliveryGuy, id=delivery_guy_id)
    name = delivery_guy.name
    delivery_guy.delete()

    return JsonResponse({
        'success': True,
        'message': f'Delivery guy "{name}" deleted successfully',
    })


@staff_member_required(login_url='admin_login')
@require_http_methods(["POST"])
def mark_delivery_guy_paid_weekly(request, delivery_guy_id):
    """Mark delivery guy as paid for the current week and reset delivery count"""
    try:
        delivery_guy = get_object_or_404(DeliveryGuy, id=delivery_guy_id)
        
        # Get or create current week's payment record
        weekly_payment = delivery_guy.get_or_create_current_week_payment()
        
        # Mark as paid and set paid_at timestamp
        weekly_payment.is_paid = True
        weekly_payment.paid_at = timezone.now()
        weekly_payment.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Marked {delivery_guy.name} as paid for week of {weekly_payment.week_start} to {weekly_payment.week_end}',
            'delivery_guy_id': delivery_guy_id,
            'deliveries_this_week': 0,  # Reset to 0 after marking paid
            'week_start': str(weekly_payment.week_start),
            'week_end': str(weekly_payment.week_end),
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error marking as paid: {str(e)}'
        }, status=400)


@staff_member_required(login_url='admin_login')
@require_http_methods(["GET"])
def get_delivery_guy_week_deliveries(request, delivery_guy_id):
    """Get current week's delivery count for a delivery guy"""
    try:
        delivery_guy = get_object_or_404(DeliveryGuy, id=delivery_guy_id)
        
        week_deliveries = delivery_guy.get_this_week_deliveries()
        week_revenue = delivery_guy.get_this_week_revenue()
        week_start = delivery_guy.get_current_week_start()
        week_end = delivery_guy.get_current_week_end()
        
        # Check if already paid this week
        weekly_payment = DeliveryGuyWeeklyPayment.objects.filter(
            delivery_guy=delivery_guy,
            week_start=week_start,
            week_end=week_end,
            is_paid=True
        ).first()
        
        is_paid = weekly_payment is not None
        
        return JsonResponse({
            'success': True,
            'delivery_guy_id': delivery_guy_id,
            'week_deliveries': week_deliveries,
            'week_revenue': float(week_revenue),
            'week_start': str(week_start),
            'week_end': str(week_end),
            'is_paid': is_paid,
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error fetching deliveries: {str(e)}'
        }, status=400)


# ==================== SITE SETTINGS ====================


@staff_member_required(login_url='admin_login')
def site_settings_view(request):
    """Manage site settings and Daraja configuration for the store"""
    user = request.user
    store = getattr(user, 'store', None)
    
    # Singleton site settings (global)
    site_settings = SiteSettings.get_instance()
    
    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Handle both JSON and FormData
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST.dict()
            
            # Global settings
            delivery_fee = data.get('delivery_fee')
            if delivery_fee is not None:
                site_settings.delivery_fee = delivery_fee
                site_settings.save()
            
            # Store-specific settings
            if store:
                # Branding settings (only if not on base plan)
                if store.plan != 'base':
                    if 'shop_name' in data:
                        store.shop_name = data.get('shop_name')
                    if 'primary_color' in data:
                        store.primary_color = data.get('primary_color')
                    if 'secondary_color' in data:
                        store.secondary_color = data.get('secondary_color')
                    if 'tagline' in data:
                        store.tagline = data.get('tagline')
                    if request.FILES.get('logo'):
                        store.logo = request.FILES.get('logo')
                
                store.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Settings updated successfully',
                    'delivery_fee': float(site_settings.delivery_fee),
                    'shop_name': store.shop_name
                })
            
            return JsonResponse({
                'success': True,
                'message': 'Global settings updated',
                'delivery_fee': float(site_settings.delivery_fee)
            })
    
    context = {
        'settings': site_settings,
        'store': store
    }
    
    return render(request, 'custom_admin/site_settings.html', context)
