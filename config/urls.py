from django.contrib import admin
from django.urls import path, include
from urbanfoods import views, admin_views
from django.conf import settings
from django.views.generic import RedirectView
from django.templatetags.static import static as static_url
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.views.static import serve
from urbanfoods.sitemap import StaticViewSitemap, FoodItemSitemap
from django.contrib.sitemaps.views import sitemap

sitemaps = {
    "static": StaticViewSitemap,
    "products": FoodItemSitemap,
}
# Customize Django Admin site branding
admin.site.site_header = "UrbanDream Backend"
admin.site.site_title = "UrbanDream Database Admin"
admin.site.index_title = "Database Management"

urlpatterns = [
    # ==================== ADMIN PANELS ====================
    # Django's built-in admin (for database management)
    path('backend/', admin.site.urls),
    path('offline/', views.offline, name='offline'),
    
    # Custom admin panel (for operations)
    path('admin-panel/login/', admin_views.admin_login, name='admin_login'),
    path('admin-panel/', admin_views.admin_dashboard, name='admin_dashboard'),
    
    # ==================== PUBLIC PAGES ====================
    path('', views.homepage, name='homepage'),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    
    # Authentication
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Password Reset
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='password_reset.html',
        email_template_name='password_reset_email.txt',
        html_email_template_name='password_reset_email.html',
        subject_template_name='password_reset_subject.txt'
    ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),
    
    # ==================== STORE SWITCHING ================
    path('api/store/switch/', views.switch_store, name='switch_store'),
    
    # ==================== API VERSIONING =================
    path('api/v1/', include('urbanfoods.api_v1_urls')),
    
    # ==================== CART & ORDERS ================
    # Cart operations
    path('api/cart/', views.get_cart, name='get_cart'),
    path('api/cart/add/', views.add_to_cart, name='add_to_cart'),
    path('api/cart/update/', views.update_cart_item, name='update_cart_item'),
    path('api/cart/remove/', views.remove_from_cart, name='remove_from_cart'),
    
    # Order placement
    path('api/order/place/', views.place_order, name='place_order'),
    
    # Order tracking
    path('orders/', views.my_orders, name='my_orders'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('api/orders/<str:order_number>/status/', views.order_status_api, name='order_status_api'),
    
    # User profile
    path('profile/', views.profile, name='profile'),
    
    # ==================== CUSTOM ADMIN DASHBOARD ====================
    # Order management
    path('admin-panel/orders/', admin_views.admin_orders, name='admin_orders'),
    path('admin-panel/orders/<str:order_number>/', admin_views.admin_order_detail, name='admin_order_detail'),
    path('admin-panel/api/orders/new/', admin_views.get_new_orders, name='get_new_orders'),
    path('admin-panel/api/orders/update-status/', admin_views.update_order_status, name='update_order_status'),
    path('admin-panel/api/orders/cancel/', admin_views.cancel_order, name='cancel_order'),
    path('admin-panel/api/orders/payment-details/<str:order_number>/', admin_views.get_payment_details, name='get_payment_details'),

    # =================== MPESA INTEGRATION ===================
    path('api/mpesa/initiate/', views.initiate_mpesa_payment, name='initiate_mpesa_payment'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path('api/mpesa/stk-query/', views.mpesa_stk_query, name='mpesa_stk_query'),
    path('api/order/payment-status/<str:order_number>/', views.check_order_payment_status, name='check_order_payment_status'),

    # Liquor admin
    path('admin-panel/liquor/', admin_views.admin_liquor, name='admin_liquor'),
    path('admin-panel/liquor/dashboard/', admin_views.liquor_dashboard, name='liquor_dashboard'),
    path('admin-panel/liquor/orders/', admin_views.liquor_orders, name='liquor_orders'),
    path('admin-panel/liquor/analytics/', admin_views.liquor_analytics, name='liquor_analytics'),
    path('admin-panel/liquor/orders/<str:order_number>/', admin_views.liquor_order_detail, name='liquor_order_detail'),
    path('admin-panel/api/orders/mpesa-details/', admin_views.mpesa_payment_details, name='admin_mpesa_details'),

    # Menu management
    path('admin-panel/menu/', admin_views.admin_menu, name='admin_menu'),
    path('admin-panel/grocery/', admin_views.admin_grocery, name='admin_grocery'),
    path('admin-panel/api/menu/toggle-availability/', admin_views.toggle_food_availability, name='toggle_food_availability'),
    path('admin-panel/api/menu/update-price/', admin_views.update_food_price, name='update_food_price'),
    path('admin-panel/api/menu/add-category/', admin_views.add_category, name='add_category'),
    path('admin-panel/api/menu/edit-category/', admin_views.edit_category, name='edit_category'),
    path('admin-panel/api/menu/delete-category/', admin_views.delete_category, name='delete_category'),
    path('admin-panel/api/menu/add-food-item/', admin_views.add_food_item, name='add_food_item'),
    path('admin-panel/api/menu/edit-food-item/', admin_views.edit_food_item, name='edit_food_item'),
    path('admin-panel/api/menu/delete-food-item/', admin_views.delete_food_item, name='delete_food_item'),
    path('admin-panel/restock-product/', admin_views.restock_product, name='restock_product'),
    path('admin-panel/api/menu/food-item/<int:item_id>/', admin_views.get_food_item_api, name='get_food_item_api'),

    
    # Analytics
    path('admin-panel/analytics/', admin_views.admin_analytics, name='admin_analytics'),
    
    # Customer management
    path('admin-panel/customers/', admin_views.admin_customers, name='admin_customers'),
    path('admin-panel/customers/<int:customer_id>/', admin_views.admin_customer_detail, name='admin_customer_detail'),
    path('admin-panel/api/customers/<int:customer_id>/orders/', admin_views.get_customer_orders, name='get_customer_orders'),
    path('admin-panel/api/customers/send-message/', admin_views.send_customer_message, name='send_customer_message'),
    path('admin-panel/api/customers/update-status/', admin_views.update_customer_status, name='update_customer_status'),

    # Dashboard API
    path('admin-panel/api/dashboard/stats/', admin_views.admin_dashboard_stats, name='dashboard_stats'),
    path('admin-panel/api/orders/recent/', admin_views.get_new_orders, name='admin_api_new_orders'),
    path('admin-panel/api/admin/update-profile/', admin_views.update_admin_profile, name='admin_api_update_admin_profile'),
    
    # Admin Profile
    path('admin-panel/profile/', admin_views.admin_profile, name='admin_profile'),
    path('admin-panel/api/admin/update-password/', admin_views.update_admin_password, name='admin_api_update_password'),
    
    # Delivery Guys
    path('admin-panel/delivery-guys/', admin_views.delivery_guys_list, name='delivery_guys_list'),
    path('admin-panel/delivery-guys/<int:delivery_guy_id>/', admin_views.delivery_guy_dashboard, name='delivery_guy_dashboard'),
    path('admin-panel/api/delivery-guys/add/', admin_views.add_delivery_guy, name='add_delivery_guy'),
    path('admin-panel/api/delivery-guys/<int:delivery_guy_id>/', admin_views.edit_delivery_guy, name='edit_delivery_guy'),
    path('admin-panel/api/delivery-guys/<int:delivery_guy_id>/toggle-status/', admin_views.toggle_delivery_guy_status, name='toggle_delivery_guy_status'),
    path('admin-panel/api/delivery-guys/<int:delivery_guy_id>/delete/', admin_views.delete_delivery_guy, name='delete_delivery_guy'),
    path('admin-panel/api/delivery-guys/<int:delivery_guy_id>/mark-paid-weekly/', admin_views.mark_delivery_guy_paid_weekly, name='mark_delivery_guy_paid_weekly'),
    path('admin-panel/api/delivery-guys/<int:delivery_guy_id>/week-deliveries/', admin_views.get_delivery_guy_week_deliveries, name='get_delivery_guy_week_deliveries'),
    
    # Site Settings

    path('admin-panel/settings/', admin_views.site_settings_view, name='site_settings'),
    
    # Reviews management

    path('orders/<str:order_number>/submit_review/', views.submit_food_review, name='submit_food_review'),
    path('orders/<str:order_number>/rate/', views.rate_order, name='rate_order'),

    # Favicon
    path('favicon.ico', RedirectView.as_view(url=static_url('images/favicon.png'), permanent=True)),

    #Service Worker & Manifest serving
    path('service-worker.js', serve, {
        'path': 'service-worker.js',
        'document_root': settings.BASE_DIR,  # adjust if files are elsewhere
    }),
    path('manifest.json', serve, {
        'path': 'manifest.json',
        'document_root': settings.BASE_DIR,
    }),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
