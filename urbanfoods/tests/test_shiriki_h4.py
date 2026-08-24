from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from urbanfoods.models import Order, ShirikiContribution, ShirikiSession, Store, User
from urbanfoods.shiriki_service import (
    ShirikiCapacityConflict,
    ShirikiService,
    ShirikiSessionConflict,
)


class ShirikiHardeningTest(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(username='h4-host')
        self.contributor = User.objects.create_user(username='h4-contributor')
        self.store = Store.objects.create(owner=self.host, name='H4 Store')
        self.order = Order.objects.create(
            user=self.host, store=self.store, phone_number='0712345678',
            subtotal=Decimal('100.00'), total=Decimal('100.00'),
        )
        self.session = ShirikiSession.objects.create(
            order=self.order, host=self.host, invite_code='TT-H4TEST',
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )

    def test_old_pending_contribution_still_reserves_capacity(self):
        contribution = ShirikiService.reserve_contribution(
            self.session.invite_code, self.contributor.id, Decimal('80.00'),
            '0712345678', 'h4-old-pending',
        )
        ShirikiContribution.objects.filter(pk=contribution.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=10)
        )

        with self.assertRaises(ShirikiCapacityConflict):
            ShirikiService.reserve_contribution(
                self.session.invite_code, self.host.id, Decimal('30.00'),
                '0712345678', 'h4-over-allocation',
            )

    def test_duplicate_contribution_key_returns_one_reservation(self):
        first = ShirikiService.reserve_contribution(
            self.session.invite_code, self.contributor.id, Decimal('20.00'),
            '0712345678', 'h4-retry',
        )
        second = ShirikiService.reserve_contribution(
            self.session.invite_code, self.contributor.id, Decimal('20.00'),
            '0712345678', 'h4-retry',
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ShirikiContribution.objects.filter(session=self.session).count(), 1)

    def test_session_creation_is_one_to_one_and_bounded_code_retry(self):
        order = Order.objects.create(
            user=self.host, store=self.store, phone_number='0712345678',
            subtotal=Decimal('100.00'), total=Decimal('100.00'),
        )
        ShirikiSession.objects.create(
            order=order, host=self.host, invite_code='TT-AAAAAA',
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        second_order = Order.objects.create(
            user=self.host, store=self.store, phone_number='0712345678',
            subtotal=Decimal('100.00'), total=Decimal('100.00'),
        )
        with patch('urbanfoods.shiriki_service.random.choices', side_effect=[
            list('AAAAAA'), list('AAAAAA'), list('BBBBBB')
        ]):
            created = ShirikiService.create_session(second_order.id, self.host.id)
        self.assertEqual(created.invite_code, 'TT-BBBBBB')
        with self.assertRaises(ShirikiSessionConflict):
            ShirikiService.create_session(second_order.id, self.host.id)

    def test_pending_contribution_limit_is_enforced(self):
        for index in range(ShirikiService.MAX_ACTIVE_PENDING_CONTRIBUTIONS):
            user = User.objects.create_user(username=f'h4-pending-{index}')
            ShirikiContribution.objects.create(
                session=self.session, user=user, amount=Decimal('1.00'),
                phone_number='0712345678', status='pending',
            )
        with self.assertRaises(ShirikiCapacityConflict):
            ShirikiService.reserve_contribution(
                self.session.invite_code, self.contributor.id, Decimal('1.00'),
                '0712345678', 'h4-limit',
            )
