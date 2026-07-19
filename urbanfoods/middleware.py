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

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model

User = get_user_model()

@database_sync_to_async
def get_user(token_key):
    try:
        access_token = AccessToken(token_key)
        user_id = access_token['user_id']
        return User.objects.get(id=user_id)
    except Exception:
        return AnonymousUser()

class JWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        query_params = dict(qp.split('=') for qp in query_string.split('&') if '=' in qp)
        token_key = query_params.get('token')

        if token_key:
            scope['user'] = await get_user(token_key)
        else:
            scope['user'] = AnonymousUser()

        return await self.app(scope, receive, send)
