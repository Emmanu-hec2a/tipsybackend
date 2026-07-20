from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets, permissions, authentication
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.throttling import ScopedRateThrottle
from django.utils import timezone
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import TruncDate
from .models import (
    Order, FoodItem, User, Store, OrderItem, FoodCategory, 
    Promotion, SubscriptionPayment, MarketingBlast, WeeklyRevenueStat, PartnerPayout
)
from .api_v1_serializers import (
    OrderSerializer, FoodItemSerializer, UserSerializer, 
    StoreSerializer, FoodCategorySerializer, PromotionSerializer,
    SubscriptionPaymentSerializer, OrderItemSerializer
)
from .permissions import IsPartner, QueryParamJWTAuthentication
from .utils import haversine_distance_km
from .tasks import send_marketing_blast_task
from datetime import timedelta
from django.shortcuts import get_object_or_404
import logging
import io
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.http import HttpResponse

logger = logging.getLogger(__name__)

class PartnerBaseView:
    permission_classes = [IsPartner]
    authentication_classes = [QueryParamJWTAuthentication, authentication.SessionAuthentication]
    
    def get_store(self, request):
        try:
            return request.user.store
        except Exception:
            return None

class PartnerStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        if request.user.role != 'partner':
            return Response({'error': 'Not a partner account'}, status=403)
        
        has_store = False
        try:
            has_store = hasattr(request.user, 'store')
        except:
            pass
            
        return Response({
            'is_approved': request.user.is_approved,
            'has_store': has_store,
            'business_name': request.user.business_name
        })

class DashboardStatsView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_404_NOT_FOUND)
            
        today = timezone.localdate()
        start_of_day = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
        end_of_day = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.max.time()))
        
        # Today's core metrics
        today_orders = Order.objects.filter(store=store, created_at__range=(start_of_day, end_of_day))
        # Revenue is sum of 'paid' orders for today
        today_revenue = today_orders.filter(
            payment_status='paid'
        ).aggregate(total=Sum('total'))['total'] or 0
        
        # Operational KPIs
        pending_orders = Order.objects.filter(store=store, status='pending').count()
        processing_orders = Order.objects.filter(store=store, status='processing').count()
        low_stock_count = FoodItem.objects.filter(store=store, stock__lte=F('low_stock_threshold'), is_active=True).count()
        
        # Monthly Growth / Performance
        start_of_month = timezone.make_aware(timezone.datetime.combine(today.replace(day=1), timezone.datetime.min.time()))
        monthly_orders = Order.objects.filter(store=store, created_at__gte=start_of_month)
        monthly_revenue = monthly_orders.filter(
            payment_status='paid'
        ).aggregate(total=Sum('total'))['total'] or 0

        # ⚠️ Payout Alert Logic
        # Check if there are any unpaid weeks before current week
        unpaid_weeks = WeeklyRevenueStat.objects.filter(
            store=store, 
            week_end__lt=today,
            status='unpaid',
            partner_share_40__gt=0
        )
        
        has_unpaid_overdue = unpaid_weeks.exists()
        is_restricted = unpaid_weeks.count() >= 2

        return Response({
            'today_orders': today_orders.count(),
            'today_revenue': float(today_revenue),
            'pending_orders': pending_orders,
            'processing_orders': processing_orders,
            'low_stock_count': low_stock_count,
            'monthly_revenue': float(monthly_revenue),
            'monthly_orders': monthly_orders.count(),
            'has_unpaid_overdue': has_unpaid_overdue,
            'is_restricted': is_restricted
        })

class OrderListView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response([], status=status.HTTP_403_FORBIDDEN)

        status_filter = request.query_params.get('status')
        orders = Order.objects.filter(store=store).exclude(status='payment_pending')

        if status_filter:
            orders = orders.filter(status=status_filter)

        orders = orders.order_by('-created_at')
        serializer = OrderSerializer(orders[:10], many=True)
        return Response(serializer.data)
