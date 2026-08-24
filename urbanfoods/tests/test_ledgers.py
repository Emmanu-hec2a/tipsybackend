from decimal import Decimal

from django.test import TestCase

from urbanfoods.ledger_service import FinancialLedgerService, LedgerConflict
from urbanfoods.models import LoyaltyLedger, User, WalletLedger


class FinancialLedgerServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ledger-user')
        self.user.wallet_balance = Decimal('100.00')
        self.user.loyalty_points = 1200
        self.user.save(update_fields=['wallet_balance', 'loyalty_points'])

    def test_wallet_debit_is_idempotent_and_never_negative(self):
        first = FinancialLedgerService.wallet_entry(
            self.user.id, WalletLedger.EntryType.DEBIT, '75', 'order', '1', 'wallet-1'
        )
        second = FinancialLedgerService.wallet_entry(
            self.user.id, WalletLedger.EntryType.DEBIT, '75', 'order', '1', 'wallet-1'
        )
        self.user.refresh_from_db()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.user.wallet_balance, Decimal('25.00'))
        with self.assertRaises(LedgerConflict):
            FinancialLedgerService.wallet_entry(
                self.user.id, WalletLedger.EntryType.DEBIT, '30', 'order', '2', 'wallet-2'
            )

    def test_loyalty_credit_is_idempotent(self):
        first = FinancialLedgerService.loyalty_entry(
            self.user.id, LoyaltyLedger.EntryType.CREDIT, 500, 'payment-1', 'loyalty-1'
        )
        second = FinancialLedgerService.loyalty_entry(
            self.user.id, LoyaltyLedger.EntryType.CREDIT, 500, 'payment-1', 'loyalty-1'
        )
        self.user.refresh_from_db()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.user.loyalty_points, 1700)

    def test_points_redemption_is_atomic(self):
        points, value, balance, remaining = FinancialLedgerService.redeem_points(self.user.id, 'redeem-1')
        self.assertEqual(points, 1200)
        self.assertEqual(value, Decimal('12'))
        self.assertEqual(balance, Decimal('112.00'))
        self.assertEqual(remaining, 0)
        self.assertEqual(WalletLedger.objects.count(), 1)
        self.assertEqual(LoyaltyLedger.objects.count(), 1)
