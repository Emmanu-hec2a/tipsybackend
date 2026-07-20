# Advanced Engagement & Safety Notifications

This plan outlines the implementation of three intelligent notification features designed to increase conversion (Cart Reminders), boost merchant value (New Arrivals), and ensure customer safety (Walk-and-Watch).

## Proposed Changes

### 1. Abandoned Cart Reminders (Backend)
Detect carts that haven't been updated for 2 hours and send a gentle nudge.

#### [tasks.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/tasks.py)
- Add `check_abandoned_carts` task to run via Celery Beat every hour.
- Filter `Cart` objects where `updated_at` is older than 2 hours and haven't received a reminder today.

#### [models.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/models.py)
- Add `last_reminder_sent_at` to the `Cart` model to prevent spamming.

---

### 2. Pro Merchant "New Arrival" Alerts (Backend)
Allow Pro merchants to announce new liquor products to their previous customers.

#### [api_v1_partner_views.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/api_v1_partner_views.py)
- Update `MenuItemViewSet` to trigger a background notification if `is_new_arrival` is toggled ON during creation/update.

#### [tasks.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/tasks.py)
- Add `notify_new_arrival_task` to find customers who have previously ordered from the store and send them a "New in Stock" alert.

---

### 3. "Walk-and-Watch" Safety Notice (Mobile)
Detect when a customer is walking while looking at the app and show a subtle warning overlay.

#### [customer_shell.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/screens/customer/customer_shell.dart)
- Integrate `sensors_plus` to detect movement patterns (User Acceleration).
- Show a temporary, non-intrusive "Look Up!" snackbar or overlay if walking speed is detected while the app is active.

## Technical Details

### Cart Reminder Logic
```python
# Pseudo-logic for Celery Task
threshold = timezone.now() - timedelta(hours=2)
abandoned_carts = Cart.objects.filter(
    updated_at__lte=threshold,
    items__isnull=False
).exclude(last_reminder_sent_at__date=timezone.now().date())
```

### Safety Detection (Flutter)
```dart
// Using accelerometer events
accelerometerEvents.listen((AccelerometerEvent event) {
  double velocity = sqrt(event.x*event.x + event.y*event.y + event.z*event.z);
  if (velocity > walkingThreshold && appIsVisible) {
     showSafetyNotice();
  }
});
```

## Verification Plan

### Automated Tests
- `pytest urbanfoods/tests/test_notifications.py` (New tests for task logic).

### Manual Verification
1. **Cart**: Add item to cart, wait (or manually trigger task), verify FCM received.
2. **New Arrival**: Create product as Pro Merchant with toggle ON, verify FCM received by "Customer".
3. **Safety**: Run app on physical device, walk while app is open, verify safety notice appears.
