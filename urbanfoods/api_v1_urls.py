from django.urls import path, include
from . import api_v1_partner_views, api_v1_rider_views, api_v1_superadmin_views, api_v1_customer_views, api_v1_billing_views, api_v1_auth_views, views

partner_patterns = [
    path('dashboard/stats/', api_v1_partner_views.DashboardStatsView.as_view(), name='partner_dashboard_stats'),
    path('status/', api_v1_partner_views.PartnerStatusView.as_view(), name='partner_status'),
    path('orders/', api_v1_partner_views.OrderListView.as_view(), name='partner_order_list'),
    path('orders/<int:pk>/', api_v1_partner_views.OrderDetailView.as_view(), name='partner_order_detail'),
    path('orders/<int:pk>/invoice/', api_v1_partner_views.OrderInvoiceView.as_view(), name='partner_order_invoice'),
    path('orders/<int:pk>/assign-rider/', api_v1_partner_views.AssignRiderView.as_view(), name='partner_order_assign_rider'),
    path('riders/nearby/', api_v1_partner_views.NearbyRidersView.as_view(), name='partner_nearby_riders'),
    path('menu/', api_v1_partner_views.MenuItemViewSet.as_view({'get': 'list', 'post': 'create'}), name='partner_menu_list'),
    path('menu/<int:pk>/', api_v1_partner_views.MenuItemViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='partner_menu_detail'),
    path('menu/<int:pk>/stock/', api_v1_partner_views.UpdateStockView.as_view(), name='partner_menu_update_stock'),
    path('categories/', api_v1_partner_views.CategoryViewSet.as_view({'get': 'list', 'post': 'create'}), name='partner_category_list'),
    path('categories/<int:pk>/', api_v1_partner_views.CategoryViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='partner_category_detail'),
    path('inventory/stats/', api_v1_partner_views.InventoryStatsView.as_view(), name='partner_inventory_stats'),
    path('promotions/', api_v1_partner_views.PromotionViewSet.as_view({'get': 'list', 'post': 'create'}), name='partner_promotion_list'),
    path('promotions/<int:pk>/', api_v1_partner_views.PromotionViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='partner_promotion_detail'),
    path('customers/', api_v1_partner_views.CustomerListView.as_view(), name='partner_customer_list'),
    path('payouts/history/', api_v1_partner_views.PayoutHistoryView.as_view(), name='partner_payout_history'),
    path('riders/', api_v1_partner_views.RiderViewSet.as_view({'get': 'list', 'post': 'create'}), name='partner_rider_list'),
    path('riders/<int:pk>/', api_v1_partner_views.RiderViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}), name='partner_rider_detail'),
    path('riders/<int:pk>/toggle-availability/', api_v1_partner_views.ToggleRiderAvailabilityView.as_view(), name='partner_rider_toggle_availability'),
    path('analytics/', api_v1_partner_views.AnalyticsSummaryView.as_view(), name='partner_analytics_summary'),
    path('analytics/revenue/', api_v1_partner_views.RevenueAnalyticsView.as_view(), name='partner_revenue_analytics'),
    path('analytics/top-products/', api_v1_partner_views.TopProductsAnalyticsView.as_view(), name='partner_top_products_analytics'),
    path('marketing/blast/', api_v1_partner_views.MarketingBlastView.as_view(), name='partner_marketing_blast'),
    path('marketing/stats/', api_v1_partner_views.MarketingStatsView.as_view(), name='partner_marketing_stats'),
    path('settings/', api_v1_partner_views.StoreSettingsView.as_view(), name='partner_settings'),
    path('billing/pay-now/', api_v1_billing_views.PayNowView.as_view(), name='partner_billing_pay_now'),
    path('payments/mpesa/initiate/', api_v1_billing_views.PayNowView.as_view(), name='partner_payments_mpesa_initiate'),
    path('billing/history/', api_v1_billing_views.SubscriptionHistoryView.as_view(), name='partner_billing_history'),
]

customer_patterns = [
    path('profile/', api_v1_customer_views.CustomerProfileView.as_view(), name='customer_profile'),
    path('profile/redeem/', api_v1_customer_views.CustomerRedeemPointsView.as_view(), name='customer_redeem_points'),
    path('addresses/', api_v1_customer_views.SavedAddressViewSet.as_view(), name='customer_address_list'),
    path('addresses/<int:pk>/', api_v1_customer_views.SavedAddressDetailView.as_view(), name='customer_address_detail'),
    path('stores/', api_v1_customer_views.CustomerStoreListView.as_view(), name='customer_store_list'),
    path('stores/<int:pk>/', api_v1_customer_views.CustomerStoreDetailView.as_view(), name='customer_store_detail'),
    path('stores/<int:pk>/favourite/', api_v1_customer_views.CustomerToggleFavouriteView.as_view(), name='customer_toggle_favourite'),
    path('stores/favourites/', api_v1_customer_views.CustomerFavouriteStoresListView.as_view(), name='customer_favourite_list'),
    path('categories/', api_v1_customer_views.CustomerCategoryListView.as_view(), name='customer_category_list'),
    path('products/', api_v1_customer_views.CustomerProductListView.as_view(), name='customer_product_list'),
    path('orders/', api_v1_customer_views.CustomerOrderListView.as_view(), name='customer_order_list'),
    path('orders/create/', api_v1_customer_views.CustomerPlaceOrderView.as_view(), name='customer_place_order'),
    path('orders/<int:pk>/', api_v1_customer_views.CustomerOrderDetailView.as_view(), name='customer_order_detail'),
    path('orders/<int:pk>/rate/', api_v1_customer_views.CustomerRateOrderView.as_view(), name='customer_rate_order'),
]

