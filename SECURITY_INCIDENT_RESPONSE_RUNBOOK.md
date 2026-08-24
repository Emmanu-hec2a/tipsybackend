# Security Incident Response Runbook

**Purpose:** Structured procedures for detecting, responding to, and recovering from security incidents

**Scope:**
- Payment fraud and payment system attacks
- Data breaches and unauthorized access
- Service disruption and DDoS attacks
- Account takeover and unauthorized access
- System failures and data corruption

---

## 1. Incident Classification & Severity Levels

### CRITICAL (P0) - Immediate Action Required

**Indicators:**
- Active data breach affecting customer PII
- Payment system completely down (no transactions possible)
- Active ongoing attack with high-volume requests
- Ransomware or malware detected
- Multiple payment failures across all customers

**Response Time:** Immediate (< 5 minutes)
**On-Call Team:** CTO, DevOps Lead, Database Admin
**Escalation:** Contact CEO immediately

**Actions:**
1. Initiate war room (Slack channel, video call)
2. Pull system offline if necessary to prevent spread
3. Engage external security incident response firm
4. Begin customer notification process
5. Notify authorities if required

**Example:** "M-Pesa API returning 500 errors for all payment requests for > 1 hour"

---

### HIGH (P1) - Urgent Response

**Indicators:**
- Suspected fraud (high-confidence pattern detected)
- Partial service degradation (10-50% transactions failing)
- Unauthorized access attempt detected
- Single customer account compromised
- Rate limit bypass detected

**Response Time:** < 30 minutes
**On-Call Team:** DevOps Lead, Backend Engineer
**Escalation:** Contact CTO

**Actions:**
1. Create incident ticket
2. Engage relevant team members
3. Investigate and isolate affected customers
4. Implement mitigation (block suspicious accounts, increase rate limits)
5. Begin root cause analysis

**Example:** "Customer reports order placed without authorization"

---

### MEDIUM (P2) - Standard Response

**Indicators:**
- Single payment attempt failed due to suspected fraud
- Unusual behavior from single customer
- Minor service degradation (< 10% transactions affected)
- Configuration error detected
- SSL certificate expiring soon

**Response Time:** < 2 hours
**On-Call Team:** Backend Engineer
**Escalation:** Contact Team Lead

**Actions:**
1. Create ticket in incident tracking system
2. Investigate root cause
3. Implement fix or workaround
4. Monitor for recurrence
5. Schedule post-incident review

**Example:** "SMS verification code not being received by one customer"

---

### LOW (P3) - Planning Response

**Indicators:**
- False positive fraud alert
- Informational security finding
- Documentation needs update
- Dependency updates available
- Non-critical error logs

**Response Time:** < 1 week
**On-Call Team:** Any engineer
**Escalation:** Via ticket system

**Actions:**
1. Create ticket for investigation
2. Investigate when time permits
3. Document findings
4. Implement long-term fix

**Example:** "Deprecated dependency version in use (but no known vulnerabilities)"

---

## 2. Incident Response Escalation Matrix

```
         P0 CRITICAL         P1 HIGH            P2 MEDIUM         P3 LOW
         
         CTO ────────────→   DevOps Lead ──→   Backend Eng ──→  Ticket Queue
           │                    │                                
           │                    ├──→ OnCall Backend            
           │                    │                                
           ├──→ OnCall DevOps   └──→ OnCall DevOps            
           │                                                    
           └──→ External Security Firm                         
```

### Escalation Procedure

1. **Initial Detection** (Automated or Manual)
   - Monitoring system detects anomaly
   - Or: Customer reports issue via support
   - Or: Team member discovers during testing

2. **Classification** (< 5 minutes)
   - Assess severity using criteria above
   - Determine affected systems
   - Estimate customer impact

3. **Page On-Call Team** (P0/P1 only)
   ```bash
   # PagerDuty API
   curl -X POST https://events.pagerduty.com/v2/enqueue \
     -H "Content-Type: application/json" \
     -d '{
       "routing_key": "PAGERDUTY_INTEGRATION_KEY",
       "event_action": "trigger",
       "payload": {
         "summary": "P1: Fraudulent order detected",
         "severity": "critical",
         "source": "incident_system"
       }
     }'
   ```

