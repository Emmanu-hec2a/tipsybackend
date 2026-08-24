from decimal import Decimal

from django.test import TestCase

from urbanfoods.inventory_service import InventoryConflict, InventoryReservationService
from urbanfoods.models import FoodItem, InventoryReservation, Order, Store, User


class InventoryReservationServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='inventory-user')
        self.store = Store.objects.create(owner=self.user, name='Inventory Store')
        self.product = FoodItem.objects.create(
            store=self.store,
            name='Test Bottle',
            price=Decimal('100.00'),
            stock=5,
            image='test.jpg',
        )
        self.order = Order.objects.create(
            user=self.user,
            store=self.store,
            phone_number='0712345678',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
        )

    def test_reservation_decrements_stock_atomically(self):
        InventoryReservationService.reserve_order(self.order, [(self.product.id, 3)])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)
        self.assertEqual(
            InventoryReservation.objects.get(order=self.order).status,
            InventoryReservation.Status.RESERVED,
        )

    def test_failed_reservation_rolls_back_all_items(self):
        second = FoodItem.objects.create(
            store=self.store, name='Second Bottle', price=Decimal('50.00'),
            stock=1, image='second.jpg',
        )
        with self.assertRaises(InventoryConflict):
            InventoryReservationService.reserve_order(
                self.order, [(self.product.id, 3), (second.id, 2)]
            )
        self.product.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertEqual(second.stock, 1)
        self.assertFalse(InventoryReservation.objects.filter(order=self.order).exists())

    def test_release_is_idempotent(self):
        InventoryReservationService.reserve_order(self.order, [(self.product.id, 3)])
        self.assertEqual(InventoryReservationService.release_order(self.order.id), 1)
        self.assertEqual(InventoryReservationService.release_order(self.order.id), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertEqual(
            InventoryReservation.objects.get(order=self.order).status,
            InventoryReservation.Status.RELEASED,
        )

    def test_finalize_does_not_deduct_stock_again(self):
        InventoryReservationService.reserve_order(self.order, [(self.product.id, 3)])
        self.order.status = 'delivered'
        self.order.save(update_fields=['status'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)
        self.assertEqual(self.product.times_ordered, 3)
        self.assertEqual(
            InventoryReservation.objects.get(order=self.order).status,
            InventoryReservation.Status.FINALIZED,
        )
