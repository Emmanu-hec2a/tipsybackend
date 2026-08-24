from decimal import Decimal

from django.db import migrations


def create_opening_balances(apps, schema_editor):
    User = apps.get_model('urbanfoods', 'User')
    WalletLedger = apps.get_model('urbanfoods', 'WalletLedger')
    LoyaltyLedger = apps.get_model('urbanfoods', 'LoyaltyLedger')

    for user in User.objects.all().iterator():
        if user.wallet_balance and user.wallet_balance > 0:
            WalletLedger.objects.create(
                user_id=user.pk,
                entry_type='credit',
                amount=user.wallet_balance,
                reference_type='opening_balance',
                reference_id=str(user.pk),
                idempotency_key=f'opening-wallet-{user.pk}',
                balance_before=Decimal('0.00'),
                balance_after=user.wallet_balance,
            )
        if user.loyalty_points and user.loyalty_points > 0:
            LoyaltyLedger.objects.create(
                user_id=user.pk,
                entry_type='credit',
                points=user.loyalty_points,
                source_payment_id='opening_balance',
                idempotency_key=f'opening-loyalty-{user.pk}',
            )


class Migration(migrations.Migration):
    dependencies = [('urbanfoods', '0064_loyaltyledger_walletledger')]
    operations = [migrations.RunPython(create_opening_balances, migrations.RunPython.noop)]
