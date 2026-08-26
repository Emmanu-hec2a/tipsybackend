#!/usr/bin/env python
"""
Diagnostic Script: Why is STK Not Being Sent?
Order #111 Analysis - 2026-08-26 13:37 UTC
"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from urbanfoods.models import Order, PaymentAttempt
from django.db.models import Q

order_id = 111
order = Order.objects.get(id=order_id)

print("=" * 80)
print(f"ORDER #{order_id} DIAGNOSTIC")
print("=" * 80)

print(f"\n📋 ORDER DETAILS:")
print(f"  Order Number: {order.order_number}")
print(f"  User: {order.user.username} (ID: {order.user.id})")
print(f"  Store: {order.store.name}")
print(f"  Created: {order.created_at}")
print(f"  Status: {order.status}")
print(f"  Payment Method: {order.payment_method}")

print(f"\n💰 FINANCIAL DETAILS:")
print(f"  Subtotal: {order.subtotal} KES")
print(f"  Delivery Fee: {order.delivery_fee} KES")
print(f"  Discount: {order.discount_amount} KES")
print(f"  Wallet Used: {order.wallet_used} KES")
print(f"  Total: {order.total} KES")
print(f"  Payment Status: {order.payment_status}")

print(f"\n📱 M-PESA DETAILS:")
print(f"  Payment Method: {order.payment_method}")
print(f"  Checkout Request ID: {order.mpesa_checkout_request_id}")
print(f"  Receipt Number: {order.mpesa_receipt_number}")
print(f"  Payment Completed At: {order.payment_completed_at}")

print(f"\n🎟️ WALLET DETAILS:")
print(f"  Wallet Used: {order.wallet_used} KES")
print(f"  User Wallet Balance (current): {order.user.wallet_balance} KES")

print(f"\n❓ ANALYSIS:")

# Check 1: Is wallet the issue?
if order.wallet_used > 0 and order.total == 0:
    print(f"  ✅ Wallet covered entire cost (used {order.wallet_used} KES)")
    print(f"  ⚠️  Payment Status is '{order.payment_status}' but should be 'paid'")
    if order.payment_status != 'paid':
        print(f"  🔴 BUG: Order not auto-marked as paid when wallet covered all!")
elif order.wallet_used > 0 and order.total > 0:
    print(f"  ✅ Partial wallet used ({order.wallet_used} KES), needs M-Pesa for {order.total} KES")
else:
    print(f"  ✅ No wallet used, full {order.total} KES needs M-Pesa payment")

# Check 2: Is total correct?
if order.total > 0 and order.payment_method == 'mpesa':
    print(f"\n  ✅ Total is {order.total} KES and payment method is M-Pesa")
    print(f"  → STK Push SHOULD have been initiated")
else:
    print(f"\n  ⚠️  Total is {order.total} KES or payment method is '{order.payment_method}'")
    print(f"  → STK Push should NOT be initiated (correct!)")

# Check 3: Payment attempts
payment_attempts = PaymentAttempt.objects.filter(order=order)
print(f"\n🔍 PAYMENT ATTEMPTS: {payment_attempts.count()}")
for i, attempt in enumerate(payment_attempts, 1):
    print(f"  #{i} ID: {attempt.public_payment_id}")
    print(f"     Status: {attempt.status}")
    print(f"     Checkout Request ID: {attempt.checkout_request_id}")
    print(f"     Created: {attempt.created_at}")
    if attempt.error_response:
        print(f"     Error: {attempt.error_response}")

if not payment_attempts.exists() and order.total > 0 and order.payment_method == 'mpesa':
    print(f"  🔴 BUG: No payment attempts created despite needing STK push!")
    print(f"  → Likely cause: InitiatePaymentService.create_or_get_for_order() failed")
    print(f"  → Check backend logs for exceptions around order creation time")

# Check 4: Order status
print(f"\n📊 ORDER STATUS: {order.status}")
if order.status in ('payment_pending', 'payment_failed'):
    print(f"  → App correctly knows payment is pending")
    print(f"  → Should be polling /orders/{order_id}/payment-status/")
    print(f"  → Rate limit (30/hour) being hit by continuous polling")

print(f"\n🔧 RECOMMENDATIONS:")
print(f"  1. Check if wallet should have auto-paid: wallet_used={order.wallet_used}, total={order.total}")
print(f"  2. Check if STK should have been sent: total={order.total}, payment_method={order.payment_method}")
print(f"  3. Review server logs at order creation time ({order.created_at})")
print(f"  4. Check payment_initiation.py InitiatePaymentService for failures")
print(f"  5. Implement exponential backoff in Flutter app (currently constant 4-5s polling)")

print(f"\n" + "=" * 80)
