from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from urbanfoods.models import Order, Promotion, PromotionRedemption, Store, User
from urbanfoods.promotion_service import PromotionReservationService


class PromotionReservationServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='promotion-user')
        self.store = Store.objects.create(owner=self.user, name='Promotion Store')
        self.promotion = Promotion.objects.create(
            store=self.store,
            title='Limited offer',
            code='LIMITED',
            discount_percentage=Decimal('10.00'),
            min_order_amount=Decimal('50.00'),
            usage_limit=2,
            end_date=timezone.now() + timedelta(days=1),
        )

    def test_usage_limit_is_enforced_while_locked(self):
        first, first_discount = PromotionReservationService.reserve(
            self.promotion.id, Decimal('100.00')
        )
        second, second_discount = PromotionReservationService.reserve(
            self.promotion.id, Decimal('100.00')
        )
        third, third_discount = PromotionReservationService.reserve(
            self.promotion.id, Decimal('100.00')
        )

        self.assertEqual(first.id, self.promotion.id)
        self.assertEqual(first_discount, Decimal('10.00'))
        self.assertEqual(second.id, self.promotion.id)
        self.assertEqual(second_discount, Decimal('10.00'))
        self.assertIsNone(third)
        self.assertEqual(third_discount, Decimal('0.00'))
        self.promotion.refresh_from_db()
        self.assertEqual(self.promotion.times_used, 2)

    def test_below_minimum_does_not_consume_usage(self):
        promotion, discount = PromotionReservationService.reserve(
            self.promotion.id, Decimal('20.00')
        )
        self.assertIsNone(promotion)
        self.assertEqual(discount, Decimal('0.00'))
        self.promotion.refresh_from_db()
        self.assertEqual(self.promotion.times_used, 0)

    def test_redemption_is_unique_per_order(self):
        order = Order.objects.create(
            user=self.user, store=self.store, phone_number='0712345678',
            subtotal=Decimal('100.00'), total=Decimal('90.00'),
        )
        promotion, discount = PromotionReservationService.reserve(
            self.promotion.id, Decimal('100.00')
        )
        PromotionRedemption.objects.create(
            promotion=promotion, order=order, code=promotion.code,
            discount_amount=discount,
        )
        with self.assertRaises(Exception):
            PromotionRedemption.objects.create(
                promotion=promotion, order=order, code=promotion.code,
                discount_amount=discount,
            )
