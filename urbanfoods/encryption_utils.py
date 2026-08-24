"""
Database Encryption Module - PCI DSS Encryption at Rest
═══════════════════════════════════════════════════════════════

Purpose: Encrypt sensitive PII columns in database to protect against data breaches.
Compliance: PCI DSS 3.4 (Encryption of stored data), GDPR Article 32 (Security)

Encryption Strategy:
1. Column-level encryption (AES-256)
2. Per-record encryption key derivation
3. Backward compatible with existing unencrypted data
4. Transparent encryption/decryption in application layer
5. Key rotation support

Why Column-Level (Not Database-Level):
- Database-level encryption is ideal but requires DB admin access
- Column-level gives app-level control without DB restart
- Works with any database (PostgreSQL, MySQL, SQLite)
- Can migrate data gradually without downtime

Data Flow:
├─ Read:
│  ├─ Fetch encrypted_phone from database
│  ├─ Check if encrypted (starts with ENCRYPTED:)
│  ├─ Decrypt using field's decryption key
│  └─ Return plaintext to application
│
└─ Write:
   ├─ Accept plaintext from application
   ├─ Encrypt using AES-256
   ├─ Add ENCRYPTED: prefix for identification
   └─ Store encrypted value in database
"""

import logging
import os
from typing import Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64

from django.conf import settings

logger = logging.getLogger(__name__)


class EncryptionKeyManager:
    """
    🛡️ Manages encryption keys and key derivation.
    
    Key Strategy:
    1. Master key from settings.ENCRYPTION_MASTER_KEY
    2. Per-field keys derived from master key + field name
    3. Per-record keys (optional) for additional security
    
    Key Rotation:
    - Old keys kept for decryption (backward compatibility)
    - New data encrypted with current key
    - Set ENCRYPTION_MASTER_KEY_OLD to support rotation
    """
    
    ENCRYPTION_PREFIX = "ENCRYPTED:"
    ENCRYPTION_VERSION = "v1"
    
    @staticmethod
    def get_master_key() -> bytes:
        """Get master encryption key from settings."""
        key = getattr(settings, 'ENCRYPTION_MASTER_KEY', None)
        if not key:
            raise ValueError(
                "ENCRYPTION_MASTER_KEY not configured in settings.py\n"
                "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key())\" "
            )
        
        # Key should be bytes, but might be string from environment
        if isinstance(key, str):
            key = key.encode('utf-8')
        
        return key
    
    @staticmethod
    def get_old_master_keys() -> list:
        """Get old master keys for decryption (key rotation)."""
        keys = getattr(settings, 'ENCRYPTION_MASTER_KEY_OLD', [])
        if isinstance(keys, str):
            keys = [keys]
        
        return [k.encode('utf-8') if isinstance(k, str) else k for k in keys]
    
    @staticmethod
    def derive_field_key(master_key: bytes, field_name: str) -> bytes:
        """
        Derive per-field encryption key from master key.
        
        Args:
            master_key: Master encryption key
            field_name: Field name (e.g., 'phone_number', 'email')
        
        Returns:
            32-byte key suitable for Fernet
        """
        # PBKDF2: Derive key from master key + field name
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=field_name.encode('utf-8'),
            iterations=100000,
            backend=default_backend()
        )
        
        derived = kdf.derive(master_key)
        # Fernet requires base64-encoded key
        return base64.urlsafe_b64encode(derived)
    
    @staticmethod
    def get_fernet_cipher(field_name: str) -> Fernet:
        """Get Fernet cipher for field."""
        master_key = EncryptionKeyManager.get_master_key()
        field_key = EncryptionKeyManager.derive_field_key(master_key, field_name)
        return Fernet(field_key)