4. **Notify Management** (P0 only)
   - Call CTO immediately
   - Text message to CEO
   - Slack #incidents channel with @here

5. **War Room Setup** (P0/P1)
   - Create Slack channel: #incident-YYYYMMDD-HHMM
   - Start Google Meet for video conference
   - Begin incident timeline in Notion
   - Assign Incident Commander (IC)

---

## 3. Incident Investigation Procedure

### Step 1: Gather Initial Information (First 5 minutes)

**Questions to Answer:**
- When did the incident start?
- Who/what reported it?
- What system is affected?
- How many customers impacted?
- Is the incident ongoing?
- Can we reproduce the issue?

**Data Collection:**
```python
# Check recent logs
curl -s "https://logs.tipsytheoryy.com/api/logs?level=ERROR&limit=100"

# Check system metrics
curl -s "https://monitoring.tipsytheoryy.com/api/metrics?metric=error_rate"

# Check fraud incidents
python manage.py shell
>>> from urbanfoods.models import FraudIncident
>>> FraudIncident.objects.filter(status='OPEN').order_by('-created_at')[:10]

# Check payment failures
>>> from urbanfoods.models import PaymentAttempt
>>> PaymentAttempt.objects.filter(
...     status__in=['FAILED', 'REJECTED'],
...     created_at__gte=timezone.now() - timedelta(minutes=30)
... ).count()
```

### Step 2: Isolate & Contain (5-15 minutes)

**For Fraud:**
```bash
# Temporarily block suspicious customer
python manage.py shell
>>> from urbanfoods.models import Customer
>>> customer = Customer.objects.get(id='suspicious_customer_id')
>>> customer.is_blocked = True
>>> customer.block_reason = "P1: Suspected fraud - investigating"
>>> customer.save()

# Alert support team
# Slack: @support - Block customer XXX pending fraud investigation
```

**For Payment System Issue:**
```bash
# Check M-Pesa API connectivity
curl -v -X POST "https://api.sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

# Failover to backup payment method if available
# Scale up M-Pesa rate limiter if needed
# Redirect traffic to backup server if needed
```

**For Data Breach:**
```bash
# Revoke potentially compromised credentials
aws secretsmanager update-secret \
  --secret-id mpesa-api-key \
  --secret-string "new-api-key"

# Disable affected accounts
python manage.py shell
>>> User.objects.filter(email='compromised@example.com').update(is_active=False)
```

### Step 3: Root Cause Analysis (15-60 minutes)

**Payment Fraud Example:**
```
Fraud Pattern Detected: Order Velocity
├─ Customer: 12345
├─ Pattern: 5 orders in 2 minutes
├─ Confidence: 90%
│
Investigation:
├─ Check IP address (same for all orders?)
├─ Check payment methods (same card/phone?)
├─ Check delivery addresses (all different?)
├─ Check order contents (similar patterns?)
│
Conclusion:
├─ All orders from different IP address (196.201.x.x)
├─ All payments from same phone (+254712345678)
├─ All delivery to different addresses
├─ Pattern: Account takeover - attacker placing multiple orders
│
Root Cause: Password too weak, phishing email
```

**Database Issue Example:**
```
Error: Connection pool exhausted
├─ Check database connections
│  $ psql -c "SELECT count(*) FROM pg_stat_activity;"
│  (Shows: 1000 connections, max 500)
├─ Check slow queries
│  $ SELECT query, calls, mean_time FROM pg_stat_statements
│  (Shows: SELECT * FROM orders WITH RECURSIVE taking 30s)
├─ Check deployment changes
│  $ git log --oneline -10
│  (Shows: Recent update to order_idempotency causing N+1 queries)
│
Root Cause: Query optimization regression in recent deployment
```

### Step 4: Resolution (Varies by incident type)

**For Fraud - Customer Blocklist:**
```python
# Temporarily block customer (24-48 hours)
customer.is_blocked = True
customer.block_reason = "P1: Fraud investigation in progress"
customer.block_until = timezone.now() + timedelta(hours=48)
customer.save()

# Schedule re-verification
# Email to customer: "We detected unusual activity on your account.
#                     Please verify your identity."
```

