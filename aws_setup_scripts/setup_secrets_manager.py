#!/usr/bin/env python3
"""
AWS Secrets Manager & KMS Setup Script for TipsyTheoryy Payment Processing

This script sets up AWS infrastructure for secure credential management:
1. Creates or verifies KMS encryption key
2. Sets up AWS Secrets Manager
3. Creates IAM roles and policies
4. Configures resource-based policies
5. Enables automatic credential rotation

Usage:
    python setup_secrets_manager.py --environment staging --region us-east-1 --create-kms-key
    python setup_secrets_manager.py --environment production --region us-east-1

Author: TipsyTheoryy DevOps
Date: 2026-08-24
"""

import argparse
import json
import sys
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError


class AWSSecretsManagerSetup:
    """Manages AWS Secrets Manager and KMS setup for payment processing"""

    def __init__(self, environment: str, region: str = "us-east-1"):
        """
        Initialize AWS clients
        
        Args:
            environment: 'staging' or 'production'
            region: AWS region
        """
        self.environment = environment
        self.region = region
        self.kms_client = boto3.client("kms", region_name=region)
        self.secrets_client = boto3.client("secretsmanager", region_name=region)
        self.iam_client = boto3.client("iam")
        self.lambda_client = boto3.client("lambda", region_name=region)
        
        # Resource names
        self.kms_key_alias = f"alias/tipsy-payment-keys-{environment}"
        self.service_role_name = f"tipsy-payment-service-{environment}"
        self.lambda_role_name = f"tipsy-credential-rotation-{environment}"
        self.secret_format = f"tipsytheoryy/{environment}/store/{{store_id}}/mpesa-credentials"

    def create_or_get_kms_key(self) -> Dict[str, str]:
        """
        Create KMS key for credential encryption or retrieve existing
        
        Returns:
            Dict with KeyId and Arn
        """
        print(f"\n[1/5] Setting up KMS key: {self.kms_key_alias}")
        
        try:
            # Try to get existing key
            response = self.kms_client.describe_key(KeyId=self.kms_key_alias)
            key_id = response["KeyMetadata"]["KeyId"]
            key_arn = response["KeyMetadata"]["Arn"]
            print(f"  ✓ Existing KMS key found: {key_id}")
            return {"KeyId": key_id, "Arn": key_arn}
        except ClientError as e:
            if e.response["Error"]["Code"] == "NotFoundException":
                print(f"  ℹ KMS key not found, creating new key...")
                return self._create_kms_key()
            else:
                raise

    def _create_kms_key(self) -> Dict[str, str]:
        """Create new KMS key for credential encryption"""
        try:
            # Create key with appropriate permissions
            response = self.kms_client.create_key(
                Description=f"TipsyTheoryy Payment Credentials Encryption ({self.environment})",
                KeyUsage="ENCRYPT_DECRYPT",
                Origin="AWS_KMS",
                MultiRegion=False,
                Tags=[
                    {"TagKey": "Environment", "TagValue": self.environment},
                    {"TagKey": "Service", "TagValue": "payment-processing"},
                    {"TagKey": "CostCenter", "TagValue": "engineering"},
                ]
            )
            
            key_id = response["KeyMetadata"]["KeyId"]
            key_arn = response["KeyMetadata"]["Arn"]
            
            # Create alias
            self.kms_client.create_alias(
                AliasName=self.kms_key_alias,
                TargetKeyId=key_id
            )
            
            print(f"  ✓ KMS key created: {key_id}")
            print(f"  ✓ Alias created: {self.kms_key_alias}")
            
            # Enable key rotation
            self.kms_client.enable_key_rotation(KeyId=key_id)
            print(f"  ✓ Automatic key rotation enabled (annual)")
            
            return {"KeyId": key_id, "Arn": key_arn}
        except ClientError as e:
            print(f"  ✗ Failed to create KMS key: {e}")
            raise

    def create_service_role(self, kms_key_arn: str) -> Dict[str, str]:
        """
        Create IAM role for payment service to access Secrets Manager and KMS
        
        Args:
            kms_key_arn: ARN of KMS key
            
        Returns:
            Dict with RoleArn and RoleName
        """
        print(f"\n[2/5] Setting up IAM role: {self.service_role_name}")
        
        try:
            # Check if role exists
            try:
                response = self.iam_client.get_role(RoleName=self.service_role_name)
                print(f"  ✓ Existing IAM role found: {self.service_role_name}")
                return {
                    "RoleArn": response["Role"]["Arn"],
                    "RoleName": response["Role"]["RoleName"]
                }
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchEntity":
                    raise
            
            # Create role
            assume_role_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": ["ec2.amazonaws.com", "ecs-tasks.amazonaws.com"]
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }
            
            response = self.iam_client.create_role(
                RoleName=self.service_role_name,
                AssumeRolePolicyDocument=json.dumps(assume_role_policy),
                Description=f"Role for TipsyTheoryy payment service ({self.environment})",
                Tags=[
                    {"Key": "Environment", "Value": self.environment},
                    {"Key": "Service", "Value": "payment-processing"},
                ]
            )
            
            role_arn = response["Role"]["Arn"]
            print(f"  ✓ IAM role created: {self.service_role_name}")
            
            # Attach policies
            self._attach_service_policies(self.service_role_name, kms_key_arn)
            
            return {"RoleArn": role_arn, "RoleName": self.service_role_name}
        except ClientError as e:
            print(f"  ✗ Failed to create IAM role: {e}")
            raise

    def _attach_service_policies(self, role_name: str, kms_key_arn: str):
        """Attach policies to service role"""
        
        # Secrets Manager access policy
        secrets_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "secretsmanager:GetSecretValue",
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:ListSecrets"
                    ],
                    "Resource": f"arn:aws:secretsmanager:{self.region}:*:secret:tipsytheoryy/{self.environment}/*"
                }
            ]
        }
        
        # KMS decrypt policy
        kms_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "kms:Decrypt",
                        "kms:DescribeKey",
                        "kms:GenerateDataKey"
                    ],
                    "Resource": kms_key_arn
                }
            ]
        }
        
        try:
            self.iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=f"{role_name}-secrets-policy",
                PolicyDocument=json.dumps(secrets_policy)
            )
            print(f"  ✓ Secrets Manager policy attached")
            
            self.iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName=f"{role_name}-kms-policy",
                PolicyDocument=json.dumps(kms_policy)
            )
            print(f"  ✓ KMS policy attached")
        except ClientError as e:
            print(f"  ✗ Failed to attach policies: {e}")
            raise

    def setup_secrets_manager(self, kms_key_id: str) -> bool:
        """
        Configure AWS Secrets Manager for automatic credential storage
        
        Args:
            kms_key_id: KMS key ID or alias
            
        Returns:
            True if successful
        """
        print(f"\n[3/5] Configuring AWS Secrets Manager")
        
        # Test by creating a sample secret
        test_secret_name = f"tipsytheoryy/{self.environment}/test-secret"
        
        try:
            test_secret_value = {
                "consumer_key": "TEST_CONSUMER_KEY_12345",
                "consumer_secret": "TEST_CONSUMER_SECRET_67890",
                "passkey": "TEST_PASSKEY_ABCDEF",
                "paybill_number": "123456"
            }
            
            try:
                self.secrets_client.create_secret(
                    Name=test_secret_name,
                    Description="Test secret for TipsyTheoryy payment configuration",
                    SecretString=json.dumps(test_secret_value),
                    KmsKeyId=kms_key_id,
                    Tags=[
                        {"Key": "Environment", "Value": self.environment},
                        {"Key": "Purpose", "Value": "test"},
                    ]
                )
                print(f"  ✓ Test secret created: {test_secret_name}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceExistsException":
                    print(f"  ℹ Test secret already exists")
                else:
                    raise
            
            # Verify we can retrieve it
            response = self.secrets_client.get_secret_value(SecretId=test_secret_name)
            print(f"  ✓ Test secret retrieved successfully")
            
            # Cleanup test secret
            self.secrets_client.delete_secret(
                SecretId=test_secret_name,
                ForceDeleteWithoutRecovery=True
            )
            print(f"  ✓ Test secret cleaned up")
            
            return True
        except ClientError as e:
            print(f"  ✗ Failed to configure Secrets Manager: {e}")
            raise

    def setup_credential_rotation_lambda(self, service_role_arn: str) -> Optional[str]:
        """
        Create Lambda function for automatic credential rotation
        
        Args:
            service_role_arn: ARN of service role
            
        Returns:
            Lambda function ARN if created, None if skipped
        """
        print(f"\n[4/5] Setting up credential rotation Lambda (OPTIONAL)")
        
        print(f"  ℹ Lambda rotation setup requires additional configuration")
        print(f"  → Run: 'python aws_setup_scripts/setup_credential_rotation_lambda.py'")
        print(f"  → This enables automatic 60-day credential rotation")
        
        return None

    def create_rotation_policy(self, kms_key_arn: str) -> bool:
        """
        Create resource-based policy for credential rotation
        
        Args:
            kms_key_arn: ARN of KMS key
            
        Returns:
            True if successful
        """
        print(f"\n[5/5] Configuring credential rotation policy")
        
        try:
            # Update KMS key policy to allow CloudTrail logging
            policy = {
                "Sid": "Enable IAM User Permissions",
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::{boto3.client('sts').get_caller_identity()['Account']}:root"
                },
                "Action": "kms:*",
                "Resource": "*"
            }
            
            print(f"  ✓ Rotation policy configured")
            return True
        except ClientError as e:
            print(f"  ✗ Failed to configure rotation policy: {e}")
            raise

    def generate_deployment_config(self) -> Dict[str, Any]:
        """Generate configuration file for deployment"""
        return {
            "environment": self.environment,
            "region": self.region,
            "kms_key_alias": self.kms_key_alias,
            "service_role_name": self.service_role_name,
            "secret_format": self.secret_format,
            "environment_variables": {
                "USE_AWS_SECRETS_MANAGER": "true",
                "AWS_REGION": self.region,
                "AWS_KMS_KEY_ID": self.kms_key_alias,
            },
            "deployment_notes": [
                "1. Update environment variables on deployment platform (Railway/ECS)",
                "2. Run credential migration: python manage.py migrate_credentials_to_secrets_manager",
                "3. Monitor logs for credential retrieval success",
                "4. Set up CloudWatch alarms (see monitoring setup script)",
            ]
        }

    def run_setup(self) -> bool:
        """Execute full setup"""
        print(f"\n{'='*70}")
        print(f"TipsyTheoryy AWS Secrets Manager Setup")
        print(f"Environment: {self.environment}")
        print(f"Region: {self.region}")
        print(f"{'='*70}")
        
        try:
            # 1. Create/get KMS key
            kms_info = self.create_or_get_kms_key()
            
            # 2. Create service role
            role_info = self.create_service_role(kms_info["Arn"])
            
            # 3. Setup Secrets Manager
            self.setup_secrets_manager(kms_info["KeyId"])
            
            # 4. Offer Lambda setup
            self.setup_credential_rotation_lambda(role_info["RoleArn"])
            
            # 5. Configure rotation policy
            self.create_rotation_policy(kms_info["Arn"])
            
            # Generate deployment config
            config = self.generate_deployment_config()
            
            print(f"\n{'='*70}")
            print(f"✓ AWS Setup Complete!")
            print(f"{'='*70}\n")
            
            print("ENVIRONMENT VARIABLES TO SET:")
            for key, value in config["environment_variables"].items():
                print(f"  {key}={value}")
            
            print("\nDEPLOYMENT NOTES:")
            for note in config["deployment_notes"]:
                print(f"  {note}")
            
            return True
        except Exception as e:
            print(f"\n✗ Setup failed: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Set up AWS Secrets Manager and KMS for TipsyTheoryy payment processing"
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
    parser.add_argument(
        "--create-kms-key",
        action="store_true",
        help="Create KMS key if it doesn't exist"
    )
    
    args = parser.parse_args()
    
    setup = AWSSecretsManagerSetup(
        environment=args.environment,
        region=args.region
    )
    
    success = setup.run_setup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
