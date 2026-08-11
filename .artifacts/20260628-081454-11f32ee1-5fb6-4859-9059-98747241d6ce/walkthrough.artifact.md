# Walkthrough: Payouts & Financial Hardening

This document summarizes the improvements made to the delivery and financial ecosystem, focusing on payout transparency and M-Pesa resiliency.

## 🏦 Payout & Settlement System
We implemented a **Dual-Layer Financial Model** to balance real-time visibility with clean accounting.

### **Accrual vs. Settlement**
*   **Live Accruals**: Every delivery instantly records a `RiderEarning`. This shows up in the "Real-time Accruals" cards for immediate visibility.
*   **Weekly Settlement**: To avoid dashboard clutter, all earnings for a rider are batched into a single `RiderWeeklyStat` row every Sunday (or via manual trigger).
*   **Merchant Dashboard**: The payout table is now high-density and professional, showing only consolidated weekly rows to simplify M-Pesa settlements.

## 🛡️ M-Pesa Hardening & Race Condition Fixes
We resolved a critical issue where "phantom payments" occurred on cancelled orders due to late STK prompts.

### **1. Order Resurrection**
If a user enters their PIN *after* the system has already cancelled the order (due to a timeout), the system now:
1.  Detects the successful payment.
2.  **Resurrects** the order from `cancelled` back to `pending`.
3.  Re-verifies stock levels to ensure the items are still available.

### **2. Atomic Payment Locking**
To prevent users from triggering multiple STK prompts simultaneously (which causes race conditions), we added a **45-second Redis-backed lock** on the payment initiation process.

### **3. Encryption Synchronization**
Fixed a desync between the fallback encryption key and the new production key. All store M-Pesa credentials have been migrated to the production key, ensuring stable STK pushes.

## 🚴 Rider Transparency
The rider app is now fully synchronized with the merchant's payout actions:
*   **Status Sync**: Riders see "PAID" status immediately after the merchant confirms.
*   **Verification**: The M-Pesa transaction code is displayed on the rider's payout card for cross-referencing.
*   **Dispute System**: A "Not Received?" button allows riders to flag payment issues for admin review.

---
**The system is now production-ready, highly transparent, and resilient to common mobile payment failures.** 🛡️🛰️🏦
