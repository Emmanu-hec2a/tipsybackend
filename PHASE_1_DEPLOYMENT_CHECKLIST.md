# Phase 1 Deployment Checklist

**Objective:** Production-ready deployment of 5 critical security fixes  
**Date:** 2026-08-24  
**Status:** READY FOR DEPLOYMENT  

---

## Pre-Deployment (48 Hours Before)

### Code Review & Testing
- [ ] All 5 critical fixes code reviewed by senior engineer
- [ ] No merge conflicts with main branch
- [ ] All unit tests passing locally
- [ ] Integration tests passing in staging environment
- [ ] Security review completed (no new vulnerabilities)

### Stakeholder Communication
- [ ] Product team notified of deployment window
- [ ] Support team briefed on Phase 1 changes
- [ ] Customer success team aware of new audit logging
- [ ] Finance team aware of AWS costs (Secrets Manager + KMS)

### Backup & Rollback Preparation
- [ ] Production database backup verified (< 24 hours old)
- [ ] Rollback procedure documented and tested
- [ ] Previous production version (v0.0.9) tagged and ready
- [ ] Rollback time estimate: 15-30 minutes

### AWS Infrastructure
- [ ] AWS Secrets Manager set up in production account
- [ ] KMS key created and tested
- [ ] IAM roles configured with correct permissions
- [ ] Monitoring dashboards and alarms configured
- [ ] SNS notifications tested (fire test alarm)

### Environment Configuration
- [ ] Production environment variables prepared:
  ```bash
  USE_AWS_SECRETS_MANAGER=true
  AWS_REGION=us-east-1
  AWS_KMS_KEY_ID=alias/tipsy-payment-keys-production
  AWS_SM_ACCESS_KEY_ID=<production-access-key>
  AWS_SM_SECRET_ACCESS_KEY=<production-secret-key>
  ```
- [ ] M-Pesa production credentials ready to migrate
- [ ] Database connection string verified (PostgreSQL on Railway)

---

## Deployment Window (Start Time: _______)

### 30 Minutes Before Deployment

- [ ] Post maintenance notice (if needed): "Payment processing temporarily unavailable"
- [ ] Notify support team deployment starting
- [ ] Verify production database is healthy
- [ ] Verify M-Pesa API is responding (smoke test)
- [ ] Verify all AWS services are operational

### Phase 1: Deploy Code (5-10 minutes)

```bash
# 1. Pull latest code
git checkout main
git pull origin main

# 2. Tag deployment
git tag -a v0.1.0-phase1 -m "Phase 1: 5 critical security fixes"
git push origin v0.1.0-phase1

# 3. Deploy to production (via GitHub Actions or manual)
railway redeploy
# OR
git push origin main:production
```

**Verification:**
- [ ] Code deployed successfully to production
- [ ] No deployment errors in logs
- [ ] Application started successfully
- [ ] Health check endpoint responding

### Phase 2: Run Database Migrations (5 minutes)

```bash
# 1. Check what migrations need to run
python manage.py migrate --plan

# 2. Run migrations
python manage.py migrate

# 3. Verify migration succeeded
python manage.py showmigrations urbanfoods
```

**Verification:**
- [ ] Migration 0073_paymentauditlog applied successfully
- [ ] No data loss
- [ ] payment_audit_log table created with correct schema
- [ ] Database still responsive

### Phase 3: Enable AWS Secrets Manager (5 minutes)

```bash
# 1. Set environment variable in Railway
railway variables set USE_AWS_SECRETS_MANAGER=true

# 2. Restart application
railway redeploy

# 3. Verify Secrets Manager accessible
curl -s https://api.tipsytheoryy.com/api/v1/health/ | jq '.secrets_manager'
# Expected: {"enabled": true, "status": "connected"}
```

**Verification:**
- [ ] Application successfully connects to AWS Secrets Manager
- [ ] No authentication errors in logs
- [ ] Credentials retrievable from Secrets Manager

### Phase 4: Migrate Credentials (10-15 minutes)

```bash
# 1. DRY RUN - verify what will be migrated (NO CHANGES)
python manage.py migrate_credentials_to_secrets_manager --dry-run

# 2. Review output and confirm looks correct

# 3. Run actual migration
python manage.py migrate_credentials_to_secrets_manager

# 4. Verify migration succeeded
python manage.py shell
# In shell:
# from urbanfoods.secrets_manager import get_hybrid_credential_store
# store = get_hybrid_credential_store()
# creds = store.get_store_credentials(store_id=1)
# print(f"Status: {creds}")  # Should return credentials successfully
```