class OrderDetailView(PartnerBaseView, APIView):
    def get(self, request, pk):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_403_FORBIDDEN)
        try:
            order = Order.objects.get(pk=pk, store=store)
            serializer = OrderSerializer(order)
            return Response(serializer.data)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, pk):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_403_FORBIDDEN)
        try:
            order = Order.objects.get(pk=pk, store=store)
            new_status = request.data.get('status')
            if new_status:
                order.status = new_status
                order.save()
            return Response(OrderSerializer(order).data)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

class AssignRiderView(PartnerBaseView, APIView):
    def post(self, request, pk):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_403_FORBIDDEN)
        try:
            order = Order.objects.get(pk=pk, store=store)
            rider_id = request.data.get('rider_id')
            rider = User.objects.get(id=rider_id, role='rider', assigned_store=store)
            
            order.assigned_rider = rider
            order.status = 'assigned'
            order.save()
            
            from .utils import notify_rider_assigned
            notify_rider_assigned(order, rider)
            
            return Response({'message': f'Order assigned to {rider.username}'})
        except (Order.DoesNotExist, User.DoesNotExist):
            return Response({'error': 'Order or Rider not found'}, status=status.HTTP_404_NOT_FOUND)

class MenuItemViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPartner]
    serializer_class = FoodItemSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_queryset(self):
        try:
            return FoodItem.objects.filter(store=self.request.user.store)
        except Exception:
            return FoodItem.objects.none()

    def perform_create(self, serializer):
        category_name = self.request.data.get('category_name')
        category_fkey = None
        if category_name:
            category_fkey = FoodCategory.objects.filter(name__iexact=category_name).first()
        
        serializer.save(store=self.request.user.store, category_fkey=category_fkey)

    def create(self, request, *args, **kwargs):
        # Log request data for debugging 400 errors
        logger.info(f"POST Product Data: {request.data}")
        
        # Strip 'image' if it's a string (e.g. empty string or previous URL)
        data = request.data.copy()
        if 'image' in data and isinstance(data['image'], str):
            del data['image']
            
        # Convert empty strings to None for numeric fields to avoid validation errors
        numeric_fields = ['price', 'original_price', 'stock', 'low_stock_threshold', 'prep_time', 'discount_percent']
        for field in numeric_fields:
            if field in data and data[field] == '':
                data[field] = None
            
        serializer = self.get_serializer(data=data)
        if not serializer.is_valid():
            logger.error(f"Validation Errors (POST): {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        category_name = self.request.data.get('category_name')
        if category_name:
            category_fkey = FoodCategory.objects.filter(name__iexact=category_name).first()
            serializer.save(category_fkey=category_fkey)
        else:
            serializer.save()

    def update(self, request, *args, **kwargs):
        # Log request data for debugging 400 errors
        logger.info(f"PATCH Product Data: {request.data}")
        
        # Strip fields that might cause validation errors if passed as invalid types from frontend
        # For example, if 'image' is a string URL, we shouldn't try to save it as a file
        data = request.data.copy()
        if 'image' in data and isinstance(data['image'], str):
            del data['image']
            
        # Convert empty strings to None for numeric fields
        numeric_fields = ['price', 'original_price', 'stock', 'low_stock_threshold', 'prep_time', 'discount_percent']
        for field in numeric_fields:
            if field in data and data[field] == '':
                data[field] = None
            
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=data, partial=partial)
        if not serializer.is_valid():
            logger.error(f"Validation Errors: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_update(serializer)
        return Response(serializer.data)

class CategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPartner]
    serializer_class = FoodCategorySerializer

    def get_queryset(self):
        return FoodCategory.objects.all()

class PromotionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPartner]
    serializer_class = PromotionSerializer

    def get_queryset(self):
        try:
            return Promotion.objects.filter(store=self.request.user.store)
        except Exception:
            return Promotion.objects.none()

    def perform_create(self, serializer):
        serializer.save(store=self.request.user.store)

class InventoryStatsView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({
                'out_of_stock': 0, 'low_stock': 0, 'active_items': 0
            }, status=status.HTTP_403_FORBIDDEN)
            
        out_of_stock = FoodItem.objects.filter(store=store, stock=0).count()
        low_stock = FoodItem.objects.filter(store=store, stock__gt=0, stock__lt=F('low_stock_threshold')).count()
        active_items = FoodItem.objects.filter(store=store, is_active=True).count()
        
        return Response({
            'out_of_stock': out_of_stock,
            'low_stock': low_stock,
            'active_items': active_items
        })

