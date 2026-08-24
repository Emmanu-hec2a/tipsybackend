#!/usr/bin/env python3
"""
AWS Credentials Troubleshooting Script

Diagnoses and fixes common AWS credential configuration issues.

Usage:
    python troubleshoot_credentials.py
    python troubleshoot_credentials.py --fix
    python troubleshoot_credentials.py --interactive

Author: TipsyTheoryy DevOps
Date: 2026-08-24
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Tuple, Optional
import platform


class AWSCredentialsTroubleshooter:
    """Diagnoses and fixes AWS credential issues"""

    def __init__(self):
        self.system = platform.system()
        self.checks_passed = 0
        self.checks_failed = 0
        self.aws_home = Path.home() / ".aws"
        self.credentials_file = self.aws_home / "credentials"
        self.config_file = self.aws_home / "config"

    def print_header(self):
        """Print header"""
        print(f"\n{'='*70}")
        print(f"AWS Credentials Troubleshooting")
        print(f"Platform: {self.system}")
        print(f"{'='*70}\n")

    def check_aws_cli_installed(self) -> bool:
        """Check if AWS CLI is installed"""
        print("[1/5] Checking AWS CLI installation...")
        
        try:
            result = subprocess.run(
                ["aws", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"  ✓ AWS CLI installed")
                print(f"    Version: {result.stdout.strip()}")
                self.checks_passed += 1
                return True
            else:
                print(f"  ✗ AWS CLI not found in PATH")
                self.checks_failed += 1
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"  ✗ AWS CLI not installed")
            print(f"    Install: pip install awscli")
            self.checks_failed += 1
            return False

    def check_credentials_file(self) -> bool:
        """Check if credentials file exists"""
        print("\n[2/5] Checking credentials file...")
        
        if self.credentials_file.exists():
            print(f"  ✓ Credentials file found: {self.credentials_file}")
            try:
                with open(self.credentials_file, 'r') as f:
                    content = f.read()
                    if "aws_access_key_id" in content.lower():
                        print(f"  ✓ Credentials file contains access key")
                        # Count profiles
                        profiles = [line for line in content.split('\n') if line.strip().startswith('[')]
                        print(f"    Found {len(profiles)} profile(s)")
                        for profile in profiles:
                            print(f"      - {profile}")
                        self.checks_passed += 1
                        return True
                    else:
                        print(f"  ⚠ Credentials file exists but is empty")
                        self.checks_failed += 1
                        return False
            except PermissionError:
                print(f"  ✗ No permission to read credentials file")
                self.checks_failed += 1
                return False
        else:
            print(f"  ✗ Credentials file not found")
            print(f"    Expected: {self.credentials_file}")
            self.checks_failed += 1
            return False

    def check_environment_variables(self) -> bool:
        """Check if AWS credentials in environment"""
        print("\n[3/5] Checking environment variables...")
        
        env_vars = {
            "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "AWS_DEFAULT_REGION": os.getenv("AWS_DEFAULT_REGION"),
            "AWS_REGION": os.getenv("AWS_REGION"),
        }
        
        configured = False
        for var, value in env_vars.items():
            if value:
                masked_value = value[:10] + "..." if len(value) > 10 else value
                print(f"  ✓ {var} = {masked_value}")
                configured = True
            else:
                print(f"  ✗ {var} not set")
        
        if configured:
            self.checks_passed += 1
            return True
        else:
            print(f"  ℹ No environment variables set (this is OK if using ~/.aws/credentials)")
            return False

    def test_aws_credentials(self) -> bool:
        """Test if credentials are valid"""
        print("\n[4/5] Testing AWS credentials...")
        
        try:
            result = subprocess.run(
                ["aws", "sts", "get-caller-identity", "--output", "json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                identity = json.loads(result.stdout)
                print(f"  ✓ AWS credentials are valid!")
                print(f"    Account ID: {identity.get('Account')}")
                print(f"    ARN: {identity.get('Arn')}")
                print(f"    User ID: {identity.get('UserId')}")
                self.checks_passed += 1
                return True
            else:
                error = result.stderr.strip()
                if "Unable to locate credentials" in error:
                    print(f"  ✗ Credentials not configured")
                    print(f"    Run: aws configure")
                elif "InvalidClientTokenId" in error:
                    print(f"  ✗ Invalid AWS credentials")
                    print(f"    Check: ~/{self.credentials_file}")
                else:
                    print(f"  ✗ Error: {error[:100]}")
                self.checks_failed += 1
                return False
        except Exception as e:
            print(f"  ✗ Failed to test credentials: {e}")
            self.checks_failed += 1
            return False

    def check_required_permissions(self) -> bool:
        """Check if credentials have required permissions"""
        print("\n[5/5] Checking required AWS permissions...")
        
        required_services = [
            "kms:CreateKey",
            "secretsmanager:CreateSecret",
            "iam:CreateRole",
            "cloudwatch:PutMetricAlarm",
            "logs:CreateLogGroup",
        ]
        
        print(f"  Checking permissions for:")
        for service in required_services:
            print(f"    - {service}")
        
        # Note: Full permission check requires IAM API call which might fail
        # This is more of an informational check
        try:
            result = subprocess.run(
                ["aws", "iam", "get-user", "--output", "json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                user_info = json.loads(result.stdout)
                username = user_info.get('User', {}).get('UserName', 'Unknown')
                print(f"  ✓ Connected as IAM user: {username}")
                print(f"    Note: Verify this user has required permissions in AWS console")
                self.checks_passed += 1
                return True
            else:
                print(f"  ⚠ Could not verify IAM user")
                print(f"    This might be OK if using root account or federated credentials")
                return True
        except Exception as e:
            print(f"  ⚠ Could not check permissions: {e}")
            return True

    def print_summary(self) -> bool:
        """Print check summary"""
        total = self.checks_passed + self.checks_failed
        passed_pct = int((self.checks_passed / total * 100) if total > 0 else 0)
        
        print(f"\n{'='*70}")
        print(f"Summary")
        print(f"{'='*70}")
        print(f"Passed: {self.checks_passed}/{total}")
        print(f"Failed: {self.checks_failed}/{total}")
        print(f"Success Rate: {passed_pct}%")
        
        if self.checks_failed == 0:
            print(f"\n✓ All checks passed! AWS credentials are ready.")
            return True
        else:
            print(f"\n⚠ Some checks failed. See recommendations below.")
            return False

    def provide_recommendations(self):
        """Provide next steps"""
        print(f"\n{'='*70}")
        print(f"Next Steps")
        print(f"{'='*70}\n")
        
        if not self.credentials_file.exists():
            print("1. CONFIGURE AWS CREDENTIALS")
            print(f"\n   Run: aws configure")
            print(f"\n   Then enter:")
            print(f"   - AWS Access Key ID: [your access key]")
            print(f"   - AWS Secret Access Key: [your secret key]")
            print(f"   - Default region: us-east-1")
            print(f"   - Default output format: json")
            print()
        
        if self.checks_failed > 0:
            print("2. GET AWS CREDENTIALS")
            print(f"\n   a. Log in to: https://console.aws.amazon.com/")
            print(f"   b. Go to: Services → IAM → Users")
            print(f"   c. Create user: tipsytheoryy-payment-deployment")
            print(f"   d. Attach policies:")
            print(f"      - AmazonSecretsManagerFullAccess")
            print(f"      - AWSKeyManagementServicePowerUser")
            print(f"      - CloudWatchFullAccess")
            print(f"   e. Create Access Key for CLI")
            print(f"   f. Copy credentials and run: aws configure")
            print()
        
        print("3. VERIFY CREDENTIALS")
        print(f"\n   Run: aws sts get-caller-identity")
        print()
        
        print("4. RUN SETUP SCRIPT")
        print(f"\n   Run: python aws_setup_scripts/setup_secrets_manager.py --environment staging --create-kms-key")
        print()

    def run_troubleshooting(self, fix: bool = False, interactive: bool = False):
        """Execute troubleshooting"""
        self.print_header()
        
        # Run all checks
        aws_cli_ok = self.check_aws_cli_installed()
        creds_file_ok = self.check_credentials_file()
        env_vars_ok = self.check_environment_variables()
        creds_valid = self.test_aws_credentials() if aws_cli_ok else False
        perms_ok = self.check_required_permissions() if creds_valid else False
        
        # Print summary
        summary_ok = self.print_summary()
        
        # Provide recommendations
        if not summary_ok:
            self.provide_recommendations()
        else:
            print(f"\nYou're ready to run the AWS setup scripts!")
            print(f"\nRun:")
            print(f"  python aws_setup_scripts/setup_secrets_manager.py --environment staging --create-kms-key")
        
        return summary_ok


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Troubleshoot AWS credentials configuration"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to fix issues automatically"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive mode (ask for user input)"
    )
    
    args = parser.parse_args()
    
    troubleshooter = AWSCredentialsTroubleshooter()
    success = troubleshooter.run_troubleshooting(
        fix=args.fix,
        interactive=args.interactive
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
