# urbanfoods/notifications.py
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

local_time = timezone.localtime(timezone.now())

def send_admin_order_notification(order):
    """Send email notification to admin when a new order is received"""
    subject = f'🔔 New Order: {order.order_number}'
    
    # Get order items
    items_list = "\n".join([
        f"  - {item.food_item.name} x{item.quantity} @ KES {item.price_at_order}"
        for item in order.items.all()
    ])
    
    # Plain text version
    message = f'''
New Order Received!

Order Details:
--------------
Order Number: {order.order_number}
Store Type: {order.store_type.upper()}
Status: {order.status.upper()}

Customer Information:
--------------------
Name: {order.user.get_full_name() or order.user.username}
Email: {order.user.email}
Phone: {order.phone_number}

Delivery Details:
----------------
Hostel: {order.hostel}
Room Number: {order.room_number}
Delivery Notes: {order.delivery_notes or 'None'}

Order Summary:
-------------
{items_list}

Subtotal: KES {order.subtotal}
Delivery Fee: KES {order.delivery_fee}
Total Amount: KES {order.total}

Payment:
--------
Payment Method: {order.payment_method.upper()}
Payment Type: {order.payment_type.upper()}
Payment Status: {order.payment_status.upper()}

Estimated Delivery: {order.estimated_delivery.strftime('%I:%M %p')}

View order details at:
{settings.SITE_URL}/admin-panel/orders/

---
TipsyTheoryy Admin System
    '''
    
    # HTML version
    items_html = "".join([
        f'''
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6;">{item.food_item.name}</td>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6; text-align: center;">{item.quantity}</td>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6; text-align: right;">KES {item.price_at_order}</td>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6; text-align: right; font-weight: bold; color: #ea580c;">KES {item.quantity * item.price_at_order}</td>
        </tr>
        '''
        for item in order.items.all()
    ])

    html_message = f'''
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f3f4f6;
                min-height: 100vh;
            }}
            .container {{
                max-width: 700px;
                margin: 20px auto;
                padding: 20px;
            }}
            .card {{
                background: #ffffff;
                border-radius: 16px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .gradient-header {{
                background: linear-gradient(135deg, #ea580c, #dc2626);
                padding: 30px;
                text-align: center;
            }}
            .gradient-header h1 {{
                color: #ffffff;
                margin: 0;
                font-size: 28px;
                font-weight: 700;
            }}
            .gradient-header p {{
                color: #ffffff;
                margin: 10px 0 0 0;
                font-size: 16px;
                opacity: 0.95;
            }}
            .content {{
                padding: 30px;
                color: #1f2937;
            }}
            .info-card {{
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 20px;
                margin: 20px 0;
            }}
            .info-card h2 {{
                color: #ea580c;
                margin: 0 0 15px 0;
                font-size: 22px;
            }}
            .section-header {{
                color: #2563eb;
                margin: 30px 0 15px 0;
                font-size: 18px;
                border-bottom: 2px solid #2563eb;
                padding-bottom: 8px;
            }}
            .modern-table {{
                border-collapse: collapse;
                width: 100%;
                margin: 20px 0;
                border-radius: 12px;
                overflow: hidden;
                border: 1px solid #e5e7eb;
            }}
            .modern-table th {{
                background: #f3f4f6;
                padding: 15px;
                text-align: left;
                font-weight: 600;
                color: #374151;
                border-bottom: 2px solid #e5e7eb;
            }}
            .modern-table td {{
                padding: 12px;
                border-bottom: 1px solid #f3f4f6;
                color: #1f2937;
            }}
            .modern-table tbody tr:hover {{
                background-color: #f9fafb;
            }}
            .total-row {{
                background: linear-gradient(135deg, #ea580c, #dc2626);
            }}
            .total-row td {{
                color: #ffffff !important;
                border-bottom: none;
                padding: 18px;
                font-size: 18px;
                font-weight: bold;
            }}
            .modern-btn {{
                display: inline-block;
                padding: 15px 30px;
                background: linear-gradient(135deg, #ea580c, #dc2626);
                color: #ffffff;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
                font-size: 16px;
                box-shadow: 0 4px 15px rgba(234, 88, 12, 0.3);
            }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e5e7eb;
            }}
            .footer p {{
                color: #6b7280;
                font-size: 12px;
                margin: 0;
            }}
            .highlight {{
                color: #ea580c;
                font-weight: 600;
            }}
            .success {{
                color: #10b981;
                font-weight: 600;
            }}
            .info {{
                color: #2563eb;
                font-weight: 600;
            }}
            strong {{
                color: #374151;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="gradient-header">
                    <h1>🔔 New Order Alert!</h1>
                    <p>Fresh order just came in</p>
                </div>

                <div class="content">
                    <div class="info-card">
                        <h2>Order #{order.order_number}</h2>
                        <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                            <div><strong>Store:</strong> <span class="info">{order.store_type.upper()}</span></div>
                            <div><strong>Status:</strong> <span class="highlight">{order.status.upper()}</span></div>
                        </div>
                    </div>

                    <h3 class="section-header">👤 Customer Details</h3>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; color: #1f2937;">
                        <div><strong>Name:</strong><br>{order.user.get_full_name() or order.user.username}</div>
                        <div><strong>Email:</strong><br>{order.user.email}</div>
                        <div><strong>Phone:</strong><br>{order.phone_number}</div>
                        <div><strong>Hostel:</strong><br>{order.hostel}</div>
                    </div>

                    <h3 class="section-header">📍 Delivery Info</h3>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; color: #1f2937;">
                        <div><strong>Room:</strong><br>{order.room_number}</div>
                        <div><strong>Notes:</strong><br>{order.delivery_notes or 'None'}</div>
                        <div><strong>ETA:</strong><br><span class="success">15 mins</span></div>
                        <div><strong>Payment:</strong><br><span class="highlight">{order.payment_method.upper()}</span></div>
                    </div>

                    <h3 class="section-header">🛒 Order Items</h3>
                    <table class="modern-table">
                        <thead>
                            <tr>
                                <th>Item</th>
                                <th style="text-align: center;">Qty</th>
                                <th style="text-align: right;">Price</th>
                                <th style="text-align: right;">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_html}
                            <tr style="background: #f9fafb;">
                                <td colspan="3" style="text-align: right; font-weight: bold;">Subtotal:</td>
                                <td style="text-align: right; font-weight: bold; color: #ea580c;">KES {order.subtotal}</td>
                            </tr>
                            <tr style="background: #f9fafb;">
                                <td colspan="3" style="text-align: right;">Delivery Fee:</td>
                                <td style="text-align: right;">KES {order.delivery_fee}</td>
                            </tr>
                            <tr class="total-row">
                                <td colspan="3" style="text-align: right;">TOTAL:</td>
                                <td style="text-align: right;">KES {order.total}</td>
                            </tr>
                        </tbody>
                    </table>

                    <div style="text-align: center; margin: 40px 0;">
                        <a href="{settings.SITE_URL}/admin-panel/orders/" class="modern-btn">
                            📊 View All Orders →
                        </a>
                    </div>

                    <div class="footer">
                        <p>
                            Tipsy Theoryy Admin System<br>
                            Sent {timezone.localtime(timezone.now()).strftime('%B %d, %Y at %I:%M %p')}
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    '''
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_NOTIFICATION_EMAIL],
            fail_silently=False,
            html_message=html_message,
        )
        return True
    except Exception as e:
        print(f"Failed to send admin notification email: {e}")
        return False


