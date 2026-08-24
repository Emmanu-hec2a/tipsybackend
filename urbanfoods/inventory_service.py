from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import FoodItem, InventoryReservation


class InventoryConflict(Exception):
    """Raised when requested stock cannot be reserved atomically."""


class InventoryReservationService:
    """Atomic, idempotent inventory reserve/release/finalize operations."""

    @classmethod
    def reserve_order(cls, order, item_requests):
        """Reserve all requested items or raise without leaving partial stock."""
        aggregated = {}
        for food_item_id, quantity in item_requests:
            food_item_id = int(food_item_id)
            aggregated[food_item_id] = aggregated.get(food_item_id, 0) + int(quantity)
        normalized = sorted(aggregated.items(), key=lambda item: item[0])
        if not normalized or any(quantity <= 0 for _, quantity in normalized):
            raise InventoryConflict('Order contains an invalid quantity.')

        with transaction.atomic():
            for food_item_id, quantity in normalized:
                food_item = FoodItem.objects.select_for_update().get(pk=food_item_id)
                if not food_item.is_active or not food_item.is_available or food_item.stock < quantity:
                    raise InventoryConflict(f'{food_item.name} is out of stock.')

                FoodItem.objects.filter(pk=food_item.pk).update(stock=F('stock') - quantity)
                InventoryReservation.objects.create(
                    order=order,
                    food_item=food_item,
                    quantity=quantity,
                    status=InventoryReservation.Status.RESERVED,
                )

    @classmethod
    def release_order(cls, order_id):
        """Return reserved stock once; repeated calls are harmless."""
        with transaction.atomic():
            reservations = list(InventoryReservation.objects.select_for_update().filter(
                order_id=order_id,
                status=InventoryReservation.Status.RESERVED,
            ).order_by('food_item_id'))
            for reservation in reservations:
                food_item = FoodItem.objects.select_for_update().get(pk=reservation.food_item_id)
                FoodItem.objects.filter(pk=food_item.pk).update(stock=F('stock') + reservation.quantity)
                reservation.status = InventoryReservation.Status.RELEASED
                reservation.released_at = timezone.now()
                reservation.save(update_fields=['status', 'released_at'])
        return len(reservations)

    @classmethod
    def finalize_order(cls, order_id):
        """Finalize reservations after delivery without changing stock."""
        with transaction.atomic():
            reservations = list(InventoryReservation.objects.select_for_update().filter(
                order_id=order_id,
                status=InventoryReservation.Status.RESERVED,
            ).order_by('food_item_id'))
            for reservation in reservations:
                reservation.status = InventoryReservation.Status.FINALIZED
                reservation.finalized_at = timezone.now()
                reservation.save(update_fields=['status', 'finalized_at'])
                FoodItem.objects.filter(pk=reservation.food_item_id).update(
                    times_ordered=F('times_ordered') + reservation.quantity
                )
        return len(reservations)
