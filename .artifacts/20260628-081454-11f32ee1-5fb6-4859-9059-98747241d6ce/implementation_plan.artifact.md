# Implementation Plan: Subscription Invoice Downloads

The "Download Invoice" feature in the Merchant Dashboard's Billings tab is currently a placeholder. This plan implements the backend PDF generation for subscription payments and connects it to the frontend.

## User Review Required

> [!IMPORTANT]
> This requires the `xhtml2pdf` library on the backend for PDF generation. It is already used for order invoices.

## Proposed Changes

### [Backend] UrbanFoods API

#### [api_v1_billing_views.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/api_v1_billing_views.py)

- Add `SubscriptionInvoiceView` to handle PDF generation for a specific `SubscriptionPayment`.
- Implement security check to ensure only the store owner can download the invoice.

#### [api_v1_urls.py](file:///C:/Users/PC/Desktop/tipsytheoryy/urbanfoods/api_v1_urls.py)

- Register the new route: `path('billing/invoices/<int:pk>/', api_v1_billing_views.SubscriptionInvoiceView.as_view(), name='subscription_invoice')`.

#### [NEW] [subscription_receipt.html](file:///C:/Users/PC/Desktop/tipsytheoryy/templates/invoices/subscription_receipt.html)

- Create a professional HTML template for subscription receipts.

---

### [Frontend] Merchant Dashboard

#### [api.js](file:///C:/Users/PC/Desktop/tipsytheoryy_merchant/src/api.js)

- Add `downloadSubscriptionInvoice` method to the `partner` object. Since it returns a binary blob, it will handle the raw response.

#### [Billing.jsx](file:///C:/Users/PC/Desktop/tipsytheoryy_merchant/src/pages/Billing.jsx)

- Implement `handleDownloadInvoice` function.
- Attach the function to the `Download` icon's `onClick` event in the Payment History table.
- Add loading state for the download action.

---

## Verification Plan

### Manual Verification
1. **Initiate Download**: Click the download icon on a successful payment in the Billing history.
2. **Verify PDF**: Ensure a PDF is downloaded with the correct details (Store name, Plan, Amount, M-Pesa Receipt).
3. **Security Test**: Attempt to download an invoice ID that belongs to a different store (should return 404/403).
4. **Error Handling**: Verify behavior for pending/failed payments (should show an error message).