def send_customer_order_confirmation(order):
    """Send order confirmation email to customer"""
    subject = f'Order Confirmation - {order.order_number}'
    
    # Get order items
    items_list = "\n".join([
        f"  - {item.food_item.name} x{item.quantity} @ KES {item.price_at_order}"
        for item in order.items.all()
    ])
    
    payment_instructions = ""
    if order.payment_method == 'cash':
        if order.store_type == 'liquor':
            payment_instructions = f'''
Payment Instructions:
--------------------
Please complete payment using M-PESA Paybill:
Business Number: 8330098 - NETWIX
Account Number: {order.order_number}
Amount: KES {order.total}

Your order will be processed once payment is confirmed.
please ignore this if already paid.
'''
        else:
            payment_instructions = f'''
Payment Instructions:
--------------------
Please complete payment using M-PESA Till Number:
Till Number: 6960814 - MOSES ONKUNDI ATINDA
Amount: KES {order.total}

Your order will be processed once payment is confirmed.
please ignore this if already paid.
'''
    
    # Plain text version
    message = f'''
Thank you for your order!

Hi {order.user.get_full_name() or order.user.username},

Your order has been received and is being processed.

Order Details:
--------------
Order Number: {order.order_number}
Order Date: {timezone.localtime(order.created_at).strftime('%B %d, %Y at %I:%M %p')}

Payment Method: {order.payment_method.upper()}

Delivery Information:
--------------------
Hostel: {order.hostel}
Room Number: {order.room_number}
Phone: {order.phone_number}
Estimated Delivery: {
    timezone.localtime(order.estimated_delivery).strftime('%I:%M %p')
    if order.estimated_delivery else '15 mins'
}

Order Summary:
-------------
{items_list}

Subtotal: KES {order.subtotal}
Delivery Fee: KES {order.delivery_fee}
Total Amount: KES {order.total}
Estimated Delivery: {
    timezone.localtime(order.estimated_delivery).strftime('%I:%M %p')
    if order.estimated_delivery else '15 mins'
}

{payment_instructions}

You can track your order status at:
https://tipsytheoryy/orders/

If you have any questions, please contact us | Call 0110345054.

Thank you for choosing Tipsy Theoryy!

---
Tipsy Theoryy
    '''
    
    # HTML version
    items_html = "".join([
        f'''
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6;">{item.food_item.name}</td>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6; text-align: center;">{item.quantity}</td>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6; text-align: right;">KES {item.price_at_order}</td>
            <td style="padding: 12px; border-bottom: 1px solid #f3f4f6; text-align: right; font-weight: bold; color: #ea580c;">KES {item.quantity * item.price_at_order}</td>
        </tr>
        '''
        for item in order.items.all()
    ])

    payment_html = ""
    if order.payment_method == 'cash':
        payment_type = "Paybill" if order.store_type == 'liquor' else "Till Number"
        payment_number = "8330098 - NETWIX" if order.store_type == 'liquor' else "6960814 - MOSES ONKUNDI ATINDA"
        account_info = f'<p style="margin: 5px 0; color: #1f2937;"><strong>Account Number:</strong> {order.order_number}</p>' if order.store_type == 'liquor' else ""
        payment_html = f'''
        <div style="background: #fef3c7; border: 1px solid #fbbf24; border-radius: 12px; padding: 20px; margin: 20px 0;">
            <h3 style="color: #92400e; margin: 0 0 15px 0; font-size: 18px;">💳 Payment Required</h3>
            <p style="margin: 10px 0; color: #1f2937;"><strong>Please complete payment using M-PESA {payment_type}:</strong></p>
            <p style="margin: 5px 0; font-size: 1.2em; color: #2563eb; font-weight: bold;">{payment_number}</p>
            {account_info}
            <p style="margin: 5px 0; color: #1f2937;"><strong>Amount:</strong> <span style="color: #10b981; font-size: 1.3em; font-weight: bold;">KES {order.total}</span></p>
            <p style="margin: 10px 0 0 0; font-size: 0.9em; color: #78716c;">Your order will be processed once payment is confirmed by our team.</p>
        </div>
        '''

    html_message = f'''
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f3f4f6;
                min-height: 100vh;
            }}
            .container {{
                max-width: 700px;
                margin: 20px auto;
                padding: 20px;
            }}
            .card {{
                background: #ffffff;
                border-radius: 16px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .gradient-header {{
                background: linear-gradient(135deg, #ea580c, #dc2626);
                padding: 30px;
                text-align: center;
            }}
            .gradient-header h1 {{
                color: #ffffff;
                margin: 0;
                font-size: 28px;
                font-weight: 700;
            }}
            .gradient-header p {{
                color: #ffffff;
                margin: 10px 0 0 0;
                font-size: 16px;
                opacity: 0.95;
            }}
            .content {{
                padding: 30px;
                color: #1f2937;
            }}
            .info-card {{
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 20px;
                margin: 20px 0;
            }}
            .info-card h2 {{
                color: #ea580c;
                margin: 0 0 15px 0;
                font-size: 22px;
            }}
            .section-header {{
                color: #2563eb;
                margin: 30px 0 15px 0;
                font-size: 18px;
                border-bottom: 2px solid #2563eb;
                padding-bottom: 8px;
            }}
            .modern-table {{
                border-collapse: collapse;
                width: 100%;
                margin: 20px 0;
                border-radius: 12px;
                overflow: hidden;
                border: 1px solid #e5e7eb;
            }}
            .modern-table th {{
                background: #f3f4f6;
                padding: 15px;
                text-align: left;
                font-weight: 600;
                color: #374151;
                border-bottom: 2px solid #e5e7eb;
            }}
            .modern-table td {{
                padding: 12px;
                border-bottom: 1px solid #f3f4f6;
                color: #1f2937;
            }}
            .modern-table tbody tr:hover {{
                background-color: #f9fafb;
            }}
            .total-row {{
                background: linear-gradient(135deg, #ea580c, #dc2626);
            }}
            .total-row td {{
                color: #ffffff !important;
                border-bottom: none;
                padding: 18px;
                font-size: 18px;
                font-weight: bold;
            }}
            .modern-btn {{
                display: inline-block;
                padding: 15px 30px;
                background: linear-gradient(135deg, #ea580c, #dc2626);
                color: #ffffff;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
                font-size: 16px;
                box-shadow: 0 4px 15px rgba(234, 88, 12, 0.3);
            }}
            .help-card {{
                background: #dbeafe;
                border: 1px solid #3b82f6;
                border-radius: 12px;
                padding: 20px;
                margin: 20px 0;
            }}
            .help-card p {{
                margin: 0;
            }}
            .help-card p:first-child {{
                color: #1e40af;
                font-weight: 600;
                font-size: 16px;
                margin-bottom: 8px;
            }}
            .help-card p:last-child {{
                color: #1f2937;
            }}
            .footer {{
                text-align: center;
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e5e7eb;
            }}
            .footer p {{
                color: #6b7280;
                font-size: 12px;
                margin: 0;
            }}
            .highlight {{
                color: #ea580c;
                font-weight: 600;
            }}
            .success {{
                color: #10b981;
                font-weight: 600;
            }}
            .info {{
                color: #2563eb;
                font-weight: 600;
            }}
            strong {{
                color: #374151;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="gradient-header">
                    <h1>🎉 Order Confirmed!</h1>
                    <p>Thank you for choosing Tipsy Theoryy</p>
                </div>

                <div class="content">
                    <p style="font-size: 18px; margin: 0 0 20px 0;">Hi <strong class="highlight">{order.user.get_full_name() or order.user.username}</strong>,</p>
                    <p style="color: #4b5563; margin: 0 0 30px 0; line-height: 1.6;">Your order has been received and is being processed. Here are your order details:</p>

                    <div class="info-card">
                        <h2>Order #{order.order_number}</h2>
                        <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                            <div><strong>Date:</strong> <span class="info">{timezone.localtime(order.created_at).strftime('%B %d, %Y')}</span></div>
                            <div><strong>Time:</strong> <span class="info">{timezone.localtime(order.created_at).strftime('%I:%M %p')}</span></div>
                            <div><strong>Status:</strong> <span class="highlight">{order.status.upper()}</span></div>
                        </div>
                    </div>

                    <h3 class="section-header">📍 Delivery Details</h3>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; color: #1f2937;">
                        <div><strong>Hostel:</strong><br>{order.hostel}</div>
                        <div><strong>Room:</strong><br>{order.room_number}</div>
                        <div><strong>Phone:</strong><br>{order.phone_number}</div>
                        <div><strong>ETA:</strong><br><span class="success">15 mins</span></div>
                    </div>

                    <h3 class="section-header">🛒 Order Items</h3>
                    <table class="modern-table">
                        <thead>
                            <tr>
                                <th>Item</th>
                                <th style="text-align: center;">Qty</th>
                                <th style="text-align: right;">Price</th>
                                <th style="text-align: right;">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_html}
                            <tr style="background: #f9fafb;">
                                <td colspan="3" style="text-align: right; font-weight: bold;">Subtotal:</td>
                                <td style="text-align: right; font-weight: bold; color: #ea580c;">KES {order.subtotal}</td>
                            </tr>
                            <tr style="background: #f9fafb;">
                                <td colspan="3" style="text-align: right;">Delivery Fee:</td>
                                <td style="text-align: right;">KES {order.delivery_fee}</td>
                            </tr>
                            <tr class="total-row">
                                <td colspan="3" style="text-align: right;">TOTAL:</td>
                                <td style="text-align: right;">KES {order.total}</td>
                            </tr>
                        </tbody>
                    </table>

                    <div style="margin: 20px 0; color: #1f2937;"><strong>Payment Method:</strong> <span class="highlight">{order.payment_method.upper()}</span></div>

                    {payment_html}

                    <div style="text-align: center; margin: 40px 0;">
                        <a href="{settings.SITE_URL}/orders/" class="modern-btn">
                            📍 Track Your Order →
                        </a>
                    </div>

                    <div class="help-card">
                        <p>💡 Need Help?</p>
                        <p>If you have any questions about your order, please contact our support team. | Call 0110345054</p>
                    </div>

                    <div class="footer">
                        <p>
                            Thank you for choosing Urban Dreams Cafe!<br>
                            This email was sent to {order.user.email}<br>
                            Sent {timezone.localtime(timezone.now()).strftime('%B %d, %Y at %I:%M %p')}
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    '''
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.user.email],
            fail_silently=False,
            html_message=html_message,
        )
        return True
    except Exception as e:
        print(f"Failed to send customer confirmation email: {e}")
        return False
        