from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone

from urbanfoods.ledger_service import FinancialLedgerService, LedgerConflict
from urbanfoods.models import (
    LoyaltyLedger, Order, PaymentAttempt, ShirikiContribution, ShirikiSession,
    Store, User, WalletLedger,
)
from urbanfoods.payment_initiation import InitiatePaymentService
from urbanfoods.payment_service import ConfirmPaymentService


@skipUnless(connection.vendor == 'postgresql', 'Concurrency tests require PostgreSQL row-lock semantics.')
class PaymentConcurrencyTest(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(username='concurrency-user')
        self.store = Store.objects.create(owner=self.user, name='Concurrency Store')

    @staticmethod
    def _run_in_threads(function, count=2):
        def worker():
            close_old_connections()
            try:
                return function()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(lambda _: worker(), range(count)))

    def test_concurrent_duplicate_callbacks_create_one_financial_effect(self):
        order = Order.objects.create(
            user=self.user, store=self.store, phone_number='0712345678',
            subtotal=Decimal('100.00'), total=Decimal('100.00'),
            mpesa_checkout_request_id='ws_CO_concurrent_callback',
        )
        metadata = {
            'Amount': 1,
            'MpesaReceiptNumber': 'QCONCURRENT',
            'PhoneNumber': '254712345678',
        }
        with patch('urbanfoods.payment_service._enqueue_order_payment_tasks'):
            results = self._run_in_threads(lambda: ConfirmPaymentService.process_payment_signal(
                'ws_CO_concurrent_callback', 0, 'Success', metadata, source='concurrency_test'
            ))

        order.refresh_from_db()
        self.assertEqual(results, [True, True])
        self.assertEqual(PaymentAttempt.objects.filter(order=order).count(), 1)
        self.assertEqual(LoyaltyLedger.objects.filter(source_payment_id__isnull=False).count(), 1)
        self.assertEqual(order.payment_status, 'paid')

    def test_concurrent_same_idempotency_key_creates_one_attempt(self):
        order = Order.objects.create(
            user=self.user, store=self.store, phone_number='0712345678',
            subtotal=Decimal('100.00'), total=Decimal('100.00'),
        )
        with patch.object(InitiatePaymentService, 'enqueue'):
            results = self._run_in_threads(lambda: InitiatePaymentService.create_or_get_for_order(
                order, '0712345678', 'concurrent-idempotency-key'
            ))

        self.assertEqual(PaymentAttempt.objects.filter(order=order).count(), 1)
        self.assertEqual({result[0].pk for result in results}, {PaymentAttempt.objects.get(order=order).pk})

    def test_concurrent_wallet_debits_cannot_overdraw(self):
        self.user.wallet_balance = Decimal('100.00')
        self.user.save(update_fields=['wallet_balance'])

        def debit(suffix):
            try:
                entry = FinancialLedgerService.wallet_entry(
                    self.user.id, WalletLedger.EntryType.DEBIT, '75',
                    'concurrency_order', suffix, f'wallet-concurrency-{suffix}'
                )
                return ('ok', entry.pk)
            except LedgerConflict:
                return ('conflict', None)

        results = self._run_in_threads(lambda: debit('same'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('25.00'))
        self.assertEqual(WalletLedger.objects.filter(user=self.user, entry_type='debit').count(), 1)
        self.assertEqual(sorted(result[0] for result in results), ['conflict', 'ok'])

    def test_concurrent_shiriki_contributions_respect_remaining_capacity(self):
        order = Order.objects.create(
            user=self.user, store=self.store, phone_number='0712345678',
            subtotal=Decimal('100.00'), total=Decimal('100.00'),
        )
        session = ShirikiSession.objects.create(
            order=order, host=self.user, invite_code='CONCUR',
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        contributors = [User.objects.create_user(username=f'contributor-{i}') for i in range(2)]
        contributions = [ShirikiContribution.objects.create(
            session=session, user=user, amount=Decimal('75.00'),
            phone_number='0712345678', checkout_request_id=f'ws_CO_shiriki_{i}'
        ) for i, user in enumerate(contributors)]

        def confirm(contribution):
            return ConfirmPaymentService.process_payment_signal(
                contribution.checkout_request_id, 0, 'Success', {
                    'Amount': 75, 'MpesaReceiptNumber': f'QSHIRIKI{contribution.id}',
                    'PhoneNumber': '254712345678',
                }, source='concurrency_test'
            )

        with patch('urbanfoods.payment_service._enqueue_order_payment_tasks'):
            results = self._run_in_threads(lambda: confirm(contributions.pop()))

        self.assertEqual(results, [True, True])
        applied = list(ShirikiContribution.objects.filter(session=session).values_list('amount_applied_to_pot', flat=True))
        self.assertEqual(sum(applied), Decimal('100.00'))
        self.assertEqual(ShirikiContribution.objects.filter(session=session, wallet_credit_amount__gt=0).count(), 1)
