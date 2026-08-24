# Phase 1 Staging Deployment Guide

**Objective:** Safely deploy Phase 1 critical fixes to staging environment for comprehensive testing  
**Estimated Duration:** 2-4 hours  
**Risk Level:** LOW (staging environment, no production data)  
**Date:** 2026-08-24  

---

## Pre-Deployment Checklist

### Code Review ✓
- [x] All 5 critical fixes implemented
- [x] No breaking changes to existing payment flow
- [x] All imports verified correct
- [x] Migration file numbered correctly (0073)
- [x] All environment variables documented

### Staging Environment Setup
- [ ] Staging database backup created
- [ ] AWS Secrets Manager staging account access verified
- [ ] M-Pesa sandbox credentials available
- [ ] Staging domain/URL confirmed
- [ ] SSL certificate for staging valid

---

## Step 1: Backup Staging Database

Before deploying, backup the staging database:

```bash
# SSH into Railway staging server
railway link

# Backup database
pg_dump $DATABASE_URL > staging_backup_$(date +%Y%m%d_%H%M%S).sql

# Verify backup
ls -lh staging_backup_*.sql
```

**Expected Output:**
```
staging_backup_20260824_143022.sql    1.2G  ...
```

---

## Step 2: Deploy Code to Staging

### Option A: GitHub Actions (Recommended)
```bash
git checkout main
git pull origin main
git tag -a v0.1.0-phase1-staging -m "Phase 1 staging deployment"
git push origin v0.1.0-phase1-staging

# Trigger staging deployment via GitHub Actions
# Wait for deployment to complete (~5-10 minutes)
# Monitor at: https://github.com/tipsytheoryy/backend/actions
```

### Option B: Manual SSH Deployment
```bash
# SSH into staging server
ssh staging.tipsytheoryy.com

# Navigate to app directory
cd /app

# Pull latest code
git pull origin main

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create/collect migration
python manage.py makemigrations

# Run migrations (DRY RUN FIRST)
python manage.py migrate --plan

# If satisfied, run actual migration
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Restart services
systemctl restart gunicorn
systemctl restart celery

# Verify deployment
curl -s https://staging.tipsytheoryy.com/api/v1/health/
```

**Expected Output:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "connected"
}
```

---

## Step 3: Set Up AWS Secrets Manager on Staging

Run the AWS setup script:

```bash
cd /path/to/tipsytheoryy

# Run AWS infrastructure setup (staging)
python aws_setup_scripts/setup_secrets_manager.py \
  --environment staging \
  --region us-east-1 \
  --create-kms-key

# Verify setup
python aws_setup_scripts/verify_secrets_manager.py --environment staging
```

**Expected Output:**
```
✓ AWS KMS key created: alias/tipsy-payment-keys-staging
✓ AWS Secrets Manager enabled
✓ IAM role configured: tipsy-payment-service-staging
✓ Test secret creation successful
✓ All checks passed
```

---

## Step 4: Configure Environment Variables on Staging

Update staging environment variables:

```bash
# On Railway staging environment
railway variables set \
  USE_AWS_SECRETS_MANAGER=true \
  AWS_REGION=us-east-1 \
  AWS_KMS_KEY_ID=alias/tipsy-payment-keys-staging \
  AWS_ROTATION_LAMBDA_ARN=arn:aws:lambda:us-east-1:ACCOUNT:function:rotate-mpesa-creds-staging
```

Or manually in Railway UI:
1. Go to Railway project → Staging service
2. Environment tab
3. Add variables (see example in Step 5)

**Verify variables loaded:**
```bash
curl -s https://staging.tipsytheoryy.com/api/v1/config/env-check/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.secrets_manager'
```

Expected:
```json
{
  "enabled": true,
  "region": "us-east-1",
  "kms_key": "alias/tipsy-payment-keys-staging"
}
```

---

## Step 5: Migrate M-Pesa Credentials to Secrets Manager

### 5a. Dry-Run First (NO CHANGES)
```bash
# SSH into staging
ssh staging.tipsytheoryy.com
cd /app

