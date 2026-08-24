# AWS Credentials Setup Guide

**Problem:** "Unable to locate credentials" when running AWS setup scripts  
**Solution:** Configure AWS credentials for your local machine or deployment environment

---

## Option 1: AWS CLI Configuration (Recommended)

### Step 1: Install AWS CLI (if not already installed)
```bash
# Windows - using pip
pip install awscli

# Verify installation
aws --version
# Output: aws-cli/2.x.x Python/3.x.x ...
```

### Step 2: Create IAM User with Programmatic Access
1. Go to AWS Management Console → IAM → Users
2. Click "Create User"
3. Set username: `tipsytheoryy-payment-deployment`
4. Select "Access Key - Programmatic access"
5. Create policy or attach existing: `AmazonSecretsManagerFullAccess` + `AWSKeyManagementServicePowerUser`
6. Copy the Access Key ID and Secret Access Key

### Step 3: Configure AWS Credentials Locally

```bash
# Run AWS CLI configuration wizard
aws configure

# It will prompt for:
# AWS Access Key ID: [paste your access key]
# AWS Secret Access Key: [paste your secret key]
# Default region name: us-east-1
# Default output format: json
```

This creates files:
- `~/.aws/credentials` (stores keys)
- `~/.aws/config` (stores region/output format)

### Step 4: Verify Credentials Work

```bash
# Test AWS credentials
aws sts get-caller-identity

# Expected output:
# {
#     "UserId": "AIDACKCEVSQ6C2EXAMPLE",
#     "Account": "123456789012",
#     "Arn": "arn:aws:iam::123456789012:user/tipsytheoryy-payment-deployment"
# }
```

---

## Option 2: Environment Variables

### For Current Terminal Session (Temporary)

```powershell
# PowerShell
$env:AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE"
$env:AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
$env:AWS_DEFAULT_REGION="us-east-1"

# Verify
$env:AWS_ACCESS_KEY_ID
```

### For Persistent Configuration (Windows)

```bash
# Set system environment variables
setx AWS_ACCESS_KEY_ID "AKIAIOSFODNN7EXAMPLE"
setx AWS_SECRET_ACCESS_KEY "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
setx AWS_DEFAULT_REGION "us-east-1"

# Restart PowerShell for changes to take effect
# Verify
echo $env:AWS_ACCESS_KEY_ID
```

---

## Option 3: For CI/CD Pipeline (GitHub Actions)

Add to your GitHub repository secrets:

1. Go to Settings → Secrets and variables → Actions
2. Create secrets:
   - `AWS_ACCESS_KEY_ID` = your access key
   - `AWS_SECRET_ACCESS_KEY` = your secret key
   - `AWS_REGION` = us-east-1

3. Update workflow file:
```yaml
- name: Set up AWS credentials
  env:
    AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
    AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    AWS_DEFAULT_REGION: ${{ secrets.AWS_REGION }}
  run: |
    python aws_setup_scripts/setup_secrets_manager.py --environment staging --create-kms-key
```

---

## Step-by-Step: Get Your AWS Credentials

### 1. Log in to AWS Management Console
- URL: https://console.aws.amazon.com/
- Login with your AWS account

### 2. Create IAM User
```
1. Click "Services" → "IAM"
2. Left menu → "Users"
3. Click "Create user"
4. Username: tipsytheoryy-payment-deployment
5. Click Next
6. Select "Attach policies directly"
7. Search and select:
   - AmazonSecretsManagerFullAccess
   - AWSKeyManagementServicePowerUser
   - CloudWatchFullAccess (for monitoring)
8. Click "Create user"
```

### 3. Create Access Key
```
1. Click on the new user name
2. Tab: "Security credentials"
3. Click "Create access key"
4. Select "Command Line Interface (CLI)"
5. Check "I understand..."
6. Click "Create access key"
7. COPY the Access Key ID and Secret Access Key (only shown once!)
```

