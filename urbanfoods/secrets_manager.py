"""
AWS Secrets Manager Integration for Payment Credentials

Implements secure credential storage using AWS Secrets Manager instead of
local database encryption. This provides:

1. Centralized key management
2. Automatic key rotation (60-day policy)
3. Audit logging via CloudTrail
4. IAM-based access control
5. Encryption with AWS KMS

PCI DSS Requirement 3.2.1: Encryption key management must use strong cryptography
"""

import json
import boto3
import logging
from typing import Optional, Dict, Any
from django.conf import settings
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class SecretsManager:
    """
    Secure credential storage using AWS Secrets Manager.
    
    Features:
    - Centralized key management
    - Automatic rotation policies
    - CloudTrail audit logging
    - KMS encryption
    
    Usage:
        sm = SecretsManager()
        credentials = sm.get_store_credentials(store_id=123)
        sm.store_credentials(store_id=123, credentials={'key': 'value'})
    """
    
    def __init__(self):
        """Initialize AWS Secrets Manager client."""
        self.region = settings.AWS_REGION or 'us-east-1'
        self.client = boto3.client('secretsmanager', region_name=self.region)
        self.kms_key_id = settings.AWS_KMS_KEY_ID or 'alias/tipsy-payment-keys'
    
    def _get_secret_name(self, store_id: int) -> str:
        """
        Generate the Secrets Manager secret name for a store.
        
        Format: tipsytheoryy/store/{store_id}/mpesa-credentials
        
        Args:
            store_id: Store database ID
        
        Returns:
            Secret name in Secrets Manager
        """
        return f"tipsytheoryy/store/{store_id}/mpesa-credentials"
    
    def get_store_credentials(self, store_id: int) -> Optional[Dict[str, str]]:
        """
        Retrieve M-Pesa credentials for a store from Secrets Manager.
        
        Args:
            store_id: Store database ID
        
        Returns:
            Dictionary with keys: consumer_key, consumer_secret, passkey, shortcode
            None if credentials don't exist or error occurs
        """
        try:
            secret_name = self._get_secret_name(store_id)
            response = self.client.get_secret_value(SecretId=secret_name)
            
            if 'SecretString' in response:
                credentials = json.loads(response['SecretString'])
                logger.info(f"Retrieved credentials from Secrets Manager for store {store_id}")
                return credentials
            else:
                logger.warning(f"Secret {secret_name} is stored as binary, not JSON")
                return None
                
        except self.client.exceptions.ResourceNotFoundException:
            logger.warning(f"Credentials not found in Secrets Manager for store {store_id}")
            return None
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(f"AWS Secrets Manager error ({error_code}) for store {store_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving credentials for store {store_id}: {str(e)}")
            return None
    
    def store_credentials(self, store_id: int, credentials: Dict[str, str]) -> bool:
        """
        Store M-Pesa credentials in Secrets Manager.
        
        Args:
            store_id: Store database ID
            credentials: Dictionary with keys: consumer_key, consumer_secret, passkey, shortcode
        
        Returns:
            True if successful, False otherwise
        """
        try:
            secret_name = self._get_secret_name(store_id)
            secret_value = json.dumps(credentials)
            
            # Try to update existing secret first
            try:
                response = self.client.update_secret(
                    SecretId=secret_name,
                    SecretString=secret_value,
                    KmsKeyId=self.kms_key_id
                )
                logger.info(f"Updated credentials in Secrets Manager for store {store_id}")
                return True
            except self.client.exceptions.ResourceNotFoundException:
                # Secret doesn't exist, create it
                response = self.client.create_secret(
                    Name=secret_name,
                    SecretString=secret_value,
                    KmsKeyId=self.kms_key_id,
                    Tags=[
                        {'Key': 'Service', 'Value': 'TipsyTheoryy'},
                        {'Key': 'Component', 'Value': 'PaymentProcessing'},
                        {'Key': 'Environment', 'Value': settings.DJANGO_ENV or 'production'},
                    ]
                )
                logger.info(f"Created credentials in Secrets Manager for store {store_id}")
                return True
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(f"AWS Secrets Manager error ({error_code}) storing credentials for store {store_id}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error storing credentials for store {store_id}: {str(e)}")
            return False
    
    def delete_credentials(self, store_id: int, recovery_days: int = 7) -> bool:
        """
        Delete credentials from Secrets Manager with recovery window.
        
        Args:
            store_id: Store database ID
            recovery_days: Days before permanent deletion (AWS minimum: 7)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            secret_name = self._get_secret_name(store_id)
            response = self.client.delete_secret(
                SecretId=secret_name,
                RecoveryWindowInDays=max(7, recovery_days)  # AWS minimum is 7
            )
            logger.warning(f"Deleted credentials for store {store_id} with {recovery_days} day recovery window")
            return True
        except ClientError as e:
            logger.error(f"AWS Secrets Manager error deleting credentials for store {store_id}: {str(e)}")
            return False
    
    def rotate_credentials(self, store_id: int, rotation_lambda_arn: str = None) -> bool:
        """
        Enable automatic credential rotation for a store.
        
        Args:
            store_id: Store database ID
            rotation_lambda_arn: ARN of Lambda function to handle rotation
        
        Returns:
            True if successful, False otherwise
        """
        try:
            secret_name = self._get_secret_name(store_id)
            
            if not rotation_lambda_arn:
                rotation_lambda_arn = settings.AWS_ROTATION_LAMBDA_ARN
            
            if not rotation_lambda_arn:
                logger.warning("No rotation Lambda ARN configured")
                return False
            
            response = self.client.rotate_secret(
                SecretId=secret_name,
                RotationLambdaARN=rotation_lambda_arn,
                RotationRules={
                    'AutomaticallyAfterDays': 60  # 60-day rotation policy
                }
            )
            logger.info(f"Enabled automatic rotation for store {store_id} credentials")
            return True
        except ClientError as e:
            logger.error(f"AWS Secrets Manager error enabling rotation for store {store_id}: {str(e)}")
            return False
    
    def list_secrets(self, tag_filter: str = 'PaymentProcessing') -> list:
        """
        List all payment-related secrets in Secrets Manager.
        
        Args:
            tag_filter: Filter by tag value
        
        Returns:
            List of secret metadata
        """
        try:
            secrets = []
            paginator = self.client.get_paginator('list_secrets')
            
            for page in paginator.paginate(
                Filters=[
                    {
                        'Key': 'tag-key',
                        'Values': ['Component']
                    }
                ]
            ):
                for secret in page.get('SecretList', []):
                    if tag_filter in str(secret.get('Tags', [])):
                        secrets.append({
                            'Name': secret['Name'],
                            'ARN': secret['ARN'],
                            'LastRotated': secret.get('LastRotatedDate'),
                            'LastUpdated': secret.get('LastUpdatedDate'),
                        })
            
            return secrets
        except ClientError as e:
            logger.error(f"Error listing secrets: {str(e)}")
            return []


class HybridCredentialStore:
    """
    Hybrid storage supporting both local Fernet encryption and AWS Secrets Manager.
    
    This allows gradual migration from local encryption to Secrets Manager
    without requiring immediate database changes.
    
    Priority order:
    1. Try AWS Secrets Manager first (if configured)
    2. Fall back to local Fernet encryption
    3. Return None if neither works
    """
    
    def __init__(self):
        self.use_secrets_manager = getattr(settings, 'USE_AWS_SECRETS_MANAGER', False)
        if self.use_secrets_manager:
            self.sm = SecretsManager()
        else:
            self.sm = None
    
    def get_credentials(self, store_id: int, fallback_to_db: bool = True) -> Optional[Dict[str, str]]:
        """
        Get credentials with fallback strategy.
        
        Args:
            store_id: Store database ID
            fallback_to_db: If True, fall back to local encryption if Secrets Manager fails
        
        Returns:
            Dictionary with credentials or None
        """
        # Try Secrets Manager first if enabled
        if self.use_secrets_manager and self.sm:
            creds = self.sm.get_store_credentials(store_id)
            if creds:
                return creds
            
            if not fallback_to_db:
                return None
        
        # Fall back to local Fernet encryption from database
        from urbanfoods.mpesa_utils import decrypt_value
        from urbanfoods.models import Store
        
        try:
            store = Store.objects.get(id=store_id)
            return {
                'consumer_key': decrypt_value(store.mpesa_consumer_key),
                'consumer_secret': decrypt_value(store.mpesa_consumer_secret),
                'passkey': decrypt_value(store.mpesa_passkey),
                'shortcode': store.mpesa_shortcode,
            }
        except Exception as e:
            logger.error(f"Error getting credentials for store {store_id}: {str(e)}")
            return None
    
    def store_credentials(self, store_id: int, credentials: Dict[str, str]) -> bool:
        """
        Store credentials to appropriate backend.
        
        Args:
            store_id: Store database ID
            credentials: Dictionary with credentials
        
        Returns:
            True if successful
        """
        if self.use_secrets_manager and self.sm:
            success = self.sm.store_credentials(store_id, credentials)
            if not success:
                logger.error(f"Failed to store credentials to Secrets Manager for store {store_id}")
            return success
        else:
            # Store to local database
            from urbanfoods.mpesa_utils import encrypt_value
            from urbanfoods.models import Store
            
            try:
                store = Store.objects.get(id=store_id)
                store.mpesa_consumer_key = encrypt_value(credentials['consumer_key'])
                store.mpesa_consumer_secret = encrypt_value(credentials['consumer_secret'])
                store.mpesa_passkey = encrypt_value(credentials['passkey'])
                store.save()
                return True
            except Exception as e:
                logger.error(f"Error storing credentials for store {store_id}: {str(e)}")
                return False


def get_hybrid_credential_store() -> HybridCredentialStore:
    """Factory function to get hybrid credential store instance."""
    return HybridCredentialStore()
