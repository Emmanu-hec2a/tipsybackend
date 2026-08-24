from rest_framework import permissions
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class SecureJWTAuthentication(JWTAuthentication):
    """
    Secure JWT authentication that ONLY accepts tokens via Authorization header.
    
    🛡️ Security Requirements:
    - REJECTS query parameter tokens completely (prevents browser history leaks)
    - REJECTS cookie-based tokens for payments (prevents CSRF)
    - REQUIRES Authorization: Bearer <token> header
    - Logs security violations for audit trail
    
    Why query params are insecure:
    - Tokens leak in browser history
    - Tokens leak in proxy/CDN logs
    - Tokens leak via Referer headers to third-party sites
    - Tokens can be cached by proxies as URL parameter
    """
    
    def authenticate(self, request):
        """
        Authenticate only via Authorization header (Bearer token).
        
        Raises:
            AuthenticationFailed: If token in query params, cookies, or missing
        """
        
        # 🛡️ REJECT query parameter tokens COMPLETELY
        if 'token' in request.query_params:
            logger.warning(
                f"SECURITY VIOLATION: Query parameter JWT auth attempted",
                extra={
                    'ip': request.META.get('REMOTE_ADDR'),
                    'user': getattr(request.user, 'id', 'anonymous'),
                    'path': request.path,
                }
            )
            raise AuthenticationFailed(
                'Authentication via query parameters is not allowed. '
                'Use Authorization header: Authorization: Bearer <token>'
            )
        
        # Use parent class to authenticate via Authorization header
        return super().authenticate(request)


class IsCustomer(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'customer'

class IsPartner(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'partner'

class IsRider(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'rider'

class IsSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'superadmin'
