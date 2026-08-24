from decimal import Decimal

from django.db import transaction

from .models import LoyaltyLedger, User, WalletLedger


class LedgerConflict(Exception):
    pass


class FinancialLedgerService:
    """Locked, idempotent mutations for materialized wallet and loyalty balances."""

    @staticmethod
    def wallet_entry(user_id, entry_type, amount, reference_type, reference_id, idempotency_key):
        amount = Decimal(str(amount)).quantize(Decimal('0.01'))
        if amount <= 0:
            raise ValueError('Wallet amount must be positive.')
        with transaction.atomic():
            existing = WalletLedger.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing
            user = User.objects.select_for_update().get(pk=user_id)
            before = user.wallet_balance
            signed_amount = -amount if entry_type == WalletLedger.EntryType.DEBIT else amount
            after = before + signed_amount
            if after < 0:
                raise LedgerConflict('Insufficient wallet balance.')
            user.wallet_balance = after
            user.save(update_fields=['wallet_balance'])
            return WalletLedger.objects.create(
                user=user, entry_type=entry_type, amount=amount,
                reference_type=reference_type, reference_id=str(reference_id),
                idempotency_key=idempotency_key,
                balance_before=before, balance_after=after,
            )

    @staticmethod
    def loyalty_entry(user_id, entry_type, points, source_payment_id, idempotency_key):
        points = int(points)
        if points <= 0:
            raise ValueError('Loyalty points must be positive.')
        with transaction.atomic():
            existing = LoyaltyLedger.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing
            user = User.objects.select_for_update().get(pk=user_id)
            signed_points = -points if entry_type == LoyaltyLedger.EntryType.DEBIT else points
            if user.loyalty_points + signed_points < 0:
                raise LedgerConflict('Insufficient loyalty points.')
            user.loyalty_points += signed_points
            user.save(update_fields=['loyalty_points'])
            return LoyaltyLedger.objects.create(
                user=user, entry_type=entry_type, points=points,
                source_payment_id=str(source_payment_id or ''), idempotency_key=idempotency_key,
            )

    @staticmethod
    def redeem_points(user_id, idempotency_key):
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user_id)
            points = user.loyalty_points
            if points < 1000:
                raise LedgerConflict('Minimum 1,000 points required for redemption.')
            redeem_value = Decimal(points) / Decimal('100')
            FinancialLedgerService.loyalty_entry(
                user_id, LoyaltyLedger.EntryType.DEBIT, points,
                user_id, f'{idempotency_key}:points',
            )
            FinancialLedgerService.wallet_entry(
                user_id, WalletLedger.EntryType.CREDIT, redeem_value,
                'points_redemption', user_id, f'{idempotency_key}:wallet',
            )
            user.refresh_from_db()
            return points, redeem_value, user.wallet_balance, user.loyalty_points
