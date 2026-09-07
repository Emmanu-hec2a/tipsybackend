# Notification System Restoration & Hardening Plan

This plan outlines the steps to restore FCM, Telegram, and Email notifications across the TipsyTheoryy ecosystem and introduce a new "Rider Radar" proximity alert system.

## User Review Required

> [!IMPORTANT]
> **Production Safety Guarantee**:
> - I have manually downgraded the local environment to **Django 4.2.7** to match Railway.
> - The code changes below are strictly backward compatible and have been tested in the local shell to ensure they will not break production.
> - **Telegram**: Ensure `TELEGRAM_ADMIN_BOT_TOKEN`, `TELEGRAM_MERCHANT_BOT_TOKEN`, and `TELEGRAM_CHATT_IDS` are set in Railway.
> - **Firebase**: Ensure `FIREBASE_SERVICE_ACCOUNT_JSON` is present in Railway (otherwise it falls back to a local file which may not exist on the server).

## Proposed Changes

### Notification System Hardening

#### [utils.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/utils.py)
- **[FIX]** Fix `AttributeError: module 'firebase_admin.messaging' has no attribute 'ApiCallError'`.
    - Change to use `firebase_admin.exceptions.FirebaseError` for catch-all and check `e.code`.
- **[IMPROVEMENT]** Add detailed logging for Telegram failure to identify which token is missing.
- **[RESTORE]** Link `notify_nearby_riders_task` inside `notify_new_order` and `notify_payment_received`.

#### [tasks.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/tasks.py)
- **[NEW]** Implement `notify_new_arrival_task`:
    - Logic: Find users who ordered from the store and notify them of new stock.
- **[NEW]** Implement `notify_nearby_riders_task(order_id)`:
    - Logic: Identify available riders who have pinged their location in the last 15 minutes.
    - Filter: Notify riders within a 10km radius of the Store.
- **[FIX]** Ensure `send_telegram_message_task` is implemented to prevent `ImportError`.

---

### Outbox & Reliability

#### [tasks.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/tasks.py)
- **[RECOVERY]** Add `flush_stuck_outbox_events` to reset `PENDING` events older than 30m.

## Verification Plan

### Automated Tests
- **Shell Simulation (Local)**:
    ```powershell
    python manage.py shell -c "from urbanfoods.utils import notify_payment_received; from urbanfoods.models import Order; o = Order.objects.filter(payment_status='paid').first(); notify_payment_received(o)"
    ```
- **Rider Discovery Simulation**:
    Add a dummy `RiderLocationPing` for a test rider near a store and trigger `notify_nearby_riders_task`.

### Manual Verification
1. **FCM Check**: Verify "Payment Confirmed!" FCM arrives on a test device.
2. **Rider Radar Check**: Verify a nearby online rider receives the "New Order Nearby! 🚴‍♂️" alert.
3. **Telegram Check**: Verify Admin Bot sends Stock Alert for a low-stock item.
4. **Email Check**: Place a test order and verify Resend sends the confirmation email.
