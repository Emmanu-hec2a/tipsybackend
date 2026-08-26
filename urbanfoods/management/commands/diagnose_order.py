"""
Django Management Command: Diagnose Order Payment Issues
Usage: python manage.py diagnose_order [order_id]
"""

from django.core.management.base import BaseCommand
from urbanfoods.models import Order, PaymentAttempt
from django.db.models import Q


class Command(BaseCommand):
    help = 'Diagnose why an order payment is stuck (e.g., no STK sent, rate limiting)'

    def add_arguments(self, parser):
        parser.add_argument(
            'order_id',
            type=int,
            help='Order ID to diagnose'
        )

    def handle(self, *args, **options):
        order_id = options['order_id']
        
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'❌ Order #{order_id} not found'))
            return

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS(f"ORDER #{order_id} DIAGNOSTIC"))
        self.stdout.write("=" * 80)

        self.stdout.write(f"\n📋 ORDER DETAILS:")
        self.stdout.write(f"  Order Number: {order.order_number}")
        self.stdout.write(f"  User: {order.user.username} (ID: {order.user.id})")
        self.stdout.write(f"  Store: {order.store.name}")
        self.stdout.write(f"  Created: {order.created_at}")
        self.stdout.write(f"  Status: {order.status}")
        self.stdout.write(f"  Payment Method: {order.payment_method}")

        self.stdout.write(f"\n💰 FINANCIAL DETAILS:")
        self.stdout.write(f"  Subtotal: {order.subtotal} KES")
        self.stdout.write(f"  Delivery Fee: {order.delivery_fee} KES")
        self.stdout.write(f"  Discount: {order.discount_amount} KES")
        self.stdout.write(f"  Wallet Used: {order.wallet_used} KES")
        self.stdout.write(f"  Total: {order.total} KES")
        self.stdout.write(f"  Payment Status: {order.payment_status}")

        self.stdout.write(f"\n📱 M-PESA DETAILS:")
        self.stdout.write(f"  Payment Method: {order.payment_method}")
        self.stdout.write(f"  Checkout Request ID: {order.mpesa_checkout_request_id}")
        self.stdout.write(f"  Receipt Number: {order.mpesa_receipt_number}")
        self.stdout.write(f"  Payment Completed At: {order.payment_completed_at}")

        self.stdout.write(f"\n👛 WALLET DETAILS:")
        self.stdout.write(f"  Wallet Used: {order.wallet_used} KES")
        self.stdout.write(f"  User Wallet Balance (current): {order.user.wallet_balance} KES")

        self.stdout.write(f"\n❓ ANALYSIS:")

        # Check 1: Is wallet the issue?
        if order.wallet_used > 0 and order.total == 0:
            self.stdout.write(self.style.SUCCESS(f"  ✅ Wallet covered entire cost (used {order.wallet_used} KES)"))
            if order.payment_status != 'paid':
                self.stdout.write(self.style.WARNING(f"  ⚠️  Payment Status is '{order.payment_status}' but should be 'paid'"))
                self.stdout.write(self.style.ERROR(f"  🔴 BUG: Order not auto-marked as paid when wallet covered all!"))
        elif order.wallet_used > 0 and order.total > 0:
            self.stdout.write(self.style.SUCCESS(f"  ✅ Partial wallet used ({order.wallet_used} KES), needs M-Pesa for {order.total} KES"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  ✅ No wallet used, full {order.total} KES needs M-Pesa payment"))

        # Check 2: Is total correct?
        if order.total > 0 and order.payment_method == 'mpesa':
            self.stdout.write(f"\n  ✅ Total is {order.total} KES and payment method is M-Pesa")
            self.stdout.write(f"  → STK Push SHOULD have been initiated")
        else:
            self.stdout.write(f"\n  ⚠️  Total is {order.total} KES or payment method is '{order.payment_method}'")
            self.stdout.write(f"  → STK Push should NOT be initiated (correct!)")

        # Check 3: Payment attempts
        payment_attempts = PaymentAttempt.objects.filter(order=order)
        self.stdout.write(f"\n🔍 PAYMENT ATTEMPTS: {payment_attempts.count()}")
        for i, attempt in enumerate(payment_attempts, 1):
            self.stdout.write(f"  #{i} ID: {attempt.public_payment_id}")
            self.stdout.write(f"     Status: {attempt.status}")
            self.stdout.write(f"     Checkout Request ID: {attempt.checkout_request_id}")
            self.stdout.write(f"     Created: {attempt.created_at}")
            if attempt.error_response:
                self.stdout.write(f"     Error: {attempt.error_response}")

        if not payment_attempts.exists() and order.total > 0 and order.payment_method == 'mpesa':
            self.stdout.write(self.style.ERROR(f"  🔴 BUG: No payment attempts created despite needing STK push!"))
            self.stdout.write(f"  → Likely cause: InitiatePaymentService.create_or_get_for_order() failed")
            self.stdout.write(f"  → Check backend logs for exceptions around order creation time")

        # Check 4: Order status
        self.stdout.write(f"\n📊 ORDER STATUS: {order.status}")
        if order.status in ('payment_pending', 'payment_failed'):
            self.stdout.write(f"  → App correctly knows payment is pending")
            self.stdout.write(f"  → Should be polling /orders/{order_id}/payment-status/")
            self.stdout.write(f"  → Rate limit (30/hour) being hit by continuous polling")

        self.stdout.write(f"\n🔧 RECOMMENDATIONS:")
        self.stdout.write(f"  1. Check if wallet should have auto-paid: wallet_used={order.wallet_used}, total={order.total}")
        self.stdout.write(f"  2. Check if STK should have been sent: total={order.total}, payment_method={order.payment_method}")
        self.stdout.write(f"  3. Review server logs at order creation time ({order.created_at})")
        self.stdout.write(f"  4. Check payment_initiation.py InitiatePaymentService for failures")
        self.stdout.write(f"  5. Implement exponential backoff in Flutter app (currently constant 4-5s polling)")

        self.stdout.write("\n" + "=" * 80)
