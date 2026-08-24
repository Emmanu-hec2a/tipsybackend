# AWS Setup Scripts - TipsyTheoryy Payment Processing

Collection of Python scripts for setting up AWS infrastructure for Phase 1 production deployment.

## Quick Start

### Step 0: Configure AWS Credentials (First Time Only)

```bash
# Check if AWS credentials are configured
python troubleshoot_credentials.py

# If issues found, configure credentials
aws configure

# Verify credentials work
aws sts get-caller-identity
```

### Step 1-3: Run AWS Setup Scripts

```bash
# 1. Setup AWS Secrets Manager and KMS
python setup_secrets_manager.py --environment staging --region us-east-1 --create-kms-key

# 2. Verify setup
python verify_secrets_manager.py --environment staging --region us-east-1

# 3. Setup monitoring and alerts
python setup_monitoring.py --environment staging --region us-east-1 --email admin@tipsytheoryy.com
```

## Scripts

### 0. `troubleshoot_credentials.py` (Troubleshooting)

Diagnoses and fixes common AWS credential configuration issues.

**Usage:**
```bash
python troubleshoot_credentials.py
```

**Checks Performed:**
1. AWS CLI installed and in PATH
2. Credentials file exists (`~/.aws/credentials`)
3. Environment variables configured
4. Credentials valid (can connect to AWS)
5. Required permissions available

**Output:**
```
✓ AWS CLI installed
  Version: aws-cli/2.13.0 Python/3.11.0 Linux/5.15.0

✓ Credentials file found: /home/user/.aws/credentials
  Found 1 profile(s)
    - [default]

✓ AWS credentials are valid!
  Account ID: 123456789012
  ARN: arn:aws:iam::123456789012:user/tipsytheoryy-payment-deployment

All checks passed! AWS credentials are ready.
```

**Fixes Issues:**
- Missing AWS CLI → Shows installation instructions
- No credentials configured → Shows `aws configure` steps
- Invalid credentials → Shows how to regenerate access keys
- Missing permissions → Lists required policies to attach

**Time:** 1-2 minutes

---

### 1. `setup_secrets_manager.py`

Creates AWS infrastructure for secure credential management:
- KMS encryption key (with automatic annual rotation)
- IAM roles with Secrets Manager permissions
- AWS Secrets Manager configuration
- Resource-based policies

**Usage:**
```bash
python setup_secrets_manager.py \
  --environment staging|production \
  --region us-east-1 \
  --create-kms-key
```

**Output:**
```
Environment variables to set:
  USE_AWS_SECRETS_MANAGER=true
  AWS_REGION=us-east-1
  AWS_KMS_KEY_ID=alias/tipsy-payment-keys-staging
```

**Time:** 2-3 minutes

---

### 2. `verify_secrets_manager.py`

Verifies that all AWS infrastructure is correctly configured:
- KMS key exists and is enabled
- Automatic key rotation configured
- IAM role has correct permissions
- Secrets Manager is accessible
- Secret naming format is correct
- CloudTrail logging is enabled

**Usage:**
```bash
python verify_secrets_manager.py \
  --environment staging|production \
  --region us-east-1
```

**Output:**
```
✓ KMS key exists and is enabled
✓ IAM role has Secrets Manager permissions
✓ Secrets Manager accessible
✓ All secret names follow correct format
✓ CloudTrail logging configured
```

**Time:** 1-2 minutes

---

### 3. `setup_monitoring.py`

Sets up CloudWatch monitoring and alerting:
- Log groups for each Phase 1 component
- CloudWatch dashboards
- CloudWatch alarms (6 critical alarms)
- Metric filters from logs
- SNS notifications

**Usage:**
```bash
# With email notifications
python setup_monitoring.py \
  --environment staging \
  --region us-east-1 \
  --email admin@tipsytheoryy.com

# With existing SNS topic
python setup_monitoring.py \
  --environment staging \
  --region us-east-1 \
  --sns-topic-arn arn:aws:sns:us-east-1:123456789012:MyTopic
```

**Output:**
```
✓ Log groups created (5 total)
✓ CloudWatch dashboard created
✓ Alarms configured (6 total)
✓ Metric filters created
✓ SNS topic subscribed
```

**Alarms Created:**
1. Certificate Pinning Failures
2. Rate Limit Abuse (>10 violations/5min)
3. Security Violations (Query param JWT)
4. Unusual Admin Activity (>20 actions/hour)
5. Secrets Manager Errors
6. Payment Success Rate Drop (<90%)

**Time:** 3-5 minutes

---

## Deployment Workflow

### Phase 1: AWS Setup (One-time)

```bash
# 1. Run from your local machine or CI/CD pipeline
python setup_secrets_manager.py --environment staging

# 2. Verify setup
python verify_secrets_manager.py --environment staging

# 3. Configure monitoring
python setup_monitoring.py --environment staging --email admin@tipsytheoryy.com
```

### Phase 2: Environment Configuration

Update deployment platform environment variables:

```bash
# Railway UI or CLI
railway variables set \
  USE_AWS_SECRETS_MANAGER=true \
  AWS_REGION=us-east-1 \
  AWS_KMS_KEY_ID=alias/tipsy-payment-keys-staging \
  AWS_SM_ACCESS_KEY_ID=<aws-access-key> \
  AWS_SM_SECRET_ACCESS_KEY=<aws-secret-key>
```

### Phase 3: Application Deployment

```bash
# Deploy to staging
railway redeploy

# Run database migrations
python manage.py migrate

# Migrate credentials to Secrets Manager
python manage.py migrate_credentials_to_secrets_manager --dry-run
python manage.py migrate_credentials_to_secrets_manager

# Verify health
curl https://staging.tipsytheoryy.com/api/v1/health/
```