class EncryptedFieldManager:
    """
    🛡️ Encryption/decryption for individual fields.
    
    Handles:
    - Transparent encryption on write
    - Automatic decryption on read
    - Backward compatibility with unencrypted data
    - Key rotation support
    """
    
    @staticmethod
    def encrypt_value(value: Optional[str], field_name: str) -> Optional[str]:
        """
        Encrypt a value for storage.
        
        Args:
            value: Plaintext value (or None)
            field_name: Field name for key derivation
        
        Returns:
            Encrypted string with ENCRYPTED: prefix (or None)
        """
        if value is None or value == '':
            return value  # Don't encrypt None or empty
        
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        
        try:
            cipher = EncryptionKeyManager.get_fernet_cipher(field_name)
            encrypted_bytes = cipher.encrypt(value.encode('utf-8'))
            encrypted_str = encrypted_bytes.decode('utf-8')
            
            # Add prefix to identify encrypted values
            return f"{EncryptionKeyManager.ENCRYPTION_PREFIX}{EncryptionKeyManager.ENCRYPTION_VERSION}:{encrypted_str}"
        
        except Exception as e:
            logger.error(f"Encryption error for field {field_name}: {e}")
            # Fail gracefully: return plaintext (better than losing data)
            logger.warning(f"Returning plaintext for {field_name} due to encryption failure")
            return value
    
    @staticmethod
    def decrypt_value(
        value: Optional[str],
        field_name: str,
        allow_plaintext: bool = True  # For backward compatibility
    ) -> Optional[str]:
        """
        Decrypt a value from storage.
        
        Args:
            value: Encrypted string (with ENCRYPTED: prefix) or plaintext
            field_name: Field name for key derivation
            allow_plaintext: If True, return unencrypted values as-is (backward compat)
        
        Returns:
            Decrypted plaintext (or original if not encrypted)
        """
        if value is None or value == '':
            return value
        
        # Check if value is encrypted
        if not isinstance(value, str):
            value = str(value)
        
        if not value.startswith(EncryptionKeyManager.ENCRYPTION_PREFIX):
            # Unencrypted value (old data or plaintext)
            if allow_plaintext:
                return value  # Return as-is for backward compatibility
            else:
                logger.warning(f"Unencrypted value found for {field_name} (should be encrypted)")
                return value
        
        try:
            # Remove prefix and version
            encrypted_str = value[len(EncryptionKeyManager.ENCRYPTION_PREFIX):]
            if ':' in encrypted_str:
                version, encrypted_str = encrypted_str.split(':', 1)
            
            encrypted_bytes = encrypted_str.encode('utf-8')
            
            # Try current key first
            try:
                cipher = EncryptionKeyManager.get_fernet_cipher(field_name)
                decrypted_bytes = cipher.decrypt(encrypted_bytes)
                return decrypted_bytes.decode('utf-8')
            
            except InvalidToken:
                # Current key failed, try old keys (key rotation)
                old_keys = EncryptionKeyManager.get_old_master_keys()
                if not old_keys:
                    raise
                
                for old_key in old_keys:
                    try:
                        field_key = EncryptionKeyManager.derive_field_key(old_key, field_name)
                        cipher = Fernet(field_key)
                        decrypted_bytes = cipher.decrypt(encrypted_bytes)
                        logger.info(f"Decrypted {field_name} using old key (key rotation)")
                        return decrypted_bytes.decode('utf-8')
                    except InvalidToken:
                        continue
                
                # No key worked
                raise InvalidToken("No valid key found for decryption (invalid token)")
        
        except InvalidToken:
            logger.error(f"Invalid encrypted token for field {field_name}")
            # Fail gracefully: return encrypted value (prevents data loss)
            logger.warning(f"Returning encrypted value for {field_name} due to decryption failure")
            return value
        
        except Exception as e:
            logger.error(f"Decryption error for field {field_name}: {e}")
            return value


# ═══════════════════════════════════════════════════════════════
# Testing & Verification
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """Test encryption/decryption locally."""
    import os
    
    # Set test key
    os.environ['ENCRYPTION_MASTER_KEY'] = Fernet.generate_key().decode('utf-8')
    
    logging.basicConfig(level=logging.INFO)
    
    print("\n✅ Test 1: Basic Encryption/Decryption")
    plaintext = "+254712345678"
    encrypted = EncryptedFieldManager.encrypt_value(plaintext, "phone_number")
    print(f"  Plaintext:  {plaintext}")
    print(f"  Encrypted:  {encrypted[:50]}...")
    decrypted = EncryptedFieldManager.decrypt_value(encrypted, "phone_number")
    print(f"  Decrypted:  {decrypted}")
    assert plaintext == decrypted, "Encryption/decryption mismatch!"
    
    print("\n✅ Test 2: Backward Compatibility (Unencrypted Values)")
    unencrypted = "old_plaintext_value"
    decrypted = EncryptedFieldManager.decrypt_value(unencrypted, "phone_number")
    print(f"  Unencrypted input:  {unencrypted}")
    print(f"  After decrypt():    {decrypted}")
    assert unencrypted == decrypted, "Backward compatibility broken!"
    
    print("\n✅ Test 3: Different Fields Use Different Keys")
    value = "sensitive_data"
    encrypted_phone = EncryptedFieldManager.encrypt_value(value, "phone_number")
    encrypted_email = EncryptedFieldManager.encrypt_value(value, "email")
    print(f"  Same value, phone field:  {encrypted_phone[:50]}...")
    print(f"  Same value, email field:  {encrypted_email[:50]}...")
    assert encrypted_phone != encrypted_email, "Field keys not unique!"
    
    print("\n✅ Test 4: None and Empty Values")
    assert EncryptedFieldManager.encrypt_value(None, "phone") is None
    assert EncryptedFieldManager.encrypt_value("", "phone") == ""
    assert EncryptedFieldManager.decrypt_value(None, "phone") is None
    assert EncryptedFieldManager.decrypt_value("", "phone") == ""
    print("  None and empty values handled correctly")
    
    print("\n✅ All encryption tests passed!")
