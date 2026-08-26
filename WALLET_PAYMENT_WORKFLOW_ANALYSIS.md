# Wallet Payment Workflow Analysis
## "What happens when wallet covers entire order cost?"

**Date:** 2026-08-26  
**Status:** ✅ **WORKS CORRECTLY**

---

## Complete Flow

### 1️⃣ Flutter Frontend (checkout_screen.dart)

```dart
// Line 139-144: Calculate remaining amount after wallet
final double totalAmount = _useWallet
    ? (cart.total - userProvider.user!.walletBalance).clamp(0, double.infinity)
    : cart.total;

// Example: cart.total = 500 KES, wallet = 500 KES
// Result: totalAmount = 0 (clamped to min 0)
```

**Sends to backend:**
```dart
data: {
  'items': [...],
  'use_wallet': true,           // ✅ Flag wallet usage
  'payment_method': 'mpesa',    // Still set to mpesa
  'mpesa_phone': '254712345678',
  // Note: totalAmount NOT sent (backend calculates own source of truth)
}
```

---

### 2️⃣ Django Backend (api_v1_customer_views.py:810-880)

**Wallet Deduction Logic:**
```python
# Lines 820-832: Deduct wallet from order total
if data.get('use_wallet') and available_wallet > 0:
    if available_wallet >= total:
        wallet_used = total
        total = 0  # ✅ Zero if wallet covers all
    else:
        wallet_used = available_wallet
        total = total - wallet_used
    
    # Record wallet ledger entry
    FinancialLedgerService.wallet_entry(
        user.id, WalletLedger.EntryType.DEBIT, wallet_used,
        'order_wallet_debit', request_key or uuid.uuid4(),
        ...
    )
```

**Order Creation:**
```python
# Lines 857-864: Create order with correct status
order = Order.objects.create(
    ...
    total=total,  # 0 if wallet covered all
    wallet_used=wallet_used,
    payment_status='paid' if total == 0 else 'pending',  # ✅ Auto-set to 'paid'
    status='pending',  # Not 'payment_pending' since no payment needed
    ...
)
```

**Payment Initiation:**
```python
# Lines 901-902: Only initiate STK if amount > 0
if order.payment_method == 'mpesa' and order.total > 0 and not is_shiriki:
    # ✅ SKIPPED when total = 0
    logger.info(f"Queuing STK Push Task for Order {order.order_number}")
    attempt, _ = InitiatePaymentService.create_or_get_for_order(...)
```

**Response to Flutter:**
```python
# No payment_id, checkout_request_id, or is_async fields
# Order returns with payment_status='paid'
```

---

### 3️⃣ Flutter Frontend - Response Handling (checkout_screen.dart:220-260)

```dart
// Line 221: Check if M-Pesa payment needed
if (_selectedPaymentMethod == 'mpesa' && totalAmount > 0) {
    // ✅ SKIPPED when totalAmount = 0
    // Would navigate to PaymentPendingScreen
}

// Line 258: Final fallback for wallet-only orders
cart.clearCart();
Navigator.pushReplacement(
    context,
    MaterialPageRoute(
        builder: (_) => OrderTrackingScreen(orderId: orderId),  // ✅ Direct to tracking
    ),
);
```

---

## ✅ What Works

| Step | Status | Details |
|------|--------|---------|
| **Wallet Deduction** | ✅ | Backend correctly subtracts wallet from total |
| **Total = 0** | ✅ | `total` becomes 0 when wallet covers all |
| **Payment Status** | ✅ | Order automatically set to `payment_status='paid'` |
| **Ledger Entry** | ✅ | Wallet debit is recorded in financial ledger |
| **STK Push** | ✅ | NOT initiated (correct, since total=0) |
| **Frontend Logic** | ✅ | Flutter checks `totalAmount > 0` before payment |
| **Order Navigation** | ✅ | Goes to OrderTrackingScreen (not PaymentPendingScreen) |
| **User Experience** | ✅ | Order completes immediately, no M-Pesa prompt |

---

## 🎯 Test Scenario

**Setup:**
- Cart total: 500 KES
- Wallet balance: 500 KES
- Payment method: M-Pesa

**Expected Result:**
- ✅ Order created with `total=0`
- ✅ Order created with `payment_status='paid'`
- ✅ Wallet debited 500 KES
- ✅ User sees order in OrderTrackingScreen immediately
- ✅ No M-Pesa prompt appears

---

## 🛡️ Edge Cases Handled

### Case 1: Partial Wallet
```
Cart: 1000 KES | Wallet: 600 KES
→ totalAmount = 400 KES (needs M-Pesa)
→ Backend: total=400, wallet_used=600, payment_status='pending'
→ STK push initiated ✅
```

### Case 2: Exact Match
```
Cart: 500 KES | Wallet: 500 KES
→ totalAmount = 0 (no M-Pesa needed)
→ Backend: total=0, wallet_used=500, payment_status='paid'
→ No STK push ✅
```

### Case 3: Wallet Insufficient
```
Cart: 1000 KES | Wallet: 100 KES
→ totalAmount = 900 KES (needs M-Pesa)
→ Backend: total=900, wallet_used=100, payment_status='pending'
→ STK push initiated ✅
```

### Case 4: No Wallet
```
Cart: 500 KES | Wallet: 0 KES | use_wallet=false
→ totalAmount = 500 KES (needs M-Pesa)
→ Backend: total=500, wallet_used=0, payment_status='pending'
→ STK push initiated ✅
```

---

## 📝 Conclusion

**YES, this works correctly.** ✅

The system is designed to:
1. Calculate remaining amount on frontend
2. Let backend be the source of truth for actual amounts
3. Only initiate payment when `order.total > 0`
4. Auto-complete orders paid entirely by wallet

No fixes needed for this feature.