class PayoutHistoryView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response([], status=status.HTTP_403_FORBIDDEN)
        return Response([])

class UpdateStockView(PartnerBaseView, APIView):
    def patch(self, request, pk):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_403_FORBIDDEN)
        try:
            product = FoodItem.objects.get(pk=pk, store=store)
            new_stock = request.data.get('stock')
            if new_stock is not None:
                product.stock = new_stock
                product.save()
            return Response(FoodItemSerializer(product).data)
        except FoodItem.DoesNotExist:
            return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

class CustomerListView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response([], status=status.HTTP_403_FORBIDDEN)
        customer_ids = Order.objects.filter(store=store).values_list('user_id', flat=True).distinct()
        customers = User.objects.filter(id__in=customer_ids)
        serializer = UserSerializer(customers, many=True)
        return Response(serializer.data)

class RiderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsPartner]
    serializer_class = UserSerializer

    def get_queryset(self):
        try:
            return User.objects.filter(assigned_store=self.request.user.store, role='rider')
        except Exception:
            return User.objects.none()

    def perform_create(self, serializer):
        serializer.save(role='rider', assigned_store=self.request.user.store, is_approved=True)

class ToggleRiderAvailabilityView(PartnerBaseView, APIView):
    def patch(self, request, pk):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_403_FORBIDDEN)
        try:
            rider = User.objects.get(pk=pk, assigned_store=store, role='rider')
            rider.is_available = not rider.is_available
            rider.save()
            return Response({'is_available': rider.is_available})
        except User.DoesNotExist:
            return Response({'error': 'Rider not found'}, status=status.HTTP_404_NOT_FOUND)

class AnalyticsSummaryView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({
                'total_revenue': 0, 'total_orders': 0, 
                'completed_orders': 0, 'pending_orders': 0, 'cancelled_orders': 0
            }, status=status.HTTP_403_FORBIDDEN)
            
        total_revenue = Order.objects.filter(store=store, payment_status='paid').aggregate(Sum('total'))['total__sum'] or 0
        total_orders = Order.objects.filter(store=store).count()
        
        # Real-time status breakdown
        completed_orders = Order.objects.filter(store=store, status='delivered').count()
        pending_orders = Order.objects.filter(store=store, status__in=['pending', 'confirmed', 'assigned', 'picked_up', 'arrived']).count()
        cancelled_orders = Order.objects.filter(store=store, status='cancelled').count()

        return Response({
            'total_revenue': float(total_revenue),
            'total_orders': total_orders,
            'completed_orders': completed_orders,
            'pending_orders': pending_orders,
            'cancelled_orders': cancelled_orders
        })

class RevenueAnalyticsView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response([], status=status.HTTP_403_FORBIDDEN)
        range_param = request.query_params.get('range', '7d')
        
        days = 7
        if range_param == '30d': days = 30
        elif range_param == '90d': days = 90
        
        today = timezone.localdate()
        start_date = today - timedelta(days=days)
        start_datetime = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
        
        revenue_data = Order.objects.filter(
            store=store, 
            payment_status='paid',
            created_at__gte=start_datetime
        ).annotate(day=TruncDate('created_at')).values('day').annotate(
            revenue=Sum('total'),
            orders=Count('id')
        ).order_by('day')
        
        # Ensure revenue is a float for JSON serialization
        results = []
        for item in revenue_data:
            results.append({
                'day': item['day'].isoformat() if hasattr(item['day'], 'isoformat') else str(item['day']),
                'revenue': float(item['revenue'] or 0),
                'orders': item['orders']
            })
            
        return Response(results)

class TopProductsAnalyticsView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response([], status=status.HTTP_403_FORBIDDEN)
        top_products = OrderItem.objects.filter(
            order__store=store,
            order__payment_status='paid'
        ).values('food_item__name').annotate(
            total_sold=Sum('quantity'),
            total_revenue=Sum(F('quantity') * F('price_at_order'))
        ).order_by('-total_sold')[:10]
        
        return Response(list(top_products))

