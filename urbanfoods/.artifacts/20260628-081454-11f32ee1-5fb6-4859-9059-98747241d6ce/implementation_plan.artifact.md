# Resolving Rider Availability Toggle Latency

Fix the Rider Online/Offline toggle by addressing blocking GPS calls, backend parsing inconsistencies, and redundant UI loading states.

## Diagnostic Report

1.  **Blocking GPS Fetching (Flutter)**: The app calls `Geolocator.getCurrentPosition(accuracy: high)` directly inside the `toggleAvailability` flow. On many devices, "High Accuracy" GPS can take 10-30 seconds to lock, especially indoors, making the UI appear frozen or "loading for years."
2.  **Smart Boolean Mismatch (Backend)**: The backend uses a complex manual check for `is_available` (`val if isinstance(val, bool) else str(val).lower() == 'true'`) which can fail depending on how Dio encodes the patch request, leading to the toggle being ignored.
3.  **Lack of Optimistic UI**: The toggle waits for the full network round-trip (plus the GPS lock) before updating the switch state, leading to poor perceived performance.
4.  **Race Conditions**: Redundant background polling (`_pollData` every 10s) may conflict with the `toggleAvailability` update, causing the UI to "flicker" back to the old state before the server responds.

## Proposed Changes

### [Backend - Rider Logistics]

#### [api_v1_rider_views.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/api_v1_rider_views.py)
- Refactor `RiderProfileView.patch` to use the `RiderProfileSerializer` for ALL field parsing, including `is_available`.
- Add explicit logging for GPS/Active order guards to help debug "silent" failures.
- Ensure the `is_available` toggle instantly clears/sets the `rider_pos_` cache.

---

### [Flutter - Mobile App]

#### [rider_provider.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/providers/rider_provider.dart)
- **Fast-Track Toggle**: Use a lower accuracy or cached location if a high-accuracy lock takes too long (>3 seconds).
- **Separated Loading States**: Distinguish between "Skeleton Loading" (background refresh) and "Action Loading" (blocking toggle).
- **Optimistic Update**: Instantly update the local `_riderProfile.isAvailable` state and only revert if the API fails.

#### [available_orders_screen.dart](file:///C:/Users/PC/Desktop/tipsytheoryy_app/lib/screens/rider/available_orders_screen.dart)
- Add a visual "GPS Finding..." indicator if the delay is caused by location services.
- Ensure the `Switch` remains responsive during the action.

## Verification Plan

### Manual Verification
1. **Instant Toggle**: Click the Online switch. It should move to the ON position *instantly* (optimistic), with a small spinner appearing nearby while GPS/API finishes.
2. **GPS Timeout**: Disable GPS or move to a basement. Verify the app times out gracefully and shows "Please turn on GPS" instead of loading indefinitely.
3. **Active Order Guard**: Try to go offline while carrying an order. Verify the backend correctly rejects the request and the app shows the error message.
4. **Offline Persistence**: Toggle offline and verify the `rider_pos_` cache is cleared in Redis (via backend logs).
