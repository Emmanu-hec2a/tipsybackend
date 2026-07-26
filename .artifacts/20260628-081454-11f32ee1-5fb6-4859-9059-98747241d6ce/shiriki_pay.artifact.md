# Shiriki Pay: Implementation Plan

Shiriki Pay is a social bill-splitting feature designed for the Tipsy Theoryy ecosystem. It allows a host to initiate an order and invite friends to contribute to the "Pot" via M-Pesa. Once the total order amount is reached, the order is finalized and sent to the merchant.

## 1. Backend Architecture (Django)

### Models

#### `ShirikiSession`
Tracks the lifecycle of a split-bill session.
- `order`: OneToOneField to `Order`.
- `host`: ForeignKey to `User`.
- `invite_code`: Unique alphanumeric string (e.g., `TT-X45K`).
- `status`: Choices (`active`, `completed`, `expired`, `cancelled`).
- `created_at`: DateTimeField.
- `expires_at`: DateTimeField (default 30 mins from creation).

#### `ShirikiContribution`
Tracks individual payments into the pot.
- `session`: ForeignKey to `ShirikiSession`.
- `user`: ForeignKey to `User`.
- `amount`: DecimalField.
- `phone_number`: CharField (M-Pesa number).
- `checkout_request_id`: CharField (M-Pesa reference).
- `status`: Choices (`pending`, `confirmed`, `failed`).
- `paid_at`: DateTimeField (null=True).

### API Endpoints

- `POST /customer/shiriki/create/`:
    - Validates that the order is `pending` and not already part of a session.
    - Generates a unique `invite_code`.
- `GET /customer/shiriki/session/<invite_code>/`:
    - Returns order summary, pot progress, and list of participants.
- `POST /customer/shiriki/contribute/`:
    - Initiates Daraja STK Push for a specific amount.
- `POST /customer/shiriki/webhook/`:
    - Existing M-Pesa callback logic updated to handle contributions.
    - If `Pot Total >= Order Total`, update `Order.payment_status = 'paid'`.

## 2. Frontend Architecture (Flutter)

### `ShirikiProvider`
- State management for joining sessions, fetching live progress, and initiating payments.
- Polling (every 10s) to update pot progress (or FCM listener).

### Screens

#### `ShirikiLobbyScreen` (Dynamic)
- **Host View**: Share Link, Code, Nudge Friends, Cover Rest.
- **Participant View**: Order Summary, Pay Equal/Custom, Wait for others.

#### `ShirikiJoinScreen`
- Simple code entry field for joining via alphanumeric code.

## 3. Growth & Growth (Deep Linking)
- Use custom URL scheme `tipsytheoryy://shiriki/<code>`.
- Integrate with `share_plus` for inviting via WhatsApp/SMS.

## 4. Refund Mechanism (The Safety Net)
- Celery task runs every 5 minutes to check for `expired` sessions.
- All `confirmed` contributions in an `expired` session are credited to the users' `wallet_balance`.
- Send FCM notification to all participants: *"Shiriki session expired. Your contribution has been refunded to Tipsy Credit."*

## 5. Implementation Roadmap
1. [ ] Backend: Models & Migrations.
2. [ ] Backend: Create & Join APIs.
3. [ ] Backend: Contribution & Webhook logic.
4. [ ] Frontend: `ShirikiProvider`.
5. [ ] Frontend: Lobby UI (Host & Participant).
6. [ ] Frontend: Join UI & Deep Linking.
7. [ ] Testing: E2E flow with M-Pesa sandbox.