**For Payment System Down:**
```python
# Restart payment processing service
$ kubectl rollout restart deployment/payment-processor

# Wait for health check
$ kubectl wait --for=condition=ready pod -l app=payment-processor

# Verify operations resuming
$ python manage.py check_payment_status
```

**For Data Breach:**
```python
# Rotate all credentials
python manage.py rotate_encryption_keys

# Force password reset for affected users
from django.contrib.auth.tokens import default_token_generator
for user in affected_users:
    user.set_password(User.objects.make_random_password())
    user.save()
    # Email password reset link

# Enable 2FA requirement
user.require_2fa = True
user.save()
```

---

## 4. Customer Notification Templates

### 4.1 Fraud Investigation - Initial Notification

**Timing:** Within 1 hour of incident detection
**Channels:** Email + SMS + In-app notification
**Tone:** Reassuring, professional

```
Subject: We're Verifying Activity on Your Account [TipsyTheoryy Support]

Dear [Customer Name],

We've detected unusual activity on your TipsyTheoryy account and have temporarily 
restricted access for your security.

Activity Detected:
├─ Location: [IP Address / Country]
├─ Time: [Timestamp]
└─ Action: [Multiple orders / Rapid payment attempts]

What We're Doing:
✓ Our security team is investigating
✓ Your account is temporarily locked to prevent unauthorized access
✓ No unauthorized charges will be processed

What You Should Do:
1. Verify you made the flagged transactions (reply to this email)
2. Change your password immediately: https://app.tipsytheoryy.com/account/security
3. Enable two-factor authentication (2FA) for added security
4. Contact our support team if you need help: support@tipsytheoryy.com

Your Account Status:
├─ Current: TEMPORARILY RESTRICTED
├─ Duration: 24-48 hours during investigation
└─ Action: You'll receive an update via email

Questions? Reply to this email or call us at [Support Phone].

Best regards,
TipsyTheoryy Security Team
```

---

### 4.2 Unauthorized Payment - Immediate Notification

**Timing:** Immediately upon detection
**Channels:** SMS (fastest) + Email + Call (high-value fraud)
**Tone:** Urgent, action-oriented

```
🚨 FRAUD ALERT - TipsyTheoryy

Unauthorized order detected on your account!

Order: #ORD-2026-08-24-001
Amount: Ksh 5,000
Merchant: Quick Mart [Westlands]
Time: 2026-08-24 14:32:10 UTC+3

TAKE ACTION IMMEDIATELY:
1. If you didn't place this order, call us NOW: +254 700 000 000
2. We can REVERSE the payment within 1 hour
3. Your card/phone is now BLOCKED

Questions or confirm this order was legitimate?
Reply "YES" to allow, "NO" to decline

--- TipsyTheoryy Fraud Prevention Team ---
```

---

### 4.3 Account Compromise - Full Notification

**Timing:** When identity verified
**Channels:** Email + Certified Letter (serious cases) + Phone Call
**Tone:** Professional, detailed

```
CONFIDENTIAL - Account Security Notice
Date: August 24, 2026
Case #: INC-2026-0824-12345

Dear [Customer Name],

We are writing to inform you of suspicious activity on your TipsyTheoryy account
that has been detected and contained by our security team.

INCIDENT SUMMARY:
├─ Type: Unauthorized Account Access
├─ Detection Time: 2026-08-24 14:32:10
├─ Contained At: 2026-08-24 14:35:00 (3 minutes)
├─ Affected Records: Payment methods, order history (not passwords or SSN)
└─ Your Data: Protected - No verified breach of personal information

WHAT HAPPENED:
An attacker gained access to your account, likely via phishing email or 
password reuse on another site. Within 3 minutes of detection, we:
  ✓ Blocked the attacker's IP address
  ✓ Locked your account
  ✓ Cancelled all pending orders

WHAT YOU SHOULD DO:
1. Change your password immediately
2. Enable 2-factor authentication (SMS or authenticator app)
3. Check for unauthorized charges in your account history
4. Report any fraudulent charges to your bank

YOUR ACCOUNT STATUS:
├─ Current: LOCKED (for your protection)
├─ To Unlock: Verify identity at https://app.tipsytheoryy.com/verify
├─ Timeline: 24-48 hours (after verification)
└─ Support: support@tipsytheoryy.com or +254 700 000 000

IMPORTANT - CHARGEBACK INFORMATION:
If you notice unauthorized charges on your card:
  1. Contact your bank immediately
  2. Request a chargeback
  3. We will cooperate fully in the investigation
  4. You are protected by your bank's fraud liability policy

REGULATORY COMPLIANCE:
This incident has been reported to:
  ├─ Kenya Data Protection Commissioner (KDPC)
  ├─ Safaricom M-Pesa Security Team
  └─ Your Financial Institution

We deeply regret this incident and have taken steps to prevent recurrence.

Best regards,
TipsyTheoryy Security & Compliance Team

Questions? Contact us immediately:
  Email: security@tipsytheoryy.com
  Phone: +254 700 000 000
  Portal: https://support.tipsytheoryy.com
```