# Activate venv
source venv/bin/activate

# Dry-run migration
python manage.py migrate_credentials_to_secrets_manager \
  --environment staging \
  --dry-run

# Output shows what WOULD be migrated (doesn't change anything)
```

**Expected Output:**
```
Dry-run mode: Changes will NOT be applied

Stores to migrate:
  - Store #1 (Urban Foods KTown): 254712345678 → Secrets Manager
  - Store #2 (Casual Vibes): 254723456789 → Secrets Manager

Credentials in Secrets Manager (after migration):
  - tipsytheoryy/store/1/mpesa-credentials
  - tipsytheoryy/store/2/mpesa-credentials

Total stores: 2
Estimated time: ~30 seconds
```

### 5b. Run Actual Migration
```bash
# If dry-run looks good, run actual migration
python manage.py migrate_credentials_to_secrets_manager \
  --environment staging

# Output shows credentials migrated
```

**Expected Output:**
```
Migrating credentials to AWS Secrets Manager (staging)...

✓ Store #1 (Urban Foods KTown): Credentials migrated to Secrets Manager
✓ Store #2 (Casual Vibes): Credentials migrated to Secrets Manager

Summary:
  Successfully migrated: 2
  Failed: 0
  Skipped: 0

Credentials are now stored in AWS Secrets Manager with KMS encryption.
Database Fernet encryption still available as fallback.

Next: Monitor logs for any credential retrieval issues during testing.
```

### 5c. Verify Credentials Accessible
```bash
# Test credential retrieval
python manage.py shell

# In Django shell:
from urbanfoods.secrets_manager import get_hybrid_credential_store
store = get_hybrid_credential_store()
creds = store.get_store_credentials(store_id=1)
print(f"Consumer Key: {creds['consumer_key'][:10]}...")
print(f"Status: {'✓ Retrieved from Secrets Manager' if creds else '✗ Failed'}")
```

---

## Step 6: Restart Services with New Configuration

```bash
# Restart Django app
railway redeploy

# Wait for deployment to complete
railway status

# Verify health
curl -s https://staging.tipsytheoryy.com/api/v1/health/ | jq .

# Check logs for errors
railway logs --tail=50
```

---

## Step 7: Integration Testing

### 7a. Test Certificate Pinning

```bash
# Test M-Pesa API call with certificate pinning
curl -X POST https://staging.tipsytheoryy.com/api/v1/mpesa/test-pinning/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json"

# Expected output:
# {
#   "status": "success",
#   "message": "Certificate pinning validated",
#   "ssl_version": "TLSv1.2",
#   "certificate": "Safaricom M-Pesa API"
# }
```

**Verify in logs:**
```bash
railway logs | grep "certificate_pinning"
# Expected: No SSL Certificate Pinning Failure messages
```

### 7b. Test Phone Validation

```bash
# Test valid Kenya phone
curl -X POST https://staging.tipsytheoryy.com/api/v1/payments/initiate/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+254712345678",
    "amount_cents": 50000
  }'

# Expected: Payment initiated successfully

# Test invalid phone
curl -X POST https://staging.tipsytheoryy.com/api/v1/payments/initiate/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+254812345678",
    "amount_cents": 50000
  }'

# Expected: 
# {
#   "error": "Invalid phone number format",
#   "details": "Phone must be Kenya number: +254712345678 or 0712345678"
# }
```

**Verify in logs:**
```bash
railway logs | grep "phone_validation"
# Expected: Validation successful messages
```

### 7c. Test Rate Limiting

```bash
# Send 4 STK pushes in rapid succession (same phone, same hour)
for i in {1..4}; do
  curl -X POST https://staging.tipsytheoryy.com/api/v1/payments/initiate/ \
    -H "Authorization: Bearer $CUSTOMER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "phone_number": "+254712345678",
      "amount_cents": 50000
    }' -s | jq '.status'
  sleep 1
