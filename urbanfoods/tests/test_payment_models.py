from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from urbanfoods.models import (
    CallbackInbox,
    Order,
    PaymentAttempt,
    Store,
    User,
)


class PaymentModelConstraintsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='payment-model-user')
        self.store = Store.objects.create(owner=self.user, name='Payment Model Store')
        self.order = Order.objects.create(
            user=self.user,
            store=self.store,
            phone_number='0712345678',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
        )

    def test_payment_attempt_requires_exactly_one_business_target(self):
        PaymentAttempt.objects.create(
            payment_type=PaymentAttempt.PaymentType.ORDER,
            order=self.order,
            expected_amount=Decimal('100.00'),
        )

        with self.assertRaises(IntegrityError):
            PaymentAttempt.objects.create(
                payment_type=PaymentAttempt.PaymentType.ORDER,
                expected_amount=Decimal('100.00'),
            )

    def test_payment_attempt_rejects_non_positive_expected_amount(self):
        with self.assertRaises(IntegrityError):
            PaymentAttempt.objects.create(
                payment_type=PaymentAttempt.PaymentType.ORDER,
                order=self.order,
                expected_amount=Decimal('0.00'),
            )

    def test_checkout_and_receipt_are_unique_per_provider(self):
        PaymentAttempt.objects.create(
            payment_type=PaymentAttempt.PaymentType.ORDER,
            order=self.order,
            expected_amount=Decimal('100.00'),
            checkout_request_id='ws_CO_unique_1',
            provider_receipt='receipt_unique_1',
        )

        second_order = Order.objects.create(
            user=self.user,
            store=self.store,
            phone_number='0712345678',
            subtotal=Decimal('200.00'),
            total=Decimal('200.00'),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment_type=PaymentAttempt.PaymentType.ORDER,
                    order=second_order,
                    expected_amount=Decimal('200.00'),
                    checkout_request_id='ws_CO_unique_1',
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentAttempt.objects.create(
                    payment_type=PaymentAttempt.PaymentType.ORDER,
                    order=second_order,
                    expected_amount=Decimal('200.00'),
                    checkout_request_id='ws_CO_unique_2',
                    provider_receipt='receipt_unique_1',
                )

    def test_callback_event_hash_is_deduplicated(self):
        CallbackInbox.objects.create(
            event_hash='a' * 64,
            checkout_request_id='ws_CO_callback_1',
            raw_payload={'Body': {'stkCallback': {}}},
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CallbackInbox.objects.create(
                    event_hash='a' * 64,
                    checkout_request_id='ws_CO_callback_1',
                    raw_payload={'Body': {'stkCallback': {}}},
                )