---

### 4.4 Service Recovery - Post-Incident

**Timing:** When incident resolved
**Channels:** Email + In-app notification + SMS
**Tone:** Apologetic, reassuring

```
Subject: Your Account Has Been Restored - Thank You for Your Patience

Hi [Customer Name],

Your TipsyTheoryy account has been fully restored following our investigation
into the unauthorized activity.

INVESTIGATION RESULTS:
✓ Attacker's access has been completely removed
✓ No additional unauthorized charges detected
✓ Your payment methods have been refreshed
✓ Session credentials have been rotated

WHAT WE'VE DONE:
├─ Account fully secured
├─ All suspicious transactions reversed (Ksh [Amount])
├─ IP blocklist activated to prevent re-attack
├─ Your 2FA has been reset (check email for setup link)
└─ Security audit completed

YOUR NEXT STEPS:
1. Log in with your new password
2. Set up 2-factor authentication (SMS or app)
3. Review account history for any issues
4. Contact us if you notice anything unusual

COMPENSATION:
We're providing:
├─ Ksh 500 credit to your account (30-day voucher)
├─ 3 months of premium support (priority response)
└─ Free fraud monitoring for 6 months

We're sorry this happened and appreciate your patience while we investigated.
Your security and trust are our top priorities.

Best regards,
TipsyTheoryy Support Team
```

---

## 5. Recovery & Remediation Procedures

### 5.1 Database Restore Procedure (Data Corruption/Breach)

**Objective:** Restore database to known-good state without data loss

```bash
# Step 1: Assess Damage
kubectl exec deployment/db -- \
  psql -U postgres -c "ANALYZE; SELECT schemaname, tablename FROM pg_tables \
  WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"

# Step 2: Create Backup of Current State (for forensics)
pg_dump -U postgres -d tipsytheoryy > /backups/corrupted_2026-08-24_1432.sql

# Step 3: Restore from Point-in-Time Recovery (last known good - 1 hour ago)
# Navigate to AWS RDS console:
# Automated backups → Restore to point in time → 2026-08-24 13:32:10
# Name new instance: tipsytheoryy-restore-20260824

# Step 4: Validate Restored Data
# Connect to restored instance
psql -h tipsytheoryy-restore-20260824.c9akciq32.us-east-1.rds.amazonaws.com \
  -U postgres -d tipsytheoryy
  
# Count orders (should match production last hour)
SELECT COUNT(*) FROM orders WHERE created_at > '2026-08-24 12:32:10';
SELECT COUNT(*) FROM payment_attempts WHERE status = 'SUCCESS';

# Step 5: Verify Data Integrity
python manage.py check_data_integrity --database=restored

# Step 6: Failover to Restored Database
# Update DATABASES setting in config/settings.py
# Restart Django application
kubectl rollout restart deployment/django

# Step 7: Monitor for Issues (1 hour)
# Check error rates
# Verify customers can access accounts
# Monitor database query performance

# Step 8: Point production read replicas to restored instance
# RDS console → Modify endpoint → new instance
```

---

### 5.2 Ransomware/Malware Recovery

**Objective:** Remove malicious software and restore clean state