### 4. Configure Locally
```bash
# PowerShell
aws configure

# Enter:
# AWS Access Key ID: [paste access key]
# AWS Secret Access Key: [paste secret key]
# Default region name: us-east-1
# Default output format: json
```

### 5. Verify
```bash
aws sts get-caller-identity
```

---

## IAM Policy Requirements

The IAM user needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "kms:CreateKey",
        "kms:DescribeKey",
        "kms:EnableKeyRotation",
        "kms:GetKeyRotationStatus",
        "kms:CreateAlias",
        "kms:ListAliases",
        "kms:ListKeys"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret",
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:ListSecrets",
        "secretsmanager:DeleteSecret"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:tipsytheoryy/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:GetRole",
        "iam:PutRolePolicy",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy"
      ],
      "Resource": "arn:aws:iam::*:role/tipsy-payment-service-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:PutDashboard",
        "cloudwatch:ListDashboards"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:PutRetentionPolicy",
        "logs:PutMetricFilter"
      ],
      "Resource": "arn:aws:logs:*:*:log-group:/tipsytheoryy/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sns:CreateTopic",
        "sns:Subscribe",
        "sns:ListTopics"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Troubleshooting

### Error: "UnrecognizedClientException: The security token included in the request is invalid"
- **Cause:** Invalid/expired credentials
- **Solution:** 
  - Check credentials in `~/.aws/credentials`
  - Regenerate access key in AWS console
  - Run `aws configure` again

### Error: "AccessDenied: User is not authorized to perform: kms:CreateKey"
- **Cause:** IAM user lacks KMS permissions
- **Solution:**
  - Attach `AWSKeyManagementServicePowerUser` policy
  - Or use AWS root account (not recommended for production)

### Error: "Could not connect to the endpoint URL"
- **Cause:** Wrong region or network issue
- **Solution:**
  - Verify region: `aws configure get region`
  - Check internet connection
  - Verify AWS services are operational

### Error: "The credential provider chain was exhausted without finding valid credentials"
- **Cause:** Credentials not configured anywhere
- **Solution:**
  - Run `aws configure`
  - Or set environment variables
  - Or check `~/.aws/credentials` file exists

---

## Once Credentials are Configured

After setting up AWS credentials, try again:

```bash
# Verify credentials work
aws sts get-caller-identity

# Expected output:
# {
#     "UserId": "AIDACKCEVSQ6C2EXAMPLE",
#     "Account": "123456789012",
#     "Arn": "arn:aws:iam::123456789012:user/tipsytheoryy-payment-deployment"
# }

# Now run the setup script
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
# [2/5] Setting up IAM role: tipsy-payment-service-staging
#   ✓ IAM role created: tipsy-payment-service-staging
#   ✓ Secrets Manager policy attached
#   ✓ KMS policy attached
#
# ✓ AWS Setup Complete!
```

---

## Next Steps

Once credentials are configured and setup script succeeds:

```bash
# 1. Verify AWS setup
python aws_setup_scripts/verify_secrets_manager.py --environment staging

# 2. Setup monitoring and alerts
python aws_setup_scripts/setup_monitoring.py --environment staging --email admin@tipsytheoryy.com

# 3. Continue with staging deployment
# See: PHASE_1_STAGING_DEPLOYMENT_GUIDE.md
```

---

## Security Best Practices

⚠️ **NEVER:**
- Share access keys in Slack, email, or GitHub
- Commit access keys to version control
- Use root AWS account credentials
- Store credentials in plain text files

✅ **ALWAYS:**
- Use IAM users with limited permissions
- Rotate access keys every 90 days
- Use environment variables or `~/.aws/credentials`
- Enable MFA on AWS root account
- Use separate credentials for staging and production

---

## Troubleshooting Script Added

See: `aws_setup_scripts/troubleshoot_credentials.py` for automated diagnostics

```bash
python aws_setup_scripts/troubleshoot_credentials.py
```

This will check:
- AWS CLI installed
- Credentials configured
- Credentials valid
- Required permissions
- AWS services accessible