done

# Expected: First 3 succeed, 4th returns:
# {
#   "error": "Rate limit exceeded",
#   "details": "Maximum 3 STK pushes per phone per hour"
# }
```

**Verify in logs:**
```bash
railway logs | grep "STK rate limit"
# Expected: "STK rate limit exceeded for +254712345678"
```

### 7d. Test Secure JWT Authentication

```bash
# Test query parameter JWT (should FAIL)
curl https://staging.tipsytheoryy.com/api/v1/orders/?token=$JWT_TOKEN

# Expected:
# {
#   "detail": "Authentication via query parameters is not allowed. Use Authorization header: Authorization: Bearer <token>"
# }

# Test Authorization header JWT (should SUCCEED)
curl -H "Authorization: Bearer $JWT_TOKEN" \
  https://staging.tipsytheoryy.com/api/v1/orders/

# Expected: Orders list returned
```

**Verify security log:**
```bash
railway logs | grep "SECURITY VIOLATION"
# Expected: "SECURITY VIOLATION: Query parameter JWT auth attempted"
```

### 7e. Test Admin Audit Logging

```bash
# Create payment attempt via admin
curl -X POST https://staging.tipsytheoryy.com/admin/urbanfoods/paymentattempt/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+254712345678", "amount_cents": 50000}'

# Mark for manual review (admin action)
curl -X POST https://staging.tipsytheoryy.com/admin/urbanfoods/paymentattempt/1/mark_manual_review/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "High value transaction - manual verification needed"}'

# Verify audit log entry created
curl https://staging.tipsytheoryy.com/admin/urbanfoods/paymentauditlog/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.results[0]'

# Expected:
# {
#   "admin_user": "admin@tipsytheoryy.com",
#   "action": "manual_review",
#   "reason": "High value transaction - manual verification needed",
#   "object_id": "1",
#   "ip_address": "203.0.113.45",
#   "timestamp": "2026-08-24T14:30:00Z"
# }
```

---

## Step 8: Full Payment Flow Test

### 8a. End-to-End STK Push Flow

```bash
# 1. Customer initiates payment
PAYMENT_ID=$(curl -X POST https://staging.tipsytheoryy.com/api/v1/payments/initiate/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+254712345678",
    "amount_cents": 100000
  }' | jq -r '.id')

echo "Payment ID: $PAYMENT_ID"

# 2. Poll for status (with rate limiting)
for i in {1..30}; do
  STATUS=$(curl https://staging.tipsytheoryy.com/api/v1/payments/$PAYMENT_ID/status/ \
    -H "Authorization: Bearer $CUSTOMER_TOKEN" | jq -r '.status')
  
  echo "[$i] Status: $STATUS"
  
  if [ "$STATUS" = "success" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  
  sleep 2
done

# 3. Verify final status
curl https://staging.tipsytheoryy.com/api/v1/payments/$PAYMENT_ID/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" | jq .
```

### 8b. Test M-Pesa Callback Processing

```bash
# Simulate M-Pesa callback (from staging M-Pesa sandbox)
curl -X POST https://staging.tipsytheoryy.com/api/v1/mpesa/callback/ \
  -H "Content-Type: application/json" \
  -d '{
    "Body": {
      "stkCallback": {
        "MerchantRequestID": "16813-1590080117-1",
        "CheckoutRequestID": "ws_CO_DMZ_123456789",
        "ResultCode": 0,
        "ResultDesc": "The service request has been accepted successfully.",
        "CallbackMetadata": {
          "Item": [
            {"Name": "Amount", "Value": 1000},
            {"Name": "MpesaReceiptNumber", "Value": "NEF61H8J02"},
            {"Name": "PhoneNumber", "Value": "254712345678"}
          ]
        }
      }
    }
  }'

