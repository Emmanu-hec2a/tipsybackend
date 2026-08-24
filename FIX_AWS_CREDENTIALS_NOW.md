# URGENT: Fix AWS Credentials Error

**Error:** `Unable to locate credentials`  
**Cause:** AWS credentials not configured  
**Solution:** Follow these 3 simple steps  

---

## ⚡ Quick Fix (2 minutes)

### Step 1: Diagnose the Issue
```bash
cd C:\Users\PC\Desktop\tipsytheoryy
python aws_setup_scripts/troubleshoot_credentials.py
```

**Expected output:**
```
✗ AWS credentials are not configured
✗ Credentials file not found

Next Steps
==========
1. CONFIGURE AWS CREDENTIALS
   Run: aws configure
   Then enter:
   - AWS Access Key ID: [your access key]
   - AWS Secret Access Key: [your secret key]
   - Default region: us-east-1
   - Default output format: json

2. GET AWS CREDENTIALS
   a. Log in to: https://console.aws.amazon.com/
   b. Go to: Services → IAM → Users
   c. Create user: tipsytheoryy-payment-deployment
   ...
```

### Step 2: Get AWS Credentials (5 minutes)

1. **Log in to AWS Console**
   - URL: https://console.aws.amazon.com/
   - Use your AWS account email and password

2. **Create IAM User**
   - Click: Services → IAM (or search for IAM)
   - Left panel: Click "Users"
   - Click: "Create user"
   - Username: `tipsytheoryy-payment-deployment`
   - Click: "Next"

3. **Attach Permissions**
   - Select: "Attach policies directly"
   - Search and select these 3 policies:
     - `AmazonSecretsManagerFullAccess`
     - `AWSKeyManagementServicePowerUser`
     - `CloudWatchFullAccess`
   - Click: "Create user"

4. **Create Access Key**
   - Click: On the new user name
   - Tab: "Security credentials"
   - Section: "Access keys"
   - Button: "Create access key"
   - Select: "Command Line Interface (CLI)"
   - Checkbox: "I understand..."
   - Click: "Create access key"
   - **COPY and SAVE** the Access Key ID and Secret Access Key (only shown once!)

### Step 3: Configure AWS Locally
```bash
# Windows PowerShell
aws configure

# When prompted, enter:
AWS Access Key ID: [paste the Access Key ID from step 4]
AWS Secret Access Key: [paste the Secret Access Key from step 4]
Default region name: us-east-1
Default output format: json

# Then press Enter for each prompt
```

### Step 4: Verify It Works
```bash
aws sts get-caller-identity

# Expected output:
# {
#     "UserId": "AIDACKCEVSQ6C2EXAMPLE",
#     "Account": "123456789012",
#     "Arn": "arn:aws:iam::123456789012:user/tipsytheoryy-payment-deployment"
# }
```

### Step 5: Run AWS Setup Again
```bash
cd C:\Users\PC\Desktop\tipsytheoryy
python aws_setup_scripts/setup_secrets_manager.py --environment staging --create-kms-key

# Expected output:
# ======================================================================
# TipsyTheoryy AWS Secrets Manager Setup
# Environment: staging
# Region: us-east-1
# ======================================================================
# [1/5] Setting up KMS key: alias/tipsy-payment-keys-staging
#   ✓ KMS key created: arn:aws:kms:us-east-1:...
#   ✓ Alias created: alias/tipsy-payment-keys-staging
#   ✓ Automatic key rotation enabled (annual)
# 
# ✓ AWS Setup Complete!
```

---

## 🆘 Still Having Issues?

### Issue: "aws command not found"
**Solution:**
```bash
# Install AWS CLI
pip install awscli

# Verify
aws --version
```

### Issue: "InvalidClientTokenId: The security token included in the request is invalid"
**Solution:**
- Check credentials in `~/.aws/credentials`
- Regenerate access key: AWS Console → IAM → Users → Security credentials → Create access key
- Run `aws configure` again with new credentials

### Issue: "AccessDenied: User is not authorized to perform: kms:CreateKey"
**Solution:**
- Go to AWS Console → IAM → Users → Permissions
- Attach the 3 policies mentioned in Step 3
- Wait 30 seconds for permissions to apply
- Try running setup script again

### Issue: "The credential provider chain was exhausted"
**Solution:**
```bash
# Check if file exists
cat ~/.aws/credentials

# If not, run configuration
aws configure

# If exists, restart PowerShell and try again
```

---

## 📚 Full Documentation

See: `AWS_CREDENTIALS_SETUP.md` (in root directory) for complete guide

---

## ✅ Verification Checklist

Before running setup scripts, verify:

- [ ] AWS CLI installed: `aws --version`
- [ ] Credentials configured: `aws sts get-caller-identity` returns user info
- [ ] Troubleshooting script passes: `python troubleshoot_credentials.py`
- [ ] Access Key ID visible: `aws sts get-caller-identity` shows Arn with username
- [ ] Region set to us-east-1: `aws configure get region`

---

## 🚀 Ready to Deploy?

Once all checks pass:

```bash
# 1. Setup Secrets Manager
python aws_setup_scripts/setup_secrets_manager.py --environment staging --create-kms-key

# 2. Verify setup
python aws_setup_scripts/verify_secrets_manager.py --environment staging

# 3. Setup monitoring
python aws_setup_scripts/setup_monitoring.py --environment staging --email admin@tipsytheoryy.com

# 4. Continue with staging deployment
# See: PHASE_1_STAGING_DEPLOYMENT_GUIDE.md
```

---

**Need Help?**
- Email: backend-devops@tipsytheoryy.com
- AWS Support: https://console.aws.amazon.com/support/
- Docs: AWS_CREDENTIALS_SETUP.md

**Status:** Ready when credentials configured ✅

