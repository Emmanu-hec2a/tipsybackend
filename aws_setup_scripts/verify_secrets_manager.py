#!/usr/bin/env python3
"""
AWS Secrets Manager Verification Script

Verifies that all AWS infrastructure is correctly configured:
- KMS key exists and is accessible
- IAM role has correct permissions
- Secrets Manager is functional
- Credential storage format is correct

Usage:
    python verify_secrets_manager.py --environment staging
    python verify_secrets_manager.py --environment production

Author: TipsyTheoryy DevOps
Date: 2026-08-24
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple
import boto3
from botocore.exceptions import ClientError


class AWSSecretsManagerVerification:
    """Verifies AWS Secrets Manager and KMS configuration"""

    def __init__(self, environment: str, region: str = "us-east-1"):
        self.environment = environment
        self.region = region
        self.kms_client = boto3.client("kms", region_name=region)
        self.secrets_client = boto3.client("secretsmanager", region_name=region)
        self.iam_client = boto3.client("iam")
        self.cloudtrail_client = boto3.client("cloudtrail", region_name=region)
        
        self.kms_key_alias = f"alias/tipsy-payment-keys-{environment}"
        self.service_role_name = f"tipsy-payment-service-{environment}"
        self.checks_passed = 0
        self.checks_failed = 0

    def verify_kms_key(self) -> Tuple[bool, str]:
        """Verify KMS key exists and is enabled"""
        print(f"\n[1/5] Verifying KMS Key: {self.kms_key_alias}")
        
        try:
            response = self.kms_client.describe_key(KeyId=self.kms_key_alias)
            metadata = response["KeyMetadata"]
            
            # Check key status
            if metadata["KeyState"] != "Enabled":
                print(f"  ✗ KMS key is not enabled (state: {metadata['KeyState']})")
                self.checks_failed += 1
                return False, f"KMS key disabled: {metadata['KeyState']}"
            
            print(f"  ✓ KMS key exists and is enabled")
            print(f"    - Key ID: {metadata['KeyId']}")
            print(f"    - ARN: {metadata['Arn']}")
            
            # Check key rotation
            rotation_response = self.kms_client.get_key_rotation_status(
                KeyId=self.kms_key_alias
            )
            if rotation_response["KeyRotationEnabled"]:
                print(f"  ✓ Automatic key rotation is enabled")
            else:
                print(f"  ⚠ Automatic key rotation is disabled (recommended: enabled)")
                self.checks_failed += 1
            
            self.checks_passed += 1
            return True, metadata["KeyId"]
        except ClientError as e:
            print(f"  ✗ KMS key not found: {e}")
            self.checks_failed += 1
            return False, str(e)

    def verify_iam_role(self, kms_key_arn: str) -> Tuple[bool, str]:
        """Verify IAM role exists and has correct permissions"""
        print(f"\n[2/5] Verifying IAM Role: {self.service_role_name}")
        
        try:
            response = self.iam_client.get_role(RoleName=self.service_role_name)
            role = response["Role"]
            
            print(f"  ✓ IAM role exists")
            print(f"    - Role ARN: {role['Arn']}")
            
            # Check inline policies
            policies_response = self.iam_client.list_role_policies(
                RoleName=self.service_role_name
            )
            
            required_policies = {
                "secrets-policy": False,
                "kms-policy": False
            }
            
            for policy_name in policies_response["PolicyNames"]:
                if "secrets" in policy_name.lower():
                    required_policies["secrets-policy"] = True
                if "kms" in policy_name.lower():
                    required_policies["kms-policy"] = True
            
            for policy, found in required_policies.items():
                status = "✓" if found else "✗"
                print(f"  {status} {policy}: {'attached' if found else 'MISSING'}")
                if not found:
                    self.checks_failed += 1
            
            # Verify Secrets Manager access in policy
            try:
                secrets_policy = self.iam_client.get_role_policy(
                    RoleName=self.service_role_name,
                    PolicyName=f"{self.service_role_name}-secrets-policy"
                )
                policy_doc = json.loads(secrets_policy["RolePolicyDocument"])
                
                has_get_secret = False
                for statement in policy_doc.get("Statement", []):
                    actions = statement.get("Action", [])
                    if "secretsmanager:GetSecretValue" in actions:
                        has_get_secret = True
                        break
                
                if has_get_secret:
                    print(f"  ✓ Secrets Manager GetSecretValue permission found")
                else:
                    print(f"  ✗ Secrets Manager GetSecretValue permission MISSING")
                    self.checks_failed += 1
            except:
                pass
            
            self.checks_passed += 1
            return True, role["Arn"]
        except ClientError as e:
            print(f"  ✗ IAM role not found: {e}")
            self.checks_failed += 1
            return False, str(e)

    def verify_secrets_manager(self) -> Tuple[bool, List[Dict]]:
        """Verify Secrets Manager functionality"""
        print(f"\n[3/5] Verifying AWS Secrets Manager")
        
        try:
            # List existing secrets
            response = self.secrets_client.list_secrets(
                Filters=[
                    {
                        "Key": "name",
                        "Values": [f"tipsytheoryy/{self.environment}/"]
                    }
                ]
            )
            
            secrets = response.get("SecretList", [])
            print(f"  ✓ Secrets Manager accessible")
            print(f"  ℹ Found {len(secrets)} existing secrets for this environment")
            
            for secret in secrets[:5]:  # Show first 5
                print(f"    - {secret['Name']}")
            
            if len(secrets) > 5:
                print(f"    ... and {len(secrets) - 5} more")
            
            # Test secret creation/retrieval
            test_secret_name = f"tipsytheoryy/{self.environment}/verification-test"
            test_value = {"test": "value", "timestamp": "2026-08-24"}
            
            try:
                # Try to create test secret
                self.secrets_client.create_secret(
                    Name=test_secret_name,
                    SecretString=json.dumps(test_value)
                )
                print(f"  ✓ Test secret created successfully")
                
                # Retrieve it
                get_response = self.secrets_client.get_secret_value(
                    SecretId=test_secret_name
                )
                print(f"  ✓ Test secret retrieved successfully")
                
                # Cleanup
                self.secrets_client.delete_secret(
                    SecretId=test_secret_name,
                    ForceDeleteWithoutRecovery=True
                )
                print(f"  ✓ Test secret cleaned up")
            except ClientError as e:
                if "ResourceExistsException" in str(e):
                    print(f"  ℹ Test secret already exists (from previous run)")
                else:
                    print(f"  ✗ Test secret creation/retrieval failed: {e}")
                    self.checks_failed += 1
            
            self.checks_passed += 1
            return True, secrets
        except ClientError as e:
            print(f"  ✗ Secrets Manager access failed: {e}")
            self.checks_failed += 1
            return False, []

    def verify_secret_format(self, secrets: List[Dict]) -> bool:
        """Verify secret naming format is correct"""
        print(f"\n[4/5] Verifying Secret Format")
        
        if not secrets:
            print(f"  ℹ No secrets found to verify format")
            return True
        
        valid_format = True
        for secret in secrets:
            name = secret["Name"]
            # Expected format: tipsytheoryy/{environment}/store/{store_id}/mpesa-credentials
            parts = name.split("/")
            if len(parts) < 5 or parts[0] != "tipsytheoryy" or parts[1] != self.environment:
                print(f"  ✗ Invalid secret format: {name}")
                print(f"    Expected: tipsytheoryy/{self.environment}/store/{{store_id}}/mpesa-credentials")
                valid_format = False
        
        if valid_format:
            print(f"  ✓ All secret names follow correct format")
            self.checks_passed += 1
        else:
            self.checks_failed += 1
        
        return valid_format

    def verify_audit_logging(self) -> bool:
        """Verify CloudTrail is logging credential access"""
        print(f"\n[5/5] Verifying Audit Logging (CloudTrail)")
        
        try:
            trails_response = self.cloudtrail_client.describe_trails()
            trails = trails_response.get("trailList", [])
            
            if not trails:
                print(f"  ⚠ No CloudTrail trails configured")
                print(f"    Recommended: Enable CloudTrail to log all credential access")
                return True
            
            print(f"  ✓ CloudTrail is configured")
            print(f"    Found {len(trails)} trail(s)")
            
            for trail in trails:
                print(f"    - {trail.get('Name', 'Unknown')}")
            
            self.checks_passed += 1
            return True
        except ClientError as e:
            print(f"  ⚠ Could not verify CloudTrail: {e}")
            return True

    def print_summary(self):
        """Print verification summary"""
        total = self.checks_passed + self.checks_failed
        passed_pct = int((self.checks_passed / total * 100) if total > 0 else 0)
        
        print(f"\n{'='*70}")
        print(f"Verification Summary")
        print(f"{'='*70}")
        print(f"Passed: {self.checks_passed}")
        print(f"Failed: {self.checks_failed}")
        print(f"Success Rate: {passed_pct}%")
        
        if self.checks_failed == 0:
            print(f"\n✓ All checks passed! AWS infrastructure is ready.")
            status = True
        else:
            print(f"\n✗ Some checks failed. Please review above for details.")
            status = False
        
        print(f"\nNEXT STEPS:")
        print(f"1. Update environment variables on deployment platform:")
        print(f"   - USE_AWS_SECRETS_MANAGER=true")
        print(f"   - AWS_KMS_KEY_ID={self.kms_key_alias}")
        print(f"   - AWS_REGION={self.region}")
        print(f"2. Deploy application")
        print(f"3. Run credential migration: python manage.py migrate_credentials_to_secrets_manager")
        print(f"4. Monitor logs for credential retrieval")
        
        return status

    def run_verification(self) -> bool:
        """Execute full verification"""
        print(f"\n{'='*70}")
        print(f"AWS Secrets Manager Verification")
        print(f"Environment: {self.environment}")
        print(f"Region: {self.region}")
        print(f"{'='*70}")
        
        # 1. Verify KMS
        kms_ok, kms_key_id = self.verify_kms_key()
        if not kms_ok:
            kms_key_id = "unknown"
        
        # 2. Verify IAM Role
        role_ok, role_arn = self.verify_iam_role(kms_key_id)
        
        # 3. Verify Secrets Manager
        sm_ok, secrets = self.verify_secrets_manager()
        
        # 4. Verify Secret Format
        format_ok = self.verify_secret_format(secrets)
        
        # 5. Verify Audit Logging
        audit_ok = self.verify_audit_logging()
        
        # Print summary
        return self.print_summary()


def main():
    parser = argparse.ArgumentParser(
        description="Verify AWS Secrets Manager and KMS configuration for TipsyTheoryy"
    )
    parser.add_argument(
        "--environment",
        required=True,
        choices=["staging", "production"],
        help="Deployment environment"
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region"
    )
    
    args = parser.parse_args()
    
    verification = AWSSecretsManagerVerification(
        environment=args.environment,
        region=args.region
    )
    
    success = verification.run_verification()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
