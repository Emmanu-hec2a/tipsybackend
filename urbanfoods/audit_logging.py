"""
Admin Action Audit Logging for Payment Operations

Provides comprehensive audit trail for all admin actions on payment-related models.
Logs who, when, what, and why for regulatory compliance.

PCI DSS Requirement 10.2: Implement automated audit trails for access to payment data
GDPR: Maintain audit trail for all access to personal payment information
"""

import logging
import json
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.admin import models as admin_models
from django.contrib.admin.utils import model_ngettext
from django.core.serializers.json import DjangoJSONEncoder

logger = logging.getLogger(__name__)
User = get_user_model()


class PaymentAuditLog(models.Model):
    """
    Immutable audit log for all payment-related admin actions.
    
    Stores:
    - Who performed the action (admin user)
    - When the action occurred
    - What was changed (object ID, model name, fields)
    - Why it was changed (comment/reason)
    - Before/after values for sensitive fields
    """
    
    ACTION_CHOICES = (
        ('create', 'Created'),
        ('update', 'Updated'),
        ('delete', 'Deleted'),
        ('manual_review', 'Marked for Manual Review'),
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ('refund', 'Initiated Refund'),
        ('dispute', 'Marked as Disputed'),
    )
    
    # Who
    admin_user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='payment_audit_logs',
        help_text="Admin user who performed the action"
    )
    
    # When
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When the action occurred (UTC)"
    )
    
    # What
    content_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Model name (e.g., 'PaymentAttempt')"
    )
    object_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="ID of the object being modified"
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        db_index=True,
        help_text="Type of action performed"
    )
    
    # Why
    reason = models.TextField(
        blank=True,
        null=True,
        help_text="Reason/comment for the action (admin's explanation)"
    )
    
    # Changes
    changes = models.JSONField(
        default=dict,
        help_text="Dictionary of changed fields: {'field': {'old': value, 'new': value}}"
    )
    
    # Security
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        db_index=True,
        help_text="IP address of the admin"
    )
    user_agent = models.TextField(
        blank=True,
        null=True,
        help_text="Browser user agent string"
    )
    
    class Meta:
        db_table = 'payment_audit_log'
        indexes = [
            models.Index(fields=['admin_user', 'timestamp']),
            models.Index(fields=['object_id', 'content_type']),
            models.Index(fields=['action', 'timestamp']),
        ]
        verbose_name = 'Payment Audit Log'
        verbose_name_plural = 'Payment Audit Logs'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.get_action_display()} {self.content_type}#{self.object_id} by {self.admin_user} on {self.timestamp}"
    
    @classmethod
    def log_action(
        cls,
        admin_user,
        content_type,
        object_id,
        action,
        reason=None,
        changes=None,
        request=None
    ):
        """
        Create an audit log entry for an admin action.
        
        Args:
            admin_user: User who performed the action
            content_type: Model name (string)
            object_id: ID of the object being modified
            action: Action type (from ACTION_CHOICES)
            reason: Optional reason/comment
            changes: Optional dict of changed fields
            request: Optional HTTP request for IP/user agent
        
        Returns:
            PaymentAuditLog instance
        """
        try:
            ip_address = None
            user_agent = None
            
            if request:
                ip_address = _get_client_ip(request)
                user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
            
            log_entry = cls.objects.create(
                admin_user=admin_user,
                content_type=content_type,
                object_id=str(object_id),
                action=action,
                reason=reason,
                changes=changes or {},
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            logger.warning(
                f"AUDIT: {admin_user.username} {action} {content_type}#{object_id}",
                extra={
                    'ip': ip_address,
                    'reason': reason,
                    'admin': admin_user.id,
                }
            )
            
            return log_entry
            
        except Exception as e:
            logger.error(f"Failed to create audit log: {str(e)}")
            return None


def _get_client_ip(request):
    """Extract client IP from request (handles proxies)."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class PaymentAuditLogAdmin:
    """
    Admin interface for viewing payment audit logs (read-only).
    """
    
    list_display = (
        'timestamp',
        'admin_user',
        'action',
        'content_type',
        'object_id',
        'ip_address',
    )
    list_filter = (
        'action',
        'content_type',
        'timestamp',
        'admin_user',
    )
    search_fields = (
        'admin_user__username',
        'object_id',
        'reason',
        'ip_address',
    )
    readonly_fields = (
        'timestamp',
        'admin_user',
        'content_type',
        'object_id',
        'action',
        'reason',
        'changes',
        'ip_address',
        'user_agent',
    )
    
    def has_add_permission(self, request):
        # Audit logs are read-only (created automatically)
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Audit logs cannot be deleted (immutable)
        return False
    
    def has_change_permission(self, request, obj=None):
        # Audit logs cannot be modified
        return False


class AdminActionMiddleware:
    """
    Middleware to capture admin IP address for audit logging.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Store IP in request for use in audit logging
        request.client_ip = _get_client_ip(request)
        response = self.get_response(request)
        return response
