# Phase 2 Quick Reference - Implementation Checklist

**Status:** PLANNING COMPLETE - Ready to begin  
**Date:** 2026-08-24  
**Total Effort:** 41-50 hours (5-6 dev days)  

---

## All 9 High-Severity Fixes at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│ PRIORITY 1 (Start First - Day 1)                            │
├─────────────────────────────────────────────────────────────┤
│ 1. PII Masking in Logs                    [4-6 hrs]         │
│    → Mask phone, email, amounts in logs                     │
│    → Files: logging_filters.py, mpesa_utils.py             │
│                                                              │
│ 2. Session Security Hardening            [2-3 hrs]          │
│    → HttpOnly, Secure, SameSite cookies                     │
│    → File: config/settings.py                              │
│                                                              │
│ 3. CORS Security Hardening               [1-2 hrs]          │
│    → Whitelist allowed origins only                        │
│    → File: config/settings.py                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ PRIORITY 2 (Day 2)                                          │
├─────────────────────────────────────────────────────────────┤
│ 4. Rate Limiting: Payment Status Polling [3-4 hrs]          │
│    → Max 30 status checks per hour/user                     │
│    → Files: permissions.py, rate_limiting.py               │
│                                                              │
│ 5. API Rate Limiting (Global)            [3-4 hrs]          │
│    → 1000 req/hour (auth), 100 (anon)                      │
│    → Files: permissions.py, views.py                       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ PRIORITY 3 (Day 3)                                          │
├─────────────────────────────────────────────────────────────┤
│ 6. Callback IP Validation (Safaricom)    [3-4 hrs]          │
│    → Reject callbacks from non-Safaricom IPs               │
│    → Files: callback_validation.py, views.py               │
│    → REQUIRES: Safaricom IP whitelist                       │
│                                                              │
│ 7. Idempotency Strengthening             [2-3 hrs]          │
│    → UUID + customer binding + expiration                  │
│    → Files: order_idempotency.py                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ PRIORITY 4 (Days 4-5)                                       │
├─────────────────────────────────────────────────────────────┤
│ 8. Database Encryption at Rest           [4-5 hrs]          │
│    → PostgreSQL encryption (pgcrypto)                      │
│    → Files: models.py, encryption_utils.py                 │
│    → REQUIRES: Railway DB access                            │
│                                                              │
│ 9. Incident Response Runbook             [6-8 hrs]          │
│    → 5 detailed runbooks + contact list                    │
│    → Files: INCIDENT_RESPONSE_*.md                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Day-by-Day Implementation Schedule

### DAY 1: Core Security Foundation (6-11 hours)

**Morning (1-2 hrs): PII Masking**
```
Files: urbanfoods/logging_filters.py (NEW)
       urbanfoods/mpesa_utils.py (UPDATE)
       urbanfoods/payment_initiation.py (UPDATE)
       config/settings.py (UPDATE)

Tasks:
□ Create logging filter class
□ Define PII patterns (phone, email, card, ID)
□ Update all payment-related log statements
□ Test log output shows masking
□ Verify sensitive data not exposed
```

**Afternoon (2-3 hrs): Session Security**
```
Files: config/settings.py (UPDATE)

Tasks:
□ Update SESSION_COOKIE_HTTPONLY = True
□ Update SESSION_COOKIE_SECURE = True
□ Update SESSION_COOKIE_SAMESITE = "Lax"
□ Update SESSION_COOKIE_AGE = 3600 (1 hour)
□ Update CSRF_COOKIE_SECURE = True
□ Test with browser dev tools
□ Verify cookies have correct flags
```

**Late Afternoon (1-2 hrs): CORS Security**
```
Files: config/settings.py (UPDATE)

Tasks:
□ Define CORS_ALLOWED_ORIGINS (exact list)
□ Remove "*" wildcard
□ Test with curl from allowed/disallowed origins
□ Verify only allowed origins work
```

**Expected Result:** ✅ All basic security settings hardened

---

### DAY 2: Rate Limiting (7-8 hours)

**Morning (3-4 hrs): Payment Status Rate Limiting**
```
Files: urbanfoods/rate_limiting.py (NEW)
       urbanfoods/permissions.py (UPDATE)
       urbanfoods/api_v1_customer_views.py (UPDATE)

Tasks:
□ Create rate limiting class using Redis
□ Define per-user limits (30 requests/hour for status)
□ Apply to payment status endpoint
□ Test rate limit enforcement
□ Verify 429 response after limit
□ Add CloudWatch monitoring
```

