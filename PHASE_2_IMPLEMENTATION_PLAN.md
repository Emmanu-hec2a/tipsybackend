# Phase 2 Implementation Plan - High-Severity Fixes

**Objective:** Address 9 high-severity security vulnerabilities  
**Duration:** 7-10 days (full implementation + testing)  
**Status:** PLANNING  
**Date:** 2026-08-24  

---

## Overview

Phase 2 focuses on high-severity vulnerabilities that don't directly cause payment failures but create significant security risks:
- Information disclosure (PII in logs)
- Authentication/session bypass vulnerabilities
- Denial of Service vectors
- Fraud detection gaps

**Impact if not fixed:** 
- Compliance violations (PCI DSS, GDPR)
- Insider threat exposure
- Customer data breaches
- Regulatory fines (up to 4% of revenue)

---

## All 9 High-Severity Issues

### 1. **PII Masking in Logs** 🟡 HIGH

**Vulnerability:** Sensitive data (phone numbers, amounts, user IDs) visible in application logs

**Current State:**
```
2026-08-24 14:30:45 - Payment initiated: phone=+254712345678, amount=50000, customer_id=42, email=john@example.com
2026-08-24 14:30:47 - M-Pesa callback received: phone=+254712345678, receipt=NEF61H8J02, amount=50000
```

**Risk:** 
- Logs accessible to multiple engineers
- Log aggregation services (CloudWatch, Sentry) store data unencrypted
- Employee with log access can identify customers
- Regulatory violation (GDPR Article 32, PCI DSS 3.4)

**PCI DSS Requirement:** Req 3.4 - PII must be masked (show only first/last 2 digits)

**Solution:**
- Create `logging_filters.py` with PII masking functions
- Apply to all payment-related log statements
- Regex patterns for phone, email, card, ID masking
- Audit logging captures masked data

**Files to Modify:**
- `urbanfoods/mpesa_utils.py` (M-Pesa logs)
- `urbanfoods/payment_initiation.py` (payment flow logs)
- `urbanfoods/payment_service.py` (payment status logs)
- `config/settings.py` (add logging filter)
- New: `urbanfoods/logging_filters.py`

**Estimated Effort:** 4-6 hours

---

### 2. **Session Security Hardening** 🟡 HIGH

**Vulnerability:** Session cookies vulnerable to XSS/CSRF attacks and session fixation

**Current State:**
```python
# config/settings.py
SESSION_COOKIE_HTTPONLY = False  # ← XSS can steal via JavaScript
SESSION_COOKIE_SECURE = False    # ← Sent over HTTP, network sniffer can intercept
CSRF_COOKIE_SECURE = False       # ← Same issue
SESSION_COOKIE_SAMESITE = None   # ← CSRF attacks possible across sites
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # ← Long-lived sessions
SESSION_COOKIE_AGE = 1209600  # 14 days (too long)
```

**Risk:**
- XSS vulnerability: Malicious JS steals session cookie
- Network sniffer captures unencrypted session cookie
- CSRF attack: Malicious site tricks browser into payment
- Session fixation: Attacker forces known session ID on victim

**OWASP Requirement:** Session Management (A2:2021)

**Solution:**
```python
SESSION_COOKIE_HTTPONLY = True      # ← Block JS access (XSS protection)
SESSION_COOKIE_SECURE = True        # ← HTTPS only
CSRF_COOKIE_SECURE = True           # ← HTTPS only
SESSION_COOKIE_SAMESITE = "Lax"     # ← CSRF protection
SESSION_EXPIRE_AT_BROWSER_CLOSE = True  # ← Close session on browser exit
SESSION_COOKIE_AGE = 3600           # ← 1 hour (short-lived)
CSRF_COOKIE_HTTPONLY = False        # ← Must be sent with requests (but Lax SameSite protects)
```

**Files to Modify:**
- `config/settings.py` (session cookie settings)
- `config/settings.py` (CSRF settings)
- `urbanfoods/middleware.py` (session rotation on sensitive actions)

**Estimated Effort:** 2-3 hours

---

### 3. **Rate Limiting: Payment Status Polling** 🟡 HIGH

**Vulnerability:** Attacker can hammer status endpoint to cause DOS and information disclosure

**Current State:**
```python
# No rate limiting on status check
curl https://api.tipsytheoryy.com/api/v1/payments/123/status/  # Unlimited calls
```

**Risk:**
- DOS attack: 1000 requests/second → Server overload
- Brute force: Try all payment IDs to find successful payments
- Account enumeration: Guess customer IDs from payment status patterns
- Competitor intelligence: Monitor transaction volume

**OWASP Requirement:** Broken Authentication (A1:2021)