```bash
# Step 1: Isolate Affected Systems
# Immediately disconnect from network
kubectl delete deployment affected-service

# Step 2: Collect Forensics
# Export logs for analysis
aws s3 cp s3://logs-bucket/cloudtrail/ /forensics/ --recursive

# Step 3: Scan System for Malware
clamav-scan /app
antivirus-scan /app

# Step 4: Review Deployment Manifests
git log --oneline -20
# Look for suspicious changes in YAML, environment variables, or container images

# Step 5: Rebuild Container from Source
docker build -t tipsytheoryy:clean-build \
  --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
  .

# Step 6: Redeploy Clean Container
kubectl set image deployment/django django=tipsytheoryy:clean-build --record

# Step 7: Rotate All Credentials
python manage.py rotate_credentials_all
# Updates: API keys, database passwords, AWS credentials, M-Pesa keys

# Step 8: Verify Clean State
# Run full test suite
pytest -v
# Run security scan
bandit -r urbanfoods/
# Check for suspicious processes
ps aux | grep -i suspicious
```

---

### 5.3 Payment System Recovery (M-Pesa Down)

**Objective:** Restore payment processing when M-Pesa API unavailable

```bash
# Step 1: Detect & Isolate
# Monitoring detects: M-Pesa API HTTP 503 for > 5 minutes
# Severity: P1
# Incident Channel: #incident-payment-outage

# Step 2: Failover to Queue Mode
# Don't reject payments - queue them for later
python manage.py shell
>>> from urbanfoods.payment_service import PaymentProcessor
>>> PaymentProcessor.set_mode('QUEUE')  # Accept but don't process

# Step 3: Notify Customers
# Email: "We're experiencing temporary payment delays. Orders will be processed in priority order."

# Step 4: Monitor M-Pesa Status
$ curl -I https://api.sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest
# Wait for 200 OK response

# Step 5: Resume Processing
python manage.py shell
>>> PaymentProcessor.set_mode('LIVE')  # Resume normal processing
>>> PaymentProcessor.process_queued_payments()

# Step 6: Verify Catch-Up
# Monitor queue depth
$ redis-cli LLEN payment:queue
# Should return to 0 within 5 minutes

# Step 7: Post-Incident Analysis
# Send metrics to stakeholders
# Update M-Pesa SLA contact list if needed
```

---

### 5.4 Credential Rotation (Suspected Compromise)

**Objective:** Invalidate potentially compromised credentials without disruption

```bash
# Step 1: Generate New Credentials
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key())"
# New M-Pesa API Key from Safaricom portal
# New AWS access keys from IAM console

# Step 2: Update AWS Secrets Manager
aws secretsmanager update-secret \
  --secret-id mpesa-api-key \
  --secret-string '{"api_key": "new_key_2026_08_24_..."}'

aws secretsmanager update-secret \
  --secret-id aws-credentials \
  --secret-string '{"access_key_id": "AKIA...", "secret_access_key": "..."}'

# Step 3: Update Environment Variables
export MPESA_API_KEY='new_key_2026_08_24_...'
export ENCRYPTION_MASTER_KEY='...'

# Step 4: Restart Services (blue-green deployment)
# Don't restart all at once - phase the restart
kubectl set env deployment/django \
  MPESA_API_KEY='new_key_2026_08_24_...'

# Step 5: Verify Old Credentials Disabled
# M-Pesa console: Revoke old API key
# AWS console: Mark old access keys as inactive
# Databaase: Verify new credentials used

# Step 6: Monitor for Issues
# Watch for authentication failures
# Verify payment processing working
# Check that old credentials are truly dead
```

---

## 6. Post-Incident Activities

### 6.1 Incident Reporting Timeline

```
Incident Occurs
  └─ T+5min: Severity assessment → Page on-call team (if P0/P1)
  └─ T+15min: War room established → Investigation begins
  └─ T+30min: Preliminary findings → Incident commander updates team
  └─ T+60min: Root cause identified → Remediation starts
  └─ T+2hr: Resolution deployed → Begin validation
  └─ T+3hr: System stabilized → Customer notifications sent
  └─ T+4hr: Incident declared resolved → Begin post-mortem
```

### 6.2 Post-Incident Review (Within 48 hours)

**Meeting Participants:**
- Incident Commander (DevOps Lead)
- Technical Lead
- Security Officer
- Product Manager
- Customer Support Manager

