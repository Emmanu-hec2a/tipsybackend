# urbanfoods/middleware.py
from django.conf import settings
from importlib import import_module
from .models import Store

class CustomAdminSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.user_engine = import_module(settings.SESSION_ENGINE)
        self.admin_engine = import_module(settings.ADMIN_SESSION_ENGINE)

    def __call__(self, request):
        # If it's admin-panel, use admin session
        if request.path.startswith("/admin-panel/"):
            session_key = request.COOKIES.get(settings.ADMIN_SESSION_COOKIE_NAME, None)
            request.session = self.admin_engine.SessionStore(session_key)
            request.session_cookie_name = settings.ADMIN_SESSION_COOKIE_NAME
        else:
            session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME, None)
            request.session = self.user_engine.SessionStore(session_key)
            request.session_cookie_name = settings.SESSION_COOKIE_NAME

        response = self.get_response(request)
        return response

class StoreMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        parts = path.split('/')
        # Path: /shop/<slug>/...
        if len(parts) >= 3 and parts[1] == 'shop':
            try:
                request.store = Store.objects.get(subdomain=parts[2], is_active=True)
            except Store.DoesNotExist:
                request.store = None
        else:
            request.store = None
            
        return self.get_response(request)
