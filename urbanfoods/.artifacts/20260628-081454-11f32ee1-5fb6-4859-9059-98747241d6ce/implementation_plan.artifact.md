# Hardening Customer Checkout and M-Pesa Integration

Harden the customer checkout flow by fixing transactional inconsistencies, improving M-Pesa state management, and unifying domain logic.

## Proposed Changes

### [Backend - Checkout Logic]

#### [api_v1_customer_views.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/api_v1_customer_views.py)
- **CustomerPlaceOrderView**:
    - Skip STK initiation if `order.total == 0`.
    - Implement a "fail-closed" production flag: default to actual total unless `MPESA_PRODUCTION` is explicitly `false`.
    - Improve error response when STK initiation fails to provide actionable feedback.
- **CustomerRetryPaymentView**:
    - Allow updating the `mpesa_phone` during retry to fix typos.
- **[NEW] PaymentStatusView**:
    - Lightweight endpoint for polling payment status without serializing the full order.
- **[NEW] MpesaQueryView**:
    - Endpoint to trigger a manual `stkpushquery` to Safaricom if a callback is delayed.

#### [views.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/views.py)
- **mpesa_callback**:
    - Fix idempotency guard: check for `payment_status == 'paid'` instead of `completed`.
    - Ensure all side effects (Loyalty, stats) are protected by this guard.

---

### [Flutter - Mobile App]

#### [payment_pending_screen.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/screens/customer/payment_pending_screen.dart)
- Switch polling to the new lightweight status endpoint.
- Implement a "Stuck? Check Status" button that calls the new `MpesaQueryView`.
- Optimize polling frequency and add a timeout that suggests manual checking or retry.

#### [checkout_screen.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/screens/customer/checkout_screen.dart)
- Improve cart clearing: notify the backend to clear the cart immediately upon successful order creation.

## Verification Plan

### Automated Tests
- Create `urbanfoods/tests/test_checkout_v1.py` covering:
    - Successful STK initiation.
    - STK failure (rollback/state check).
    - Wallet-only checkout (0 total).
    - Idempotent callback processing.
    - Amount mismatch in callback.
    - Retry with new phone number.

### Manual Verification
1. **Wallet-Only Checkout**: Place an order fully covered by wallet balance. Verify no STK push is triggered and order status is immediately `paid`.
2. **STK Polling & Fallback**: Simulate a lost callback and trigger a manual status query from the "Payment Pending" screen.
3. **Retry Flow**: Initiate payment with a wrong number, then use the "Retry" feature with the correct number and verify successful STK initiation.
