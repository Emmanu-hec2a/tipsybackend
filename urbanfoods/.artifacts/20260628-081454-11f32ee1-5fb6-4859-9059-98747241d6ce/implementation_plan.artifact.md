# Fixing Timezone Discrepancies and Rider Earnings Logic

Resolve the "incorrect time" on both apps and align rider earnings strictly with the delivery fee paid by customers.

## Diagnostic Report

1.  **Timezone Mismatch**: The backend sends UTC timestamps (e.g., `2023-10-27T10:00:00Z`). The Flutter app parses these but displays them directly without calling `.toLocal()`. Since Kenya is UTC+3, users see times that are 3 hours behind.
2.  **Earnings Logic Disconnect**:
    *   The `Order` model has a `rider_base_fare` field that defaults to **200**.
    *   When a customer places an order, the `delivery_fee` is calculated dynamically (e.g., 150 or 250).
    *   However, `rider_base_fare` is never updated to match this `delivery_fee`.
    *   When the rider completes the delivery, the `RiderEarning` record is created using the stagnant `rider_base_fare` (200) instead of the actual `delivery_fee`.

## Proposed Changes

### [Backend - Logistics & Finance]

#### [api_v1_customer_views.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/api_v1_customer_views.py)
- In `CustomerPlaceOrderView`, update the `Order.objects.create` call to set `rider_base_fare=delivery_fee`. This ensures the rider's potential earning matches exactly what the customer paid.

#### [api_v1_rider_views.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/api_v1_rider_views.py)
- In `RiderOrderStatusView` (for `delivered` status), ensure the `RiderEarning` creation uses the most up-to-date `rider_base_fare` from the order.

---

### [Flutter - Mobile App]

#### [order_model.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/models/order_model.dart)
- Update `fromJson` to call `.toLocal()` on `createdAt` and `riderVerifiedAt`.

#### [chat_message_model.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/models/chat_message_model.dart)
- Update `fromJson` to call `.toLocal()` on `createdAt`.

#### [earnings_screen.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/screens/rider/earnings_screen.dart)
- Update the transaction history list to call `.toLocal()` on the parsed timestamp.

## Verification Plan

### Manual Verification
1. **Place Order**: Create an order as a customer. Verify the `delivery_fee` (e.g., KSh 150).
2. **Backend Audit**: Check the database for the new order. Verify `delivery_fee` is 150 AND `rider_base_fare` is now 150 (instead of the old default 200).
3. **Time Check**: View the order on the customer app. Verify the "Order Time" matches your current phone's time (Kenya Time).
4. **Complete Delivery**: As a rider, accept and deliver the order.
5. **Earnings Audit**: Check the "Earnings" screen. Verify the payout matches the 150 `delivery_fee`.
6. **Chat Time**: Send a chat message and verify the timestamp matches your local time exactly.