**Afternoon (4-5 hrs): Global API Rate Limiting**
```
Files: urbanfoods/permissions.py (UPDATE)
       urbanfoods/api_v1_customer_views.py (UPDATE)
       urbanfoods/api_v1_partner_views.py (UPDATE)

Tasks:
□ Create global throttle classes
□ Define auth user limit: 1000 req/hour
□ Define anonymous limit: 100 req/hour
□ Define IP limit: 10,000 req/hour
□ Apply to all list/create endpoints
□ Test with load test (1000 concurrent)
□ Verify Retry-After header returned
```

**Expected Result:** ✅ DOS and brute force attacks prevented

---

### DAY 3: Validation & IP Security (6-8 hours)

**Morning (3-4 hrs): Callback IP Validation**
```
Files: urbanfoods/callback_validation.py (NEW)
       urbanfoods/api_v1_customer_views.py (UPDATE)

Tasks:
□ Create callback validation class
□ Validate IP against Safaricom whitelist
□ Validate HMAC-SHA256 signature
□ Validate timestamp (within 5 minutes)
□ Implement exponential backoff retry
□ Test with valid/invalid IPs
□ Log all rejections
□ Monitor for spoofing attempts
```

**Afternoon (3-4 hrs): Idempotency Strengthening**
```
Files: urbanfoods/order_idempotency.py (UPDATE)
       urbanfoods/payment_initiation.py (UPDATE)

Tasks:
□ Replace MD5 with UUID generation
□ Bind to customer_id + phone_number
□ Add 24-hour expiration
□ Validate signature (HMAC)
□ Check for token reuse
□ Return 400 if parameters different
□ Test idempotency enforcement
□ Verify no duplicate payments
```

**Expected Result:** ✅ Fake callbacks rejected, payment fraud prevented

---

### DAY 4: Data Protection (4-5 hours)

**Full Day: Database Encryption at Rest**
```
Files: config/settings.py (UPDATE)
       urbanfoods/models.py (UPDATE)
       urbanfoods/encryption_utils.py (NEW)
       New migration: encrypt PII columns

Tasks:
□ Enable pgcrypto on Railway PostgreSQL
□ Create encryption utility functions
□ Encrypt PII columns: phone_number, email, user_id
□ Create migration to encrypt existing data
□ Update model methods to decrypt on read
□ Test encryption/decryption
□ Verify data encrypted at rest
□ No performance regression
```

**Expected Result:** ✅ Database breach impact minimized

---

### DAY 5: Documentation & Cleanup (6-8 hours)

**Morning/Afternoon: Incident Response Runbooks**
```
Files: INCIDENT_RESPONSE_RUNBOOK.md (NEW)
       INCIDENT_RESPONSE_FRAUD.md (NEW)
       INCIDENT_RESPONSE_BREACH.md (NEW)
       INCIDENT_RESPONSE_RANSOMWARE.md (NEW)
       INCIDENT_RESPONSE_CONTACTS.md (NEW)

Tasks:
□ Define fraud detection procedures
□ Create data breach response playbook
□ Document ransomware recovery steps
□ Create DDoS response procedure
□ Create insider threat checklist
□ Document third-party breach response
□ Create emergency contact list
□ Add incident severity levels
□ Define escalation procedures
□ Add training requirements
```

**Late Afternoon: Testing & Verification**
```
Tasks:
□ Unit tests for all 9 fixes
□ Integration tests in staging
□ Load testing (no regression)
□ Security review checklist
□ Compliance checklist (PCI DSS)
□ Documentation complete
□ Code review ready
```

**Expected Result:** ✅ All 9 fixes complete + documented

---

## Pre-Implementation Checklist

Before starting Phase 2, verify:

- [ ] **Safaricom IP Whitelist** - Obtain from Safaricom documentation or support
  - Production IPs for callback validation
  - Backup/secondary IPs

- [ ] **CORS Allowed Origins** - Confirm all frontend domains:
  - Flutter app domain: `https://app.tipsytheoryy.com`
  - Merchant portal domain: `https://merchant.tipsytheoryy.com`
  - Admin dashboard domain: `https://admin.tipsytheoryy.com`
  - Development domain (if needed): `https://dev.tipsytheoryy.com`

- [ ] **Railway PostgreSQL** - Verify:
  - Database user has pgcrypto extension privilege
  - Can create functions and extensions
  - Backup created before encryption

- [ ] **Redis Access** - Verify:
  - Rate limiting requires Redis connection
  - Redis accessible from application
  - Connection string configured

- [ ] **Team Briefing** - Complete:
  - Share Phase 2 plan with team
  - Assign code reviewers
  - Schedule testing window
  - Notify support of deployment

---

## Implementation Order (Critical)

```
MUST DO IN THIS ORDER:

1️⃣  Session Security + CORS (independent, low risk)
2️⃣  PII Masking (needed before rate limiting logging)
3️⃣  Rate Limiting (needs logging in place)
4️⃣  Callback IP Validation (needs Redis for rate limit)
5️⃣  Idempotency Strengthening (final validation layer)
6️⃣  Database Encryption (requires all else done first)
7️⃣  Incident Response (documentation only, can be parallel)
```

