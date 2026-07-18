from django.urls import path
from . import views
from . import admin_views
from . import api_v1_customer_views

app_name = 'urbanfoods'

urlpatterns = [
    # Public pages
    path('', views.homepage, name='homepage'),
    path('shop/<slug:subdomain>/', views.homepage, name='store_home'),
    path('offline/', views.offline, name='offline'),

    # Authentication
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Cart operations
    path('api/cart/', views.get_cart, name='get_cart'),
    path('api/cart/add/', views.add_to_cart, name='add_to_cart'),
    path('api/cart/update/', views.update_cart_item, name='update_cart_item'),
    path('api/cart/remove/', views.remove_from_cart, name='remove_from_cart'),

    # Order placement
    path('api/order/place/', views.place_order, name='place_order'),

    #Robots.txt
    path('robots.txt', views.robots_txt, name='robots_txt'),

    # MPESA integration
    path('api/mpesa/initiate/', views.initiate_mpesa_payment, name='initiate_mpesa_payment'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path('api/mpesa/stk-query/', views.mpesa_stk_query, name='mpesa_stk_query'),

    # Order tracking
    path('orders/', views.my_orders, name='my_orders'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('api/orders/<str:order_number>/status/', views.order_status_api, name='order_status_api'),
    path('api/orders/pending-review/', views.pending_review_order, name='pending_review_order'),
    path('api/orders/<str:order_number>/dismiss-review/', views.dismiss_review_prompt, name='dismiss_review_prompt'),

    # User profile
    path('profile/', views.profile, name='profile'),
    path('orders/<str:order_number>/rate/', views.rate_order, name='rate_order'),
    path('orders/<str:order_number>/submit_review/', views.submit_food_review, name='submit_food_review'),

    # Admin - Delivery Guys
    path('admin/delivery-guys/', admin_views.delivery_guys_list, name='delivery_guys_list'),
    path('admin/delivery-guys/<int:delivery_guy_id>/', admin_views.delivery_guy_dashboard, name='delivery_guy_dashboard'),
    
    # Admin - Site Settings
    path('admin/settings/', admin_views.site_settings_view, name='site_settings'),

    # API v1
    path('api/geocode/reverse/', views.reverse_geocode, name='reverse_geocode'),
    path('api/v1/promotions/available/', api_v1_customer_views.AvailablePromotionsView.as_view(), name='api_available_promotions'),
    path('api/v1/promotions/validate/', api_v1_customer_views.ValidatePromotionView.as_view(), name='api_validate_promotion'),
    path('api/v1/auth/customer/login/', views.CustomerLoginView.as_view(), name='api_customer_login'),
    path('api/v1/auth/partner/login/', views.PartnerLoginView.as_view(), name='api_partner_login'),
    path('api/v1/auth/rider/login/', views.RiderLoginView.as_view(), name='api_rider_login'),
    path('api/v1/auth/partner/signup/', views.PartnerSignupView.as_view(), name='api_partner_signup'),
    path('api/v1/auth/partner/approve/<int:user_id>/', views.PartnerApprovalView.as_view(), name='api_partner_approve'),
    
    # Test endpoints
    path('api/v1/test/customer/', views.TestCustomerView.as_view(), name='test_customer'),
    path('api/v1/test/partner/', views.TestPartnerView.as_view(), name='test_partner'),
    path('api/v1/test/rider/', views.TestRiderView.as_view(), name='test_rider'),
    path('api/v1/test/superadmin/', views.TestSuperAdminView.as_view(), name='test_superadmin'),
]