**Agenda:**

1. **Timeline Review** (15 min)
   - When was incident first detected?
   - How long before containment?
   - What alerts fired? Which missed?
   - What manual actions were needed?

2. **Root Cause Analysis** (30 min)
   - What was the underlying cause?
   - Why wasn't this prevented?
   - Were there warning signs we missed?
   - Could this have been prevented?

3. **Impact Assessment** (10 min)
   - How many customers affected?
   - How much revenue impact?
   - How much data exposed (if any)?
   - Regulatory implications?

4. **What Went Well** (10 min)
   - Alert detected issue quickly?
   - Team responded effectively?
   - Customers were notified appropriately?
   - Documentation was accurate?

5. **What Could Improve** (20 min)
   - Alert tuning needed?
   - Runbook needs updating?
   - Process changes required?
   - Team training needed?

6. **Action Items** (15 min)
   - Immediate fixes (deploy before end of day)
   - Short-term improvements (implement within 1 week)
   - Long-term changes (implement within 1 month)
   - Process documentation updates

### 6.3 Post-Incident Report Template

```markdown
# Incident Report: [Title]

**Incident ID:** INC-2026-0824-12345
**Date:** August 24, 2026
**Severity:** P1 (High)
**Status:** RESOLVED

## Executive Summary
[1-2 paragraph summary suitable for CEO]

## Incident Timeline

| Time | Event |
|------|-------|
| 14:32:10 | Order Velocity fraud pattern detected (5 orders/2 min) |
| 14:35:00 | Customer account blocked by fraud detection system |
| 14:42:00 | On-call engineer begins investigation |
| 14:55:00 | Root cause identified: Password too weak, phishing |
| 15:10:00 | Customer contacted and account reset |
| 15:25:00 | Incident declared resolved |

**Total Duration:** 53 minutes
**Time to Detection:** 2 minutes (automated)
**Time to Containment:** 3 minutes
**Time to Resolution:** 53 minutes

## Root Cause Analysis

### What Happened
Customer's account was compromised via phishing email directing to fake login page.
Attacker used credentials to place 5 rapid orders totaling Ksh 8,500.

### Why It Happened
- Password strength requirements were too lenient (minimum 6 chars)
- No rate limiting on rapid order placement
- Customer fell for sophisticated phishing email

### Why We Didn't Catch It Earlier
- Fraud detection was not trained on order velocity patterns (now added)
- No rate limiting on order creation endpoints (now added)

## Impact Assessment

- **Customers Affected:** 1
- **Orders Fraudulently Placed:** 5
- **Fraudulent Amount:** Ksh 8,500
- **Amount Charged Back:** Ksh 8,500 (no customer loss)
- **Customers Who Needed Notification:** 1
- **Regulatory Reporting Required:** No

## Resolution

1. ✅ Blocked fraudulent account
2. ✅ Reversed all unauthorized charges
3. ✅ Reset customer's password and enabled 2FA
4. ✅ Added order rate limiting (max 3 orders per minute)
5. ✅ Improved fraud detection with order velocity patterns
6. ✅ Notified customer with apology and Ksh 500 credit

## Prevention for Future

### Immediate Actions (Deployed)
- ✅ Order velocity rate limiting (3 orders per 5 minutes)
- ✅ Fraud pattern detection activated
- ✅ Customer notification templates created

### Short-term Actions (Next Week)
- [ ] Strengthen password requirements (min 12 chars, complexity)
- [ ] Add phishing email detection
- [ ] Implement email authentication (SPF, DKIM, DMARC)
- [ ] Security awareness training for all customers

### Long-term Actions (Next Month)
- [ ] Implement passwordless authentication
- [ ] Add behavioral biometrics for fraud detection
- [ ] Deploy hardware security key support
- [ ] Implement advanced fraud ML model

## Lessons Learned

**What Went Well:**
- Fraud detection system worked as designed
- Alert was triggered within 2 minutes
- Customer support responded quickly with account reset
- Charges were reversed promptly

**What Could Improve:**
- Could have detected phishing email upstream
- Rate limiting should have prevented 5 orders initially
- Customer password requirements too weak
- No email verification for first login from new IP

## Preventive Measures Implemented

1. Order rate limiting: 3 orders per 5 minutes per customer
2. Fraud detection patterns: Failed attempt velocity, order velocity, unusual amounts
3. Callback validation: IP whitelist, signature verification, amount verification
4. Idempotency: SHA256 fingerprints with customer binding
5. Session security: 1-hour timeouts, HttpOnly cookies

## Sign-Off

- **Incident Commander:** [Name], DevOps Lead
- **Security Officer:** [Name]
- **CTO:** [Name]
- **Date:** August 24, 2026
```