**DO NOT:**
- ❌ Start database encryption before other fixes (complex rollback)
- ❌ Deploy callback IP validation without IP list (blocks all callbacks)
- ❌ Activate rate limiting without testing (blocks legitimate users)
- ❌ Change session settings in production (forces logout)

---

## Rollback & Contingency

### If Phase 2 Breaks Payments
```bash
# Immediate rollback (all fixes can be toggled):
USE_PII_MASKING=false
USE_SESSION_SECURITY=false
USE_RATE_LIMITING=false
USE_CALLBACK_IP_VALIDATION=false
USE_IDEMPOTENCY_CHECK=false
USE_DATABASE_ENCRYPTION=false

# Feature flags in settings.py prevent issues
```

### Critical Issues That Require Code Revert
- Callback IP validation rejecting ALL callbacks
- Rate limiting too aggressive (blocks users)
- Idempotency blocking legitimate payments

---

## Monitoring During Phase 2 Deployment

```
Real-time Alerts:
🔴 CRITICAL:
  - Payment initiation errors > 5/minute
  - M-Pesa callback failures > 10/minute
  - Database encryption errors

🟡 WARNING:
  - Rate limit rejections > 100/hour
  - Callback validation failures increasing
  - Idempotency token errors

🟢 INFO:
  - Log masking verification (correct masking detected)
  - Session timeout events (expected increase)
  - CORS rejections (should be near 0)
```

---

## Success Criteria Per Fix

### ✅ PII Masking
- Logs show "+254712345" instead of "+254712345678"
- Email shows "jo***@example.com"
- Amount shows "50***" instead of "50000"
- No plaintext PII in CloudWatch logs

### ✅ Session Security
- Session cookies have HttpOnly flag
- Session cookies have Secure flag
- Session cookies have SameSite=Lax
- Session expires after 1 hour of inactivity
- No XSS can steal session cookie

### ✅ Rate Limiting (Polling)
- 1st-30th status checks succeed
- 31st status check returns 429
- Retry-After header included
- Logs show "Rate limit exceeded"
- Redis counter increments correctly

### ✅ Rate Limiting (Global)
- Authenticated user: 1000 req/hour
- Anonymous user: 100 req/hour
- After limit: Returns 429
- Clients see Retry-After header
- Load test: No DOS impact

### ✅ Callback IP Validation
- Valid Safaricom IP: Callback processed ✓
- Invalid IP: Callback rejected ✗
- Missing signature: Callback rejected ✗
- Old timestamp: Callback rejected ✗
- Logs show "Callback rejected: invalid IP"

### ✅ Idempotency Strengthening
- Token format: UUID (not MD5)
- Token bound to: customer_id + phone_number
- Token expiration: 24 hours
- Replay attack: Returns 400 (Bad Request)
- Different parameters: Returns 400

### ✅ Database Encryption
- Data encrypted at rest on disk
- `SELECT * FROM customer` shows encrypted blobs
- Application can decrypt and read normally
- Performance impact < 10%
- No visible plaintext data

### ✅ CORS Security
- `Origin: https://allowed.com` → 200 OK
- `Origin: https://malicious.com` → 403 CORS Error
- `Origin: *` → 403 CORS Error
- Wildcard origins rejected
- Only exact origins allowed

### ✅ Incident Response
- Runbooks document all procedures
- Emergency contacts defined
- Decision trees for each scenario
- Training materials created
- Regular drills scheduled

---

## Phase 2 Completion Checklist

- [ ] All 9 fixes implemented
- [ ] Unit tests passing (>80% coverage)
- [ ] Integration tests in staging passing
- [ ] Code review completed by senior engineer
- [ ] Security review passed
- [ ] Load test: No regression
- [ ] Performance test: Latency ±10%
- [ ] Staging deployment: 24 hours no issues
- [ ] Monitoring alerts configured
- [ ] Documentation complete
- [ ] Incident response runbooks signed off
- [ ] Team training completed
- [ ] Ready for production deployment

---

## Next Steps

1. ✅ **Review this plan** - Approve approach
2. ✅ **Gather prerequisites** - Safaricom IPs, CORS origins, etc.
3. ✅ **Set up environment** - Redis, testing tools, monitoring
4. → **Start DAY 1** - PII Masking + Session Security + CORS
5. → **Continue Days 2-5** - Complete implementation
6. → **Testing Week** - Staging validation + security review
7. → **Production Deployment** - Roll out Phase 2

---

**Ready to begin Phase 2 implementation?**

**Or would you prefer to:**
1. Complete staging deployment of Phase 1 first? 
2. Review specific Phase 2 fixes in detail?
3. Get help setting up prerequisites (Safaricom IPs, etc.)?

