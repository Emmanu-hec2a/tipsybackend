from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import patch
from urbanfoods.models import Store, Order, FoodItem
from decimal import Decimal


class FlutterwavePaymentFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='customer1',
            email='customer@example.com',
            password='secret123',
            role='customer',
            phone='254700000001',
        )
        self.partner = get_user_model().objects.create_user(
            username='partner1',
            email='partner@example.com',
            password='secret123',
            role='partner',
            phone='254700000002',
        )
        self.store = Store.objects.create(
            owner=self.partner,
            name='Test Store',
            is_active=True,
            delivery_fee=Decimal('100.00'),
            flutterwave_enabled=True,
            flutterwave_public_key='pk_test_123',
            flutterwave_secret_key='sk_test_123',
            flutterwave_webhook_secret='whsec_123',
        )
        self.item = FoodItem.objects.create(
            store=self.store,
            name='Test Drink',
            description='A test item',
            price=Decimal('500.00'),
            stock=10,
            image='dummy.jpg',
            prep_time=15,
            is_available=True,
            is_active=True,
        )

    def test_initiate_payment_returns_flutterwave_payload(self):
        order = Order.objects.create(
            user=self.user,
            store=self.store,
            subtotal=Decimal('500.00'),
            delivery_fee=Decimal('100.00'),
            total=Decimal('600.00'),
            phone_number='254700000001',
            status='pending',
            payment_status='pending',
            order_number='TTTEST456',
        )

        self.client.force_login(self.user)
        with patch('urbanfoods.api_v1_billing_views.requests.post') as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            mock_post.return_value.json.return_value = {
                'data': {'link': 'https://flutterwave.test/checkout/123'}
            }

            response = self.client.post(
                reverse('initiate_flutterwave_payment'),
                {
                    'amount': '600.00',
                    'order_id': str(order.id),
                    'currency': 'KES',
                    'email': 'customer@example.com',
                    'name': 'Test User',
                },
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn('payment_url', body)
        self.assertIn('transaction_reference', body)
        self.assertEqual(body['currency'], 'KES')

    def test_webhook_confirms_paid_order(self):
        order = Order.objects.create(
            user=self.user,
            store=self.store,
            subtotal=Decimal('500.00'),
            delivery_fee=Decimal('100.00'),
            total=Decimal('600.00'),
            phone_number='254700000001',
            status='pending',
            payment_status='pending',
            order_number='TTTEST123',
        )
        response = self.client.post(
            reverse('flutterwave_webhook'),
            {
                'event': 'charge.completed',
                'data': {
                    'status': 'successful',
                    'tx_ref': order.order_number,
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')

    def test_compat_rating_route_accepts_order_id(self):
        order = Order.objects.create(
            user=self.user,
            store=self.store,
            subtotal=Decimal('500.00'),
            delivery_fee=Decimal('100.00'),
            total=Decimal('600.00'),
            phone_number='254700000001',
            status='delivered',
            payment_status='paid',
            order_number='TTTEST789',
        )
        response = self.client.post(
            f'/api/v1/orders/{order.id}/rate/',
            {'rating': 5, 'comment': 'Great service'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
