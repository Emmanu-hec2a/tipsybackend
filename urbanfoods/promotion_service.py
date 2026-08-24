from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Promotion


class PromotionReservationService:
    """Lock and reserve promotion usage inside the caller's order transaction."""

    @classmethod
    def reserve(cls, promotion_id, subtotal):
        with transaction.atomic():
            promotion = Promotion.objects.select_for_update().get(pk=promotion_id)
            now = timezone.now()
            if (
                not promotion.is_active
                or promotion.start_date > now
                or promotion.end_date < now
                or (promotion.usage_limit is not None and promotion.times_used >= promotion.usage_limit)
                or subtotal < promotion.min_order_amount
            ):
                return None, Decimal('0.00')

            if promotion.discount_percentage:
                discount = subtotal * (promotion.discount_percentage / Decimal('100'))
            elif promotion.discount_amount:
                discount = promotion.discount_amount
            else:
                discount = Decimal('0.00')

            discount = min(discount, subtotal).quantize(Decimal('0.01'))
            promotion.times_used += 1
            promotion.save(update_fields=['times_used'])
            return promotion, discount