**Verification:**
- [ ] All store credentials migrated to Secrets Manager
- [ ] Fallback to DB encryption still works
- [ ] No credential retrieval errors in logs
- [ ] No payment processing errors

### Phase 5: Smoke Testing (10-15 minutes)

```bash
# Test 1: Certificate Pinning
curl -X POST https://api.tipsytheoryy.com/api/v1/mpesa/test-pinning/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.status'
# Expected: "success"

# Test 2: Phone Validation
curl -X POST https://api.tipsytheoryy.com/api/v1/payments/initiate/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+254712345678", "amount_cents": 50000}' | jq '.status'
# Expected: "initiated"

# Test 3: JWT Query Param Rejection
curl https://api.tipsytheoryy.com/api/v1/orders/?token=$TOKEN | jq '.detail'
# Expected: "Authentication via query parameters is not allowed..."

# Test 4: Admin Audit Log
curl https://api.tipsytheoryy.com/admin/urbanfoods/paymentauditlog/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.count'
# Expected: > 0 (audit logs being created)

# Test 5: Full Payment Flow
PAYMENT_ID=$(curl -X POST https://api.tipsytheoryy.com/api/v1/payments/initiate/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+254712345678", "amount_cents": 50000}' | jq -r '.id')

curl https://api.tipsytheoryy.com/api/v1/payments/$PAYMENT_ID/ \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" | jq '.status'
# Expected: "initiated" or "pending" or "success"
```

**Verification:**
- [ ] Certificate pinning validates successfully
- [ ] Phone validation accepts valid Kenya numbers
- [ ] Query parameter JWT auth rejected
- [ ] Audit logs being created for admin actions
- [ ] Payment initiation works end-to-end

---

## Post-Deployment (Next 24 Hours)

### Hour 1: Immediate Monitoring

- [ ] Monitor CloudWatch dashboard continuously
- [ ] Check for any certificate pinning failures (CRITICAL)
- [ ] Check for any secrets retrieval errors (CRITICAL)
- [ ] Check for any unexpected JWT auth rejections (WARNING)
- [ ] Verify payment success rate > 95%

**Logs to Check:**
```bash
railway logs --tail=100 | grep ERROR
railway logs --tail=100 | grep "certificate_pinning"
railway logs --tail=100 | grep "Secrets Manager"
railway logs --tail=100 | grep "SECURITY VIOLATION"
```

### Hour 2-4: Validate All Fixes

- [ ] Certificate Pinning: M-Pesa API calls successful
- [ ] Secrets Manager: Credentials retrieved successfully
- [ ] Phone Validation: Valid numbers accepted, invalid rejected
- [ ] JWT Auth: Query params rejected, headers accepted
- [ ] Audit Logging: All admin actions logged

### Hour 4-24: Continuous Monitoring

- [ ] CloudWatch alarms functioning correctly
- [ ] SNS notifications delivering
- [ ] No unexpected error rate spikes
- [ ] No unusual admin activity
- [ ] Payment success rate stable
- [ ] Customer complaints: ZERO

**Daily Monitoring Tasks:**
```bash
# Check metrics every hour
aws cloudwatch get-metric-statistics \
  --namespace TipsyTheoryy/Payment \
  --metric-name CertificatePinningFailures \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum \
  --region us-east-1

# Check audit logs for suspicious activity
curl https://api.tipsytheoryy.com/admin/urbanfoods/paymentauditlog/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq '.results | length'
```

---

## Success Criteria

### Deployment Success (Immediate)
- [x] Code deployed to production
- [x] Database migrations applied
- [x] AWS Secrets Manager accessible
- [x] Credentials migrated successfully
- [x] All smoke tests passing

### Operational Success (24 Hours)
- [ ] Zero certificate pinning failures
- [ ] Zero secrets retrieval errors
- [ ] Zero unhandled payment exceptions
- [ ] Payment success rate > 95%
- [ ] Response time unchanged (± 100ms)
- [ ] No critical CloudWatch alarms triggered
- [ ] Admin audit logs capturing all actions
- [ ] Zero customer complaints related to Phase 1