class StoreSettingsView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated', 'approval_pending': True}, status=status.HTTP_404_NOT_FOUND)
        return Response(StoreSerializer(store, context={'request': request}).data)
    
    def patch(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=status.HTTP_403_FORBIDDEN)
        
        # Log request data for debugging
        logger.info(f"PATCH Store Settings: {request.data}")
            
        serializer = StoreSerializer(store, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        logger.error(f"Store Settings Validation Errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class OrderInvoiceView(PartnerBaseView, APIView):
    def get(self, request, pk):
        store = self.get_store(request)
        try:
            order = Order.objects.get(pk=pk, store=store)
            template = get_template('invoices/invoice_template.html')
            
            context = {
                'order': order,
                'store': store,
                'items': order.items.all(),
                'logo_url': request.build_absolute_uri(store.logo.url) if store.logo else None,
                'date': timezone.now().strftime('%d %b, %Y')
            }
            
            html = template.render(context)
            result = io.BytesIO()
            pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)
            
            if not pdf.err:
                response = HttpResponse(result.getvalue(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="invoice_{order.order_number}.pdf"'
                return response
            return Response({'error': 'PDF generation failed'}, status=400)
            
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

class NearbyRidersView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store or not store.latitude or not store.longitude:
            return Response({'error': 'Store location not configured'}, status=400)
            
        radius = float(store.delivery_radius_km)
        
        # Get all riders assigned to this store who are available
        riders = User.objects.filter(role='rider', is_available=True)
        
        nearby_riders = []
        for rider in riders:
            # Get latest ping within last 30 minutes
            last_ping = rider.location_pings.filter(
                created_at__gte=timezone.now() - timedelta(minutes=30)
            ).order_by('-created_at').first()
            
            if last_ping:
                dist = haversine_distance_km(
                    float(store.latitude), float(store.longitude),
                    float(last_ping.latitude), float(last_ping.longitude)
                )
                
                if dist <= radius:
                    nearby_riders.append({
                        'id': rider.id,
                        'username': rider.username,
                        'phone': rider.phone,
                        'avg_rating': float(rider.avg_rating),
                        'distance_km': round(dist, 2),
                        'last_seen': last_ping.created_at
                    })
        
        # Sort by distance
        nearby_riders.sort(key=lambda x: x['distance_km'])
        return Response(nearby_riders)

class MarketingBlastView(PartnerBaseView, APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'merchant_blast'

    def post(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=403)
            
        if store.plan != 'pro':
            return Response({'error': 'Marketing Blast is a Pro feature'}, status=403)
            
        # 1-hour cooling lock check
        last_blast = MarketingBlast.objects.filter(store=store).order_by('-created_at').first()
        if last_blast and (timezone.now() - last_blast.created_at) < timedelta(hours=1):
            remaining = timedelta(hours=1) - (timezone.now() - last_blast.created_at)
            minutes = int(remaining.total_seconds() / 60)
            return Response({
                'error': f'Cooling lock active. Please wait {minutes} minutes before the next blast.'
            }, status=429)

        message = request.data.get('message')
        if not message:
            return Response({'error': 'Message is required'}, status=400)
            
        # Create record
        blast = MarketingBlast.objects.create(
            store=store,
            message=message
        )
        
        # Hand off to Celery
        send_marketing_blast_task.delay(store.id, blast.id)
        
        return Response({
            'message': 'Marketing blast initiated and will be delivered shortly.',
            'blast_id': blast.id,
            'target_count': Order.objects.filter(store=store).values('user').distinct().count()
        }, status=202)

class MarketingStatsView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=403)
            
        # Real aggregations
        customer_reach = Order.objects.filter(store=store).values('user').distinct().count()
        menu_clicks = Order.objects.filter(store=store).count() * 4 # Mock multiplier based on orders
        store_views = (store.rating_count * 15) + (customer_reach * 2)
        
        # Get recent blasts
        recent_blasts = MarketingBlast.objects.filter(store=store).order_by('-created_at')[:5]
        blasts_data = [{
            'id': b.id,
            'message': b.message,
            'target_count': b.target_count,
            'created_at': b.created_at.isoformat()
        } for b in recent_blasts]

        # Calculate cooldown status
        cooldown_active = False
        if recent_blasts:
            time_since_last = timezone.now() - recent_blasts[0].created_at
            cooldown_active = time_since_last < timedelta(hours=1)

        return Response({
            'store_views': f"{store_views:,}",
            'menu_clicks': f"{menu_clicks:,}",
            'customer_reach': f"{customer_reach:,}",
            'brand_score': 'A+' if store.rating >= 4.5 else 'A' if store.rating >= 4.0 else 'B',
            'recent_blasts': blasts_data,
            'can_blast': not cooldown_active
        })

class RevenueSharingView(PartnerBaseView, APIView):
    def get(self, request):
        store = self.get_store(request)
        if not store:
            return Response({'error': 'No store associated'}, status=403)

        # Get current week
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        current_stat, _ = WeeklyRevenueStat.objects.get_or_create(
            store=store,
            week_start=week_start,
            defaults={'week_end': week_end}
        )

        # Get history (including current week if not paid)
        history = WeeklyRevenueStat.objects.filter(
            store=store
        ).order_by('-week_start')

        history_data = []
        for h in history:
            payout = PartnerPayout.objects.filter(week_stat=h).first()
            history_data.append({
                'id': h.id,
                'week_start': h.week_start,
                'week_end': h.week_end,
                'total_liquor_sales': float(h.total_liquor_sales),
                'partner_share': float(h.partner_share_40),
                'status': h.status,
                'mpesa_code': payout.mpesa_code if payout else None,
                'paid_at': payout.paid_at if payout else None
            })

        return Response({
            'current_week': {
                'id': current_stat.id,
                'week_start': current_stat.week_start,
                'week_end': current_stat.week_end,
                'total_liquor_sales': float(current_stat.total_liquor_sales),
                'partner_share': float(current_stat.partner_share_40),
                'status': current_stat.status
            },
            'history': history_data
        })

    def post(self, request):
        # Mark as paid
        stat_id = request.data.get('stat_id')
        mpesa_code = request.data.get('mpesa_code')
        
        if not stat_id or not mpesa_code:
            return Response({'error': 'Missing stat_id or mpesa_code'}, status=400)
            
        store = self.get_store(request)
        stat = get_object_or_404(WeeklyRevenueStat, id=stat_id, store=store)
        
        if stat.status != 'unpaid':
            return Response({'error': f'Cannot pay. Current status is {stat.status}'}, status=400)
            
        PartnerPayout.objects.create(
            store=store,
            week_stat=stat,
            amount=stat.partner_share_40,
            mpesa_code=mpesa_code.upper()
        )
        
        stat.status = 'pending'
        stat.is_paid = False # Safety
        stat.save()
        
        # 🛡️ Notify Admin of new payout to verify
        from .utils import send_telegram_notification
        msg = (
            f"💰 <b>New Revenue Payout Submission</b>\n"
            f"Store: {store.name}\n"
            f"Amount: KSh {stat.partner_share_40}\n"
            f"M-Pesa Code: {mpesa_code.upper()}\n"
            f"Week: {stat.week_start} to {stat.week_end}\n"
            f"<i>Please verify and approve in Admin panel.</i>"
        )
        # Use configured Admin Chat ID or fallback to legacy
        from django.conf import settings
        admin_chat_id = getattr(settings, 'TELEGRAM_ADMIN_CHAT_ID', None) or "5191834221"
        send_telegram_notification(admin_chat_id, msg, bot_type='admin')
        
        return Response({'status': 'success', 'message': 'Payment submitted for verification'})

class VerifyRevenueGateView(PartnerBaseView, APIView):
    def post(self, request):
        password = request.data.get('password')
        # Default security gate password for V1
        if password == "TipsyPartner2026":
            return Response({'success': True})
        return Response({'success': False}, status=401)
