from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from urbanfoods.models import Order, Store, User
from urbanfoods.order_idempotency import order_request_fingerprint, validate_idempotency_key


class OrderIdempotencyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='order-idempotency-user')
        self.store = Store.objects.create(owner=self.user, name='Idempotency Store')

    def test_same_economic_payload_has_same_fingerprint(self):
        first = {
            'items': [{'product_id': 2, 'quantity': 1}, {'product_id': 1, 'quantity': 2}],
            'promo_code': 'save10', 'payment_method': 'mpesa', 'use_wallet': False,
        }
        second = {
            'items': [{'product_id': 1, 'quantity': 2}, {'product_id': 2, 'quantity': 1}],
            'promo_code': 'SAVE10', 'payment_method': 'MPESA', 'use_wallet': False,
        }
        self.assertEqual(order_request_fingerprint(first), order_request_fingerprint(second))

    def test_different_payload_has_different_fingerprint(self):
        base = {'items': [{'product_id': 1, 'quantity': 1}]}
        changed = {'items': [{'product_id': 1, 'quantity': 2}]}
        self.assertNotEqual(order_request_fingerprint(base), order_request_fingerprint(changed))

    def test_key_is_bounded_and_unique_at_database_layer(self):
        validate_idempotency_key('a' * 128)
        with self.assertRaises(ValueError):
            validate_idempotency_key('a' * 129)

        Order.objects.create(
            user=self.user, store=self.store, phone_number='0712345678',
            subtotal=Decimal('10.00'), total=Decimal('10.00'),
            payment_idempotency_key='order-key',
        )
        with self.assertRaises(IntegrityError):
            Order.objects.create(
                user=self.user, store=self.store, phone_number='0712345678',
                subtotal=Decimal('10.00'), total=Decimal('10.00'),
                payment_idempotency_key='order-key',
            )