---

## 7. Monitoring & Alerting for Incidents

### Alert Rules

```yaml
# AlertManager Configuration

alerts:
  
  - name: "payment_failed_high_rate"
    condition: "rate(payment_failures[5m]) > 10"
    severity: "critical"
    message: "Payment failure rate unusually high"
    action: "page_oncall_devops"
  
  - name: "fraud_pattern_detected"
    condition: "fraud_incidents{confidence > 0.8}"
    severity: "high"
    message: "High-confidence fraud pattern detected"
    action: "page_oncall_backend"
  
  - name: "database_connection_pool_exhausted"
    condition: "pg_connections > 400"
    severity: "critical"
    message: "Database connection pool nearly exhausted"
    action: "page_oncall_dba"
  
  - name: "mpesa_api_timeout"
    condition: "mpesa_request_duration{quantile=0.99} > 30000"
    severity: "high"
    message: "M-Pesa API responses slow (p99 > 30s)"
    action: "page_oncall_devops"
  
  - name: "rate_limit_bypass_attempt"
    condition: "rate_limit_bypass_attempts > 5"
    severity: "high"
    message: "Multiple attempts to bypass rate limiting"
    action: "page_oncall_backend"
```

---

## 8. Emergency Contacts

**On-Call Rotation:** PagerDuty
**Slack Channel:** #incidents
**War Room:** Google Meet (auto-created per incident)

| Role | Name | Phone | Email | Availability |
|------|------|-------|-------|---|
| CTO | [Name] | +254 700 000 000 | cto@tipsytheoryy.com | 24/7 (Sleep schedule) |
| DevOps Lead | [Name] | +254 700 000 001 | devops@tipsytheoryy.com | 24/7 |
| Backend Lead | [Name] | +254 700 000 002 | backend@tipsytheoryy.com | 9-18 KST |
| Security Officer | [Name] | +254 700 000 003 | security@tipsytheoryy.com | 9-18 KST |
| Support Manager | [Name] | +254 700 000 004 | support@tipsytheoryy.com | 24/7 |
| M-Pesa Account Manager | [Name] | +254 700 000 005 | [Email] | 9-17 KST |

---

## 9. Incident Communication Templates

### Slack Update - Investigation Phase

```
🚨 INCIDENT UPDATE - 14:45 KST

Incident: P1 - Fraudulent Order Surge
Status: INVESTIGATING

Current Situation:
├─ Fraud pattern detected: 5 orders in 2 minutes
├─ Confidence: 90% (high confidence)
├─ Customer: [Masked ID]
├─ Amount: Ksh 8,500
└─ Estimated Impact: 1 customer affected

Actions Taken:
✓ Customer account blocked
✓ Fraudulent orders cancelled
✓ Charges reversed
✓ Investigation in progress

Next Steps:
- Root cause analysis (15 min)
- Customer notification (30 min)
- Resolution verification (45 min)

Incident Commander: @DevOps Lead
Questions? React with 👍
```

### Email - Customer Notification (Initial)

```
Subject: Security Alert: Unusual Activity on Your Account

Dear Customer,

We detected unusual activity on your TipsyTheoryy account at 14:32 KST today.
We have temporarily restricted your account for your protection.

Activity: Multiple orders placed rapidly
Action: Account locked, charges reversed, no customer loss

Your account will be restored after verification (24-48 hours).

Please verify your identity: https://app.tipsytheoryy.com/verify

Questions? support@tipsytheoryy.com or +254 700 000 000

Security Team
```

---

**Phase 2 Day 5 Status: ✅ IMPLEMENTATION COMPLETE**

All incident response procedures, customer communication templates, and recovery procedures are documented and ready for deployment.