### Phase 4: Testing

Run full staging deployment test (see `PHASE_1_STAGING_DEPLOYMENT_GUIDE.md`):
- Certificate pinning validation
- Phone number validation
- Rate limiting
- JWT authentication
- Audit logging
- End-to-end payment flow

---

## Environment Variables Reference

### AWS Secrets Manager

| Variable | Example | Notes |
|----------|---------|-------|
| `USE_AWS_SECRETS_MANAGER` | `true` | Enable Secrets Manager (fallback to DB encryption if false) |
| `AWS_REGION` | `us-east-1` | AWS region for Secrets Manager |
| `AWS_KMS_KEY_ID` | `alias/tipsy-payment-keys-staging` | KMS key for credential encryption |
| `AWS_SM_ACCESS_KEY_ID` | `AKIAIOSFODNN7EXAMPLE` | AWS IAM access key (separate credentials recommended) |
| `AWS_SM_SECRET_ACCESS_KEY` | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` | AWS IAM secret key |
| `AWS_ROTATION_LAMBDA_ARN` | `arn:aws:lambda:us-east-1:...` | Optional Lambda for credential rotation |

### M-Pesa (Existing)

| Variable | Example | Notes |
|----------|---------|-------|
| `MPESA_PRODUCTION` | `true` | Use production M-Pesa endpoints |
| `MPESA_CONSUMER_KEY` | `consumer_key` | Stored in Secrets Manager after migration |
| `MPESA_CONSUMER_SECRET` | `consumer_secret` | Stored in Secrets Manager after migration |
| `MPESA_PASSKEY` | `passkey` | Stored in Secrets Manager after migration |
| `MPESA_PAYBILL_NUMBER` | `123456` | Stored in Secrets Manager after migration |
| `MPESA_CALLBACK_URL` | `https://api.tipsytheoryy.com/api/v1/mpesa/callback/` | Webhook endpoint |

---

## Troubleshooting

### Error: "Unable to locate credentials"

This means AWS credentials are not configured on your machine.

**Quickest Fix:**

```bash
# Step 1: Run troubleshooting script
python troubleshoot_credentials.py

# Step 2: Configure AWS (if credentials file missing)
aws configure

# Step 3: Paste in:
# AWS Access Key ID: [your access key from AWS IAM]
# AWS Secret Access Key: [your secret key]
# Default region: us-east-1
# Default output format: json

# Step 4: Verify it worked
aws sts get-caller-identity

# Step 5: Run setup script again
python setup_secrets_manager.py --environment staging --create-kms-key
```

**Detailed Help:**
See: `AWS_CREDENTIALS_SETUP.md` (in root directory)

### AWS Credentials Not Found

```bash
# Verify AWS credentials are configured
aws sts get-caller-identity

# If not configured, set credentials
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

If you get: "InvalidClientTokenId: The security token included in the request is invalid"

```bash
# Regenerate credentials in AWS console:
# 1. AWS console → IAM → Users → Your User
# 2. Security credentials → Create new access key
# 3. Run: aws configure
# 4. Enter new credentials
```

### Script Fails with "NoSuchEntity"

```bash
# Usually means IAM role doesn't exist yet
# Run with --create-kms-key flag to create all resources
python setup_secrets_manager.py --environment staging --create-kms-key
```

### KMS Key Already Exists

```bash
# Script will reuse existing key
# To create a new key, first delete the alias
aws kms schedule-key-deletion --key-id alias/tipsy-payment-keys-staging --pending-window-in-days 7
```

### SNS Topic Creation Fails

```bash
# Provide existing SNS topic ARN instead
python setup_monitoring.py \
  --environment staging \
  --sns-topic-arn arn:aws:sns:us-east-1:123456789012:MyTopic
```

---

## Security Best Practices

1. **Separate IAM Users for Secrets Manager Access**
   - Create dedicated IAM user with only Secrets Manager + KMS permissions
   - Use this user for application credentials
   - Do not use root AWS account

2. **Enable MFA on AWS Root Account**
   - Prevents accidental credential exposure

3. **Rotate IAM Credentials Regularly**
   - AWS Secrets Manager does this automatically for credentials
   - Manually rotate any static IAM keys every 90 days

4. **Restrict KMS Key Access**
   - Only payment service and authorized admins can decrypt

5. **Enable CloudTrail Logging**
   - Logs all credential access for audit trail

6. **Review Audit Logs Weekly**
   - Check for unusual credential access patterns
   - Monitor admin activity

---

## Monitoring Checklist

- [ ] CloudWatch dashboards accessible
- [ ] All 6 alarms active
- [ ] SNS notifications configured
- [ ] Log groups receiving data
- [ ] Metric filters active
- [ ] Certificate pinning health: GREEN
- [ ] Rate limiting active
- [ ] Admin audit logs recording
- [ ] Payment success rate > 95%

---

## Support

**Questions about AWS setup?**
- See `PHASE_1_STAGING_DEPLOYMENT_GUIDE.md` for full deployment procedure
- See `aws_setup_scripts/setup_monitoring.py --help` for monitoring options

**Critical issues?**
- Contact: backend-devops@tipsytheoryy.com
- Escalate to: CTO (for production approval)

---

## Files in This Directory

```
aws_setup_scripts/
├── troubleshoot_credentials.py   # Diagnose AWS credential issues
├── setup_secrets_manager.py      # AWS KMS + Secrets Manager setup
├── verify_secrets_manager.py     # Verify AWS infrastructure
├── setup_monitoring.py           # CloudWatch monitoring setup
└── README.md                      # This file
```

---

**Last Updated:** 2026-08-24  
**Tested On:** Python 3.9+, boto3 1.26.0+  
**Status:** PRODUCTION-READY  
