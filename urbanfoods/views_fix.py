# CRITICAL FIX: Add order status validation in initiate_mpesa_payment
# This prevents the race condition where:
# 1. User cancels order
# 2. User requests STK on cancelled order
# 3. STK sent successfully
# 4. User enters PIN
# 5. Money deducted on CANCELLED order

@login_required
@require_http_methods(["POST"])
def initiate_mpesa_payment(request):
    """Re-initiate an STK push for an existing unpaid order."""
    data = json.loads(request.body)
    order_number = data.get('order_number')

    if not order_number:
        return JsonResponse({'success': False, 'message': 'Order number required'})

    try:
        order = Order.objects.select_for_update().get(order_number=order_number, user=request.user)
    except Order.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Order not found'})

    # ═══════════════════════════════════════════════════════════════════════
    # 🔴 CRITICAL VALIDATION: Check order eligibility for payment
    # ═══════════════════════════════════════════════════════════════════════
    
    # 1️⃣ REJECT if order is cancelled
    # Prevents: User cancels → requests STK → money deducted on cancelled order
    if order.status == 'cancelled':
        return JsonResponse({
            'success': False,
            'message': 'Cannot initiate payment for a cancelled order',
            'status': order.status
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # 2️⃣ REJECT if payment already confirmed
    # Prevents: Duplicate payment on already-paid order
    if order.payment_status == 'paid':
        return JsonResponse({
            'success': False,
            'message': 'Payment already completed for this order'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # 3️⃣ REJECT if STK was sent recently (within 90 seconds)
    # Prevents: Rapid duplicate STK requests causing CheckoutRequestID conflicts
    if order.mpesa_checkout_request_id:
        last_update = order.updated_at
        seconds_since = (timezone.now() - last_update).total_seconds()
        
        if seconds_since < 90:
            retry_after = 90 - int(seconds_since)
            return JsonResponse({
                'success': False,
                'message': f'STK push was recently sent. Please enter the PIN on your phone or wait to retry.',
                'retry_after_seconds': retry_after,
                'last_sent': last_update.isoformat()
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
    
    # ═══════════════════════════════════════════════════════════════════════
    # All validations passed → Proceed with STK push
    # ═══════════════════════════════════════════════════════════════════════
    
    from .mpesa_utils import MpesaIntegration
    mpesa_service = MpesaIntegration(store=order.store)

    try:
        formatted_phone = mpesa_service.format_phone_number(order.phone_number)
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)})

    stk_result = mpesa_service.initiate_stk_push(
        phone_number=formatted_phone,
        amount=int(order.total),
        account_reference=order.order_number,
        transaction_desc=f"Order {order.order_number}"
    )

    # Log initiation
    log_mpesa_event(
        event_type="stk_initiated",
        user_id=request.user.id,
        order_number=order.order_number,
        phone=formatted_phone,
        amount=int(order.total),
        extra={"checkout_request_id": stk_result.get("checkout_request_id")}
    )

    if not stk_result.get('success'):
        return JsonResponse({
            'success': False,
            'message': stk_result.get('message')
        })

    # ═══════════════════════════════════════════════════════════════════════
    # 🟢 ATOMIC: Update order with NEW CheckoutRequestID
    # This ensures the callback will always find a PENDING order
    # ═══════════════════════════════════════════════════════════════════════
    order.mpesa_checkout_request_id = stk_result['checkout_request_id']
    order.payment_status = 'pending'
    order.save(update_fields=['mpesa_checkout_request_id', 'payment_status'])

    OrderStatusHistory.objects.create(
        order=order,
        status=order.status,
        notes=f"STK push sent to {formatted_phone}. CheckoutRequestID: {stk_result['checkout_request_id']}",
    )

    return JsonResponse({
        'success': True,
        'message': stk_result.get('customer_message', 'STK push sent'),
        'checkout_request_id': stk_result['checkout_request_id'],
    })