### Security Success (48 Hours)
- [ ] No query parameter JWT attempts detected
- [ ] Phone validation preventing spoofing attempts
- [ ] Rate limiting preventing DOS attempts
- [ ] Audit logs immutable and complete
- [ ] All M-Pesa API calls validated

---

## Rollback Decision Tree

### If Certificate Pinning Fails
```
Symptom: "SSL Certificate Pinning Failure" in logs
Action:
1. Immediately set environment variable: USE_CERTIFICATE_PINNING=false
2. Restart application: railway redeploy
3. Verify payment flow works
4. Investigate certificate issue in parallel
```

### If Secrets Manager Fails
```
Symptom: "ClientError: An error occurred (InvalidRequest)"
Action:
1. Immediately set: USE_AWS_SECRETS_MANAGER=false
2. Restart application: railway redeploy
3. Fallback to DB encryption will activate
4. Verify payment flow works
5. Investigate AWS configuration
```

### If Phone Validation Too Strict
```
Symptom: Valid Kenya numbers being rejected
Action:
1. Review phone validation regex in urbanfoods/phone_validation.py
2. Check logs for specific format causing rejection
3. Update regex if needed
4. Hot-patch and redeploy
```

### If Query Param JWT Rejection Breaks Clients
```
Symptom: Mobile app auth errors
Action:
1. Mobile app must update to use Authorization header
2. Cannot revert without breaking security fix
3. Coordinate with mobile team for rapid release
4. Provide authentication header documentation
```

### If Audit Logging Causes Performance Issues
```
Symptom: Response time increased > 200ms
Action:
1. Disable AdminActionMiddleware temporarily
2. Implement async audit logging (if not already)
3. Update to batch log inserts
4. Monitor performance impact
```

### Complete Rollback (Last Resort)
```bash
# 1. Stop accepting payments
# 2. Restore database from backup
git checkout v0.0.9
git push --force origin main
railway redeploy
# 3. Disable Phase 1 features
USE_AWS_SECRETS_MANAGER=false
USE_CERTIFICATE_PINNING=false
USE_PHONE_VALIDATION=false
# 4. Restart
railway redeploy
```

**Estimated Rollback Time:** 15-30 minutes

---

## Post-Deployment Documentation

### Create Deployment Report

File: `PHASE_1_DEPLOYMENT_REPORT.md`

```markdown
# Phase 1 Deployment Report

**Deployment Date:** 2026-08-24  
**Deployment Window:** 14:00 UTC - 14:45 UTC (45 minutes)  
**Status:** ✅ SUCCESSFUL  

## Timeline
- 14:00 - Pre-deployment checks complete
- 14:05 - Code deployed to production
- 14:10 - Database migrations applied
- 14:15 - Credentials migrated to Secrets Manager
- 14:25 - Smoke tests completed successfully
- 14:45 - Deployment verified complete

## Metrics
- Payment success rate (pre): 99.2%
- Payment success rate (post): 99.3%
- Average response time (pre): 245ms
- Average response time (post): 290ms
- Certificate pinning failures: 0
- Secrets Manager errors: 0

## Issues Encountered
None

## Next Steps
1. Continue monitoring for 24 hours
2. Begin Phase 2 implementation
3. Schedule production penetration testing

## Sign-Off
Deployed By: [Your Name]
Verified By: [QA Lead]
Date: 2026-08-24
```

---

## Phase 1 Completion Sign-Off

- [ ] Deployment completed successfully
- [ ] All 5 fixes verified working
- [ ] 24-hour monitoring complete
- [ ] Deployment report created
- [ ] Team debriefing scheduled
- [ ] Phase 2 planning initiated

---

## Contact Information

**In Case of Emergency:**
- Backend DevOps: backend-devops@tipsytheoryy.com
- On-Call Engineer: [+254-XXX-XXXXX]
- CTO: cto@tipsytheoryy.com

**Escalation Procedures:**
1. Payment processing down → Immediate escalation
2. Certificate pinning failure → Immediate escalation
3. Credentials compromised → Immediate escalation
4. Data loss detected → Immediate escalation (and legal team)

---

**Document Version:** 1.0  
**Last Updated:** 2026-08-24  
**Status:** READY FOR PRODUCTION DEPLOYMENT  