# Expected: 204 No Content (callback processed)

# Verify payment status updated
curl https://staging.tipsytheoryy.com/api/v1/payments/$PAYMENT_ID/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" | jq '.status'

# Expected: "success"
```

---

## Step 9: Load Testing

### 9a. Test Concurrent Payment Requests

```bash
# Generate 10 concurrent payment requests
ab -n 100 -c 10 \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -p payment_request.json \
  https://staging.tipsytheoryy.com/api/v1/payments/initiate/

# payment_request.json:
# {
#   "phone_number": "+254712345678",
#   "amount_cents": 50000
# }

# Expected: 
# - All requests successful (200 OK)
# - < 500ms response time
# - No certificate pinning failures
# - No database connection errors
```

### 9b. Performance Metrics

```bash
# Load test with Apache Bench and capture metrics
ab -n 1000 -c 50 \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  https://staging.tipsytheoryy.com/api/v1/payments/initiate/ \
  | tee load_test_results.txt

# Analyze results
grep "Requests per second" load_test_results.txt
grep "Time per request" load_test_results.txt
grep "Failed requests" load_test_results.txt
```

**Expected Performance:**
- Requests/sec: > 100
- Time per request: < 500ms
- Failed requests: 0

---

## Step 10: Security Verification

### 10a. Check SSL/TLS Configuration

```bash
# Verify TLS version enforcement
openssl s_client -connect staging.tipsytheoryy.com:443 \
  -tls1_1 2>&1 | grep "Protocol"

# Expected: "Protocol : TLSv1.2" (TLS 1.1 should be rejected)

# Verify certificate chain
openssl s_client -connect staging.tipsytheoryy.com:443 \
  -showcerts 2>&1 | grep "subject="

# Expected: Valid staging certificate
```

### 10b. Verify Audit Logging

```bash
# Check audit logs for any suspicious activities
railway logs | grep "PaymentAuditLog"

# Count manual review actions
railway logs | grep "manual_review" | wc -l

# Check for security violations
railway logs | grep "SECURITY VIOLATION"

# Expected: No unexpected violations
```

### 10c. Check AWS Secrets Manager Access

```bash
# Verify credentials retrieved successfully
railway logs | grep "Retrieved credentials from Secrets Manager"

# Expected: Multiple successful retrievals during testing

# Check for credential errors
railway logs | grep "ERROR.*Secrets Manager"

# Expected: No errors
```

---

## Step 11: Monitoring & Alerts Verification

### 11a. Check CloudWatch Dashboards

```bash
# Verify dashboards created
aws cloudwatch list-dashboards \
  --region us-east-1 | jq '.DashboardEntries[] | .DashboardName'

# Expected dashboards:
# - TipsyTheoryy-Payment-Health-Staging
# - TipsyTheoryy-Certificate-Pinning-Staging
# - TipsyTheoryy-Phone-Validation-Staging
```

### 11b. Trigger Test Alerts

```bash
# Generate test certificate pinning failure
curl -k https://invalid-cert.example.com/  # This should fail

# Check CloudWatch alarm
aws cloudwatch get-metric-statistics \
  --namespace TipsyTheoryy \
  --metric-name CertificatePinningFailures \
  --dimensions Name=Environment,Value=staging \
  --statistics Sum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --region us-east-1
```

---

## Step 12: Deployment Success Criteria

- [ ] All code deployed to staging successfully
- [ ] No errors in application logs after restart
- [ ] Database migration completed without errors
- [ ] AWS Secrets Manager configured and accessible
- [ ] M-Pesa credentials migrated to Secrets Manager
- [ ] All 5 integration tests pass (pinning, validation, rate limiting, JWT, audit)
- [ ] End-to-end payment flow works (STK push → callback → status update)
- [ ] Load test passes (100+ req/sec, <500ms latency)
- [ ] Security logs show no unexpected violations
- [ ] Admin audit logs capturing all payment actions
- [ ] CloudWatch dashboards populated with metrics
- [ ] No performance regression (latency +60-120ms acceptable)

---

## Step 13: Sign-Off & Documentation

### 13a. Document Test Results

Create `PHASE_1_STAGING_TEST_RESULTS.md`:
```markdown
# Phase 1 Staging Test Results