**Solution:**
- Create `rate_limiting.py` with Redis-based throttling
- Apply to payment status endpoints (max 30 requests/hour/user)
- Apply to list endpoints (max 10 requests/minute/user)
- Track by user_id + IP address
- Return 429 Too Many Requests when exceeded
- Log repeated violations for fraud detection

**Files to Modify:**
- `urbanfoods/permissions.py` (add rate limit permission class)
- `urbanfoods/api_v1_customer_views.py` (apply to payment status)
- New: `urbanfoods/rate_limiting.py`

**Estimated Effort:** 3-4 hours

---

### 4. **Callback IP Validation (Safaricom Whitelist)** 🟡 HIGH

**Vulnerability:** Any attacker can send fake M-Pesa callbacks to manipulate payment status

**Current State:**
```python
# api_v1_customer_views.py
def mpesa_callback(request):
    data = json.loads(request.body)
    # NO CHECK: Where did this request come from?
    # Could be from attacker's machine!
    payment = PaymentAttempt.objects.get(id=data['payment_id'])
    payment.status = 'success'  # ← Attacker marks as paid without paying!
    payment.save()
```

**Risk:**
- **Critical:** Attacker marks payment as successful without paying
- Inventory given away for free
- Customer gets order without payment
- Revenue loss (entire transaction amount)

**Safaricom Requirement:** API security (mutual TLS + IP whitelist)

**Solution:**
- Create `callback_validation.py`
- Validate callback IP against Safaricom whitelisted IPs
- Validate callback signature (HMAC-SHA256)
- Validate callback timestamp (within 5 minutes)
- Reject if any validation fails
- Log all rejected callbacks
- Implement exponential backoff retry for failed payments

**Safaricom Production IPs:** (to be obtained from documentation)
```
196.201.214.0/24    # Safaricom production
196.201.213.0/24    # Safaricom backup
```

**Files to Modify:**
- `urbanfoods/api_v1_customer_views.py` (mpesa_callback endpoint)
- New: `urbanfoods/callback_validation.py`

**Estimated Effort:** 3-4 hours

---

### 5. **Idempotency Validation Strengthening** 🟡 HIGH

**Vulnerability:** Payment idempotency tokens can be reused or spoofed

**Current State:**
```python
# order_idempotency.py (exists but weak)
def get_or_create_payment(idempotency_key, ...):
    # Uses MD5 hash (broken)
    # No expiration
    # No customer binding
    return Payment.objects.get_or_create(idempotency_key=idempotency_key)
```

**Risk:**
- Attacker replays old idempotency token → duplicate payment
- Attacker guesses idempotency token format → initiates payments on behalf of others
- No expiration → tokens valid forever
- Cross-customer attacks

**PCI DSS Requirement:** Req 6.5.2 - Idempotency enforcement

**Solution:**
```python
# Strengthen idempotency:
1. Generate UUIDs (random, not MD5)
2. Bind to customer_id (attacker can't use another customer's token)
3. Bind to phone_number (additional check)
4. Set 24-hour expiration
5. Track token usage (prevent replay)
6. Validate signature (HMAC-SHA256)
7. Return 400 if token already used with different parameters
```

**Files to Modify:**
- `urbanfoods/order_idempotency.py` (strengthen validation)
- `urbanfoods/payment_initiation.py` (enforce on payment creation)

**Estimated Effort:** 2-3 hours

---

### 6. **Database Encryption at Rest** 🟡 HIGH

**Vulnerability:** PostgreSQL database on Railway stores sensitive data unencrypted

**Current State:**
```bash
# Database stored in plain text
# If attacker gains database access:
# - All customer phone numbers visible
# - All M-Pesa credentials visible (before migration to Secrets Manager)
# - All payment history visible
```

**Risk:**
- Database breach → all customer data exposed
- Insider threat: Disgruntled employee exports database
- Regulatory violation (PCI DSS 3.4, GDPR)
- Competitive intelligence: Entire customer list + transaction history

**Encryption Methods:**
1. **Database-level encryption (recommended)**
   - PostgreSQL: pgcrypto extension
   - Encrypts all data at rest on disk
   - Transparent to application

2. **Column-level encryption (secondary)**
   - Encrypt sensitive columns: phone_number, email
   - Application handles encryption/decryption
   - Performance impact minimal

**PCI DSS Requirement:** Req 3.4 - Encryption of stored data

**Solution (Database-level):**
```bash
# On Railway PostgreSQL:
1. Enable pgcrypto extension
2. Create master encryption key
3. Enable transparent encryption at storage level
4. Verify with: SELECT pgp_sym_encrypt('test', 'key');
```

