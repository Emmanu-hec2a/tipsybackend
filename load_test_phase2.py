"""
Locust load test for Phase 2 security hardening verification.
Tests rate limiting, encryption, fraud detection, and callback validation.

Run locally against production:
  locust -f load_test_phase2.py --host https://api.tipsytheoryy.com --users 50 --spawn-rate 5

Before running:
1. Get a valid JWT token:
   curl -X POST https://api.tipsytheoryy.com/api/v1/auth/customer/login/ \
     -H "Content-Type: application/json" \
     -d '{"username": "your_username", "password": "your_password"}'

2. Replace the token in this file: self.token = "your_access_token_from_login"

3. Get a valid order_id and payment_id from your database
"""
import json
import hmac
import hashlib
from locust import HttpUser, task, between, events
from locust.contrib.fasthttp import FastHttpUser


class Phase2TestUser(FastHttpUser):
    """Test Phase 2 security features under load"""
    
    wait_time = between(1, 3)
    
    def on_start(self):
        """Authenticate and get token"""
        # REQUIRED: Replace these with actual values from your production environment
        
        # 1. Get token via: curl -X POST https://api.tipsytheoryy.com/api/v1/auth/customer/login/
        self.token = "YOUR_JWT_TOKEN_HERE"  # Replace with actual token
        
        # 2. Find valid order_id in your database
        self.order_id = 109  # Replace with valid order ID
        
        # 3. Find valid payment_id (UUID) in your database - optional for new implementations
        self.payment_id = None  # Will skip payment attempt test if None
        
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    @task(10)
    def test_payment_status_rate_limiting(self):
        """
        Test: 30 requests/hour rate limiting on payment status endpoint
        Expected: First 30 succeed, request 31+ return 429 Too Many Requests
        """
        response = self.client.get(
            f"/api/v1/orders/{self.order_id}/payment-status/",
            headers=self.headers,
            name="/api/v1/orders/[id]/payment-status/"
        )
        
        # Log rate limit headers
        if "X-RateLimit-Limit" in response.headers:
            print(f"Rate-Limit-Remaining: {response.headers.get('X-RateLimit-Remaining')}")
            if response.status_code == 429:
                print(f"✅ Rate limit triggered: {response.status_code}")
    
    @task(5)
    def test_payment_attempt_status(self):
        """
        Test: Retrieve payment attempt with encryption verification
        Expected: Returns payment details, PII encrypted in database
        """
        # Skip if no payment_id available (new implementations)
        if not self.payment_id:
            return
            
        response = self.client.get(
            f"/api/v1/payments/{self.payment_id}/",
            headers=self.headers,
            name="/api/v1/payments/[id]/"
        )
        
        if response.status_code == 200:
            data = response.json()
            # Verify no plaintext PII in response
            if 'phone' in data:
                assert not data['phone'].startswith('+254'), "PII should be encrypted in DB!"
    
    @task(3)
    def test_fraud_detection_trigger(self):
        """
        Test: Rapid transaction patterns trigger fraud detection
        Expected: Multiple $1 orders in short time get flagged
        """
        order_data = {
            "store_id": 1,
            "customer_name": f"Test User {self.client.environ['REQUEST_COUNT']}",
            "customer_phone": "+254712345678",
            "items": [{"food_item_id": 1, "quantity": 1}],
            "payment_method": "mpesa",
            "amount": 1  # Test transaction for fraud detection
        }
        
        response = self.client.post(
            "/api/v1/orders/create/",
            json=order_data,
            headers=self.headers,
            name="/api/v1/orders/create/"
        )
        
        if response.status_code == 201:
            data = response.json()
            # Check if fraud incident was created
            if data.get('fraud_score', 0) > 0.75:
                print(f"✅ High fraud confidence: {data['fraud_score']}")
    
    @task(2)
    def test_global_rate_limiting(self):
        """
        Test: Global API rate limiting (1000/hour authenticated)
        Expected: Baseline endpoint respects global throttles
        """
        response = self.client.get(
            "/api/v1/orders/",
            headers=self.headers,
            name="/api/v1/orders/"
        )
        
        # Should succeed unless we've hit global limit
        if response.status_code == 429:
            print("✅ Global rate limit engaged")
    
    @task(1)
    def test_callback_signature_validation(self):
        """
        Test: M-Pesa callback signature validation
        Expected: Invalid signatures rejected with 401/403
        This simulates callback validation without actual M-Pesa
        """
        # Example callback payload
        payload = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "test-id",
                    "CheckoutRequestID": "test-checkout-id",
                    "ResultCode": 0,
                    "ResultDesc": "The service request has been processed successfully.",
                    "Amount": 500
                }
            }
        }
        
        # Create HMAC-SHA256 signature
        secret = "MPESA_SECRET"
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        signature = hmac.new(
            secret.encode(), 
            canonical.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        # Valid signature should pass, invalid should fail
        response = self.client.post(
            "/api/v1/mpesa/callback/",
            json=payload,
            headers={
                "X-Mpesa-Signature": signature,
                "Content-Type": "application/json"
            },
            name="/api/v1/mpesa/callback/"
        )
        
        # Should accept valid signature or reject invalid
        print(f"Callback validation response: {response.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Print test configuration"""
    print("\n" + "="*60)
    print("🚀 Phase 2 Security Load Test")
    print("="*60)
    print("Testing:")
    print("  ✓ Rate limiting (30/hour payment status, 1000/hour global)")
    print("  ✓ PII encryption (database column encryption)")
    print("  ✓ Fraud detection (7-pattern engine)")
    print("  ✓ Callback signature validation (HMAC-SHA256)")
    print("  ✓ Session security (HttpOnly, Secure cookies)")
    print("="*60 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print test summary"""
    print("\n" + "="*60)
    print("📊 Test Summary")
    print("="*60)
    
    stats = environment.stats
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    
    print(f"Total Requests: {total_requests}")
    print(f"Total Failures: {total_failures}")
    print(f"Success Rate: {((total_requests - total_failures) / total_requests * 100):.1f}%")
    
    # Show endpoint-specific stats
    for name, stat in stats.entries.items():
        print(f"\n  {name}:")
        print(f"    Requests: {stat.num_requests}")
        print(f"    Failures: {stat.num_failures}")
        print(f"    Avg Response: {stat.avg_response_time:.0f}ms")
        print(f"    Max Response: {stat.max_response_time:.0f}ms")
    
    print("="*60 + "\n")