**Test Date:** 2026-08-24  
**Tester:** [Your Name]  
**Status:** ✓ ALL TESTS PASSED  

## Test Summary
- Certificate Pinning: ✓ PASS
- Phone Validation: ✓ PASS
- Rate Limiting: ✓ PASS
- Secure JWT: ✓ PASS
- Audit Logging: ✓ PASS
- End-to-End Flow: ✓ PASS
- Load Test: ✓ PASS (150 req/sec)
- Security: ✓ PASS (No violations)

## Issues Found
None

## Recommendations
Ready for production deployment

## Sign-Off
Signed: [Your Name]
Date: 2026-08-24
```

### 13b. Update Runbook

Add Phase 1 section to production deployment runbook:
- AWS Secrets Manager setup steps
- Environment variables to set
- Database migrations to apply
- Credential migration procedure
- Rollback steps if needed

---

## Troubleshooting

### Issue: Certificate Pinning Failure
**Error:** `SSL Certificate Pinning Failure on M-Pesa API`

**Solution:**
```bash
# Check M-Pesa certificate
openssl s_client -connect api.safaricom.co.ke:443 -showcerts

# Update certificate hash in tls_pinning.py
# Restart service
railway redeploy
```

### Issue: Secrets Manager Credential Retrieval Fails
**Error:** `ClientError: An error occurred (InvalidRequest) when calling the GetSecretValue operation`

**Solution:**
```bash
# Verify IAM role permissions
aws iam list-role-policies --role-name tipsy-payment-service-staging

# Verify KMS key access
aws kms describe-key --key-id alias/tipsy-payment-keys-staging

# Check environment variables
railway variables get USE_AWS_SECRETS_MANAGER
```

### Issue: Rate Limiting Too Strict
**Error:** `STK rate limit exceeded` for legitimate requests

**Solution:**
```python
# Edit urbanfoods/phone_validation.py
MAX_STK_PUSHES_PER_HOUR = 5  # Increase from 3 to 5
# Restart service
```

### Issue: Query Parameter JWT Still Working
**Error:** Tokens in query params not being rejected

**Solution:**
```bash
# Verify SecureJWTAuthentication is used
grep -r "SecureJWTAuthentication" urbanfoods/

# Restart service
railway redeploy
```

---

## Rollback Procedure (If Needed)

```bash
# 1. Restore database from backup
psql $DATABASE_URL < staging_backup_20260824_143022.sql

# 2. Revert code to previous version
git checkout v0.0.9  # Previous production tag
git push --force origin main

# 3. Disable AWS Secrets Manager fallback
railway variables set USE_AWS_SECRETS_MANAGER=false

# 4. Redeploy
railway redeploy

# 5. Verify health
curl https://staging.tipsytheoryy.com/api/v1/health/
```

**Estimated Rollback Time:** 15-30 minutes

---

## Next Steps (After Staging Sign-Off)

1. ✅ Phase 1 staging deployment complete
2. → Schedule production deployment window
3. → Notify operations team and customer support
4. → Deploy to production (follow same procedure)
5. → Monitor production for 24 hours
6. → Begin Phase 2 implementation (high-severity fixes)

---

## Support & Escalation

**Questions about staging deployment?**
- Check logs: `railway logs --tail=100`
- Check status: `railway status`
- Rollback: See Rollback Procedure section

**Critical issues?**
- Contact: backend-devops@tipsytheoryy.com
- Escalate to: CTO (for production approval)

---

**Document Version:** 1.0  
**Last Updated:** 2026-08-24  
**Status:** READY FOR DEPLOYMENT  