auth_patterns = [
    path('fcm-token/', views.SaveFCMTokenView.as_view(), name='save_fcm_token'),
    path('login/', api_v1_auth_views.UnifiedLoginView.as_view(), name='unified_login_api'),
    path('social-login/', api_v1_auth_views.FirebaseSocialLoginView.as_view(), name='firebase_social_login'),
    path('partner/login/', views.PartnerLoginView.as_view(), name='partner_login_api'),
    path('partner/signup/', views.PartnerSignupView.as_view(), name='partner_signup_api'),
    path('rider/login/', views.RiderLoginView.as_view(), name='rider_login_api'),
    path('rider/signup/', api_v1_auth_views.RiderSignupView.as_view(), name='rider_signup_api'),
    path('customer/login/', views.CustomerLoginView.as_view(), name='customer_login_api'),
    path('customer/signup/', api_v1_auth_views.CustomerSignupView.as_view(), name='customer_signup_api'),
]

rider_patterns = [
    path('orders/queue/', api_v1_rider_views.RiderOrderQueueView.as_view(), name='rider_order_queue'),
    path('orders/history/', api_v1_rider_views.RiderHistoryView.as_view(), name='rider_order_history'),
    path('orders/<int:order_id>/accept/', api_v1_rider_views.RiderAcceptOrderView.as_view(), name='rider_order_accept'),
    path('orders/<int:order_id>/status/', api_v1_rider_views.RiderOrderStatusView.as_view(), name='rider_order_status'),
    path('location/ping/', api_v1_rider_views.RiderLocationPingView.as_view(), name='rider_location_ping'),
    path('earnings/', api_v1_rider_views.RiderEarningsView.as_view(), name='rider_earnings'),
    path('earnings/summary/', api_v1_rider_views.RiderEarningsSummaryView.as_view(), name='rider_earnings_summary'),
    path('profile/', api_v1_rider_views.RiderProfileView.as_view(), name='rider_profile'),
]

superadmin_patterns = [
    path('stores/', api_v1_superadmin_views.StoreListView.as_view(), name='superadmin_store_list'),
    path('stores/<int:pk>/', api_v1_superadmin_views.StoreDetailView.as_view(), name='superadmin_store_detail'),
    path('partners/<int:pk>/approve/', api_v1_superadmin_views.PartnerApproveView.as_view(), name='superadmin_partner_approve'),
    path('partners/<int:pk>/suspend/', api_v1_superadmin_views.PartnerSuspendView.as_view(), name='superadmin_partner_suspend'),
    path('orders/', api_v1_superadmin_views.PlatformOrdersView.as_view(), name='superadmin_orders'),
    path('analytics/', api_v1_superadmin_views.PlatformAnalyticsView.as_view(), name='superadmin_analytics'),
    path('pending-partners/', api_v1_superadmin_views.PendingPartnersView.as_view(), name='superadmin_pending_partners'),
]

urlpatterns = [
    path('fcm-token/', views.SaveFCMTokenView.as_view(), name='save_fcm_token_root'),
    path('customer/profile/', api_v1_customer_views.CustomerProfileView.as_view(), name='customer_profile_api_alt'),
    path('partner/', include(partner_patterns)),
    path('rider/', include(rider_patterns)),
    path('customer/', include(customer_patterns)),
    path('orders/<int:pk>/rate/', api_v1_customer_views.CustomerRateOrderView.as_view(), name='customer_rate_order_compat'),
    path('superadmin/', include(superadmin_patterns)),
    path('auth/', include(auth_patterns)),
    path('billing/callback/', api_v1_billing_views.subscription_callback, name='subscription_callback'),
    path('geocode/reverse/', views.reverse_geocode, name='api_reverse_geocode'),
    path('orders/<str:order_number>/verification-image/', views.OrderVerificationImageView.as_view(), name='order_verification_image'),
    path('ai/chat/', views.TheoryAIChatView.as_view(), name='ai_chat'),
    path('ai/voice-upload/', views.TempVoiceUploadView.as_view(), name='ai_voice_upload'),
    path('ai/transcribe/', views.SecureTranscriptionView.as_view(), name='ai_transcribe'),
    path('ai/speak/', views.SecureTTSView.as_view(), name='ai_speak'),
]