**Solution (Column-level - if DB doesn't support TDE):**
```python
# In models.py
from cryptography.fernet import Fernet

class Customer(models.Model):
    phone_number = models.CharField(max_length=255)  # Store encrypted
    
    def get_phone(self):
        cipher = Fernet(settings.ENCRYPTION_KEY)
        return cipher.decrypt(self.phone_number).decode()
```

**Files to Modify:**
- `config/settings.py` (add encryption key config)
- `urbanfoods/models.py` (add encryption for PII columns)
- New migration: encrypt existing data
- New: `urbanfoods/encryption_utils.py`

**Estimated Effort:** 4-5 hours

---

### 7. **API Rate Limiting (Global)** 🟡 HIGH

**Vulnerability:** No global rate limiting on API endpoints allows DOS and brute force

**Current State:**
```bash
# Attacker can make unlimited requests
curl -X POST https://api.tipsytheoryy.com/api/v1/payments/initiate/ \
  -H "Authorization: Bearer $TOKEN" \
  -d '...' \
  & curl -X POST https://api.tipsytheoryy.com/api/v1/payments/initiate/ \
  -H "Authorization: Bearer $TOKEN" \
  -d '...' \
  & ...  # 1000 times
```

**Risk:**
- DOS attack: Crash server with resource exhaustion
- Brute force: Try all 4-digit amounts to find threshold
- Account takeover: Flood login attempts
- Competitor DOS: Disable competitor's API during peak hours

**OWASP Requirement:** A4:2021 - Insecure Design (DOS prevention)

**Solution:**
```python
# Global throttling per user/IP
- Authenticated users: 1000 requests/hour
- Anonymous users: 100 requests/hour
- IP-level limit: 10,000 requests/hour
- Endpoint-specific limits:
  - Payment initiation: 30 requests/hour
  - Login: 5 attempts/minute
  - List endpoints: 100 requests/hour
```

**Implementation:**
- Use Django REST Framework throttling
- Redis backend for distributed rate limiting
- Return 429 Too Many Requests
- Include Retry-After header
- Log to CloudWatch for monitoring

**Files to Modify:**
- `urbanfoods/permissions.py` (add throttle classes)
- `urbanfoods/api_v1_customer_views.py` (apply throttles)
- `urbanfoods/api_v1_partner_views.py` (apply throttles)

**Estimated Effort:** 3-4 hours

---

### 8. **CORS Security Hardening** 🟡 HIGH

**Vulnerability:** Overly permissive CORS settings allow cross-site attacks

**Current State:**
```python
# config/settings.py
CORS_ALLOWED_ORIGINS = ["*"]  # ← ALLOWS ANYONE!
# OR
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = ["http://localhost:*"]  # ← Too broad
```

**Risk:**
- Malicious website makes requests to API in victim's browser
- Victim's authentication cookie sent automatically (CORS_ALLOW_CREDENTIALS)
- Attacker initiates payments, transfers funds, changes settings
- CSRF attack via CORS

**CORS Requirement:** OWASP A7:2021 - Cross-Origin Resource Sharing

**Solution:**
```python
CORS_ALLOWED_ORIGINS = [
    "https://app.tipsytheoryy.com",      # Flutter app
    "https://merchant.tipsytheoryy.com", # Web merchant portal
    "https://admin.tipsytheoryy.com",    # Admin dashboard
]

# NOT allowed:
# - "http://..." (HTTP only)
# - "*" (wildcard)
# - "*.com" (too broad)

CORS_ALLOW_CREDENTIALS = True  # Only with specific origins above
CORS_EXPOSE_HEADERS = ["Content-Type", "X-CSRFToken"]
CORS_MAX_AGE = 600  # 10 minutes
```

**Files to Modify:**
- `config/settings.py` (CORS settings)

**Estimated Effort:** 1-2 hours

---

### 9. **Incident Response Runbook** 🟡 HIGH

**Vulnerability:** No documented procedures for security incidents → chaotic response

**Current State:**
```
Security incident happens:
- No one knows who to call
- No procedures defined
- Evidence destroyed
- Slow response (hours instead of minutes)
- Regulatory violations
```

**Risk:**
- Payment fraud not detected for days
- Customer data breach → GDPR violation (fine up to 4% revenue)
- Ransomware: No backup/recovery procedure
- Insider threat: No detection/investigation procedure
- Compliance: Can't prove incident response readiness

**PCI DSS Requirement:** Req 12.10 - Incident Response Plan

**Solution - Create Runbooks For:**
1. **Payment Fraud Detection**
   - High unusual transaction detected
   - Customer reports unauthorized payment
   - Multiple failed transaction attempts
   - Procedure: Investigate → Freeze account → Contact customer → Refund

2. **Data Breach**
   - Database compromised
   - Customer data exposed
   - Procedure: Contain → Assess scope → Notify (GDPR 72 hours) → Remediate

3. **Ransomware Attack**
   - Server encrypted
   - Backups compromised
   - Procedure: Isolate → Restore from clean backup → Verify integrity

4. **DDoS Attack**
   - API overwhelmed
   - Services down
   - Procedure: Activate DDoS mitigation → Route to backup → Monitor recovery

5. **Insider Threat**
   - Suspicious access patterns
   - Unauthorized credential access
   - Procedure: Alert → Disable account → Audit logs → Investigation

6. **Third-Party Breach (M-Pesa, AWS)**
   - Provider reports security incident
   - Our data might be affected
   - Procedure: Contact provider → Assess exposure → Take action

**Files to Create:**
- `INCIDENT_RESPONSE_RUNBOOK.md` (master document)
- `INCIDENT_RESPONSE_FRAUD.md` (fraud-specific procedures)
- `INCIDENT_RESPONSE_BREACH.md` (data breach procedures)
- `INCIDENT_RESPONSE_RANSOMWARE.md` (ransomware recovery)
- `INCIDENT_RESPONSE_CONTACTS.md` (who to call)

**Estimated Effort:** 6-8 hours (documentation only)

---

## Implementation Timeline

### Week 1 (Days 1-3)
- [ ] Day 1: PII Masking + Session Security
- [ ] Day 2: Rate Limiting (Payment Polling + Global)
- [ ] Day 3: Callback IP Validation

**Estimated:** 12-14 hours

### Week 1 (Days 4-5)
- [ ] Day 4: Idempotency Strengthening + Database Encryption
- [ ] Day 5: CORS Security + Incident Response Documentation

**Estimated:** 13-16 hours

### Week 2 (Days 6-7)
- [ ] Day 6: Integration testing all 9 fixes
- [ ] Day 7: Staging deployment and validation

**Estimated:** 16-20 hours

**Total Phase 2 Effort:** 41-50 hours (5-6 days for developer, 7-10 calendar days with testing)

---

## Risk Assessment

| Fix | Risk | Complexity | Breaking Changes | Testing Effort |
|-----|------|-----------|-----------------|-----------------|
| PII Masking | LOW | Medium | None | Medium |
| Session Security | MEDIUM | Low | None (production only) | Low |
| Rate Limiting (Polling) | LOW | Medium | Possible (if limits too strict) | High |
| Callback IP Validation | HIGH | High | Requires Safaricom IPs | High |
| Idempotency Strengthening | MEDIUM | Medium | Possible (changes token format) | High |
| Database Encryption | HIGH | High | May require migration | High |
| API Rate Limiting | MEDIUM | Medium | Possible (clients hitting limits) | High |
| CORS Security | LOW | Low | Possible (if origins missing) | Low |
| Incident Response | LOW | Low | None (documentation) | Low |

---

## Dependencies & Ordering

### Must Be Done First (No Dependencies)
1. ✅ CORS Security (independent)
2. ✅ Session Security (independent)
3. ✅ PII Masking (independent)

### Depends on Above
4. → Rate Limiting (Global) [depends on: API infrastructure]
5. → Rate Limiting (Polling) [depends on: permissions system]
6. → API Rate Limiting (Global)

### Requires Infrastructure Setup
7. → Database Encryption [depends on: Railway PostgreSQL]
8. → Callback IP Validation [depends on: Safaricom IP list]

### Depends on All Above
9. → Idempotency Strengthening [validation across system]
10. → Incident Response Runbook [depends on all fixes deployed]

---

## Success Criteria

### Per Fix
- Code review completed
- Unit tests passing (>80% coverage)
- Integration tests in staging passing
- No performance regression
- Logging shows expected behavior

### Overall Phase 2
- [ ] All 9 high-severity issues fixed
- [ ] Staging deployment successful
- [ ] 24-hour monitoring shows no issues
- [ ] Load test passing
- [ ] Security review completed
- [ ] Compliance checklist signed off

---

## Monitoring & Alerts

Create CloudWatch dashboards for Phase 2:
- PII masking verification (count of masked vs unmasked logs)
- Session timeout events
- Rate limit violations (by endpoint)
- Callback validation failures
- Idempotency token reuse attempts
- Database encryption health
- CORS rejection rate

---

## Post-Phase 2

### Phase 3 Work (5 medium-severity issues)
- 2-3 weeks
- After Phase 2 staging validated

### Phase 4-5 Compliance & Testing
- 3-4 weeks
- PCI DSS compliance audit
- Penetration testing
- Load testing
- Final production audit

---

## Questions Before Starting?

- Do you have Safaricom IP whitelist list?
- Is Railway PostgreSQL TDE (Transparent Data Encryption) supported?
- What CORS origins should be whitelisted?
- Database encryption key management (AWS KMS or local)?

**Ready to implement Phase 2?** 

Next steps:
1. Review this plan
2. Get Safaricom IP whitelist
3. Confirm CORS allowed origins
4. Start with PII Masking (Day 1)

