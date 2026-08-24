import random
import string
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Order, ShirikiContribution, ShirikiSession


class ShirikiCapacityConflict(Exception):
    """The requested contribution cannot be reserved safely."""


class ShirikiSessionConflict(Exception):
    """The order already has a session or a code cannot be allocated."""


class ShirikiService:
    MAX_ACTIVE_PENDING_CONTRIBUTIONS = 50
    INVITE_CODE_ATTEMPTS = 8

    @classmethod
    def create_session(cls, order_id, host_id):
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                pk=order_id, user_id=host_id, payment_status='pending'
            )
            if ShirikiSession.objects.filter(order_id=order.pk).exists():
                raise ShirikiSessionConflict('Shiriki session already exists for this order')
            for _ in range(cls.INVITE_CODE_ATTEMPTS):
                code = 'TT-' + ''.join(
                    random.choices(string.ascii_uppercase + string.digits, k=6)
                )
                try:
                    with transaction.atomic():
                        return ShirikiSession.objects.create(
                            order=order,
                            host_id=host_id,
                            invite_code=code,
                            expires_at=timezone.now() + timezone.timedelta(minutes=30),
                        )
                except IntegrityError:
                    continue
        raise ShirikiSessionConflict('Could not allocate a unique Shiriki invite code')

    @classmethod
    def reserve_contribution(cls, session_code, user_id, amount, phone, idempotency_key=None):
        with transaction.atomic():
            try:
                session = ShirikiSession.objects.select_for_update().select_related('order').get(
                    invite_code=session_code, status='active'
                )
            except ShirikiSession.DoesNotExist:
                raise ShirikiCapacityConflict('Active session not found')
            if session.expires_at <= timezone.now():
                raise ShirikiCapacityConflict('Shiriki session has expired')
            if idempotency_key:
                existing = ShirikiContribution.objects.filter(
                    payment_idempotency_key=idempotency_key
                ).first()
                if existing:
                    if existing.user_id == user_id:
                        return existing
                    raise ShirikiCapacityConflict('Idempotency key is already used')

            pending = session.contributions.filter(status='pending')
            if pending.count() >= cls.MAX_ACTIVE_PENDING_CONTRIBUTIONS:
                raise ShirikiCapacityConflict('This Shiriki pot has reached its pending payment limit')
            confirmed_sum = session.contributions.filter(status='confirmed').aggregate(
                total=Sum('amount_applied_to_pot')
            )['total'] or Decimal('0')
            pending_sum = pending.aggregate(total=Sum('amount'))['total'] or Decimal('0')
            remaining = session.order.total - confirmed_sum - pending_sum
            if amount > remaining + Decimal('0.01'):
                raise ShirikiCapacityConflict(
                    f'Amount exceeds remaining available balance of {max(0, float(remaining))}'
                )
            try:
                with transaction.atomic():
                    return ShirikiContribution.objects.create(
                        session=session, user_id=user_id, amount=amount,
                        phone_number=phone, payment_idempotency_key=idempotency_key,
                        status='pending',
                    )
            except IntegrityError:
                raise
