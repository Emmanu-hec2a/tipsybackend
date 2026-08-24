"""
PII Masking Logging Filters for Payment Processing

This module provides utilities to mask sensitive personally identifiable information
(PII) in application logs while preserving enough information for debugging.

PCI DSS Requirement 3.4: All cardholder data and sensitive authentication data
must be masked when displayed (show at most first 6 or last 4 digits).

Usage:
    import logging
    from urbanfoods.logging_filters import PIIMaskingFilter
    
    logger = logging.getLogger('payment_processing')
    logger.addFilter(PIIMaskingFilter())
    
    # Logs automatically masked:
    logger.info(f"Payment: phone={phone}, email={email}, amount={amount}")
    # Output: Payment: phone=+25471234***, email=jo***@example.com, amount=50***

Author: TipsyTheoryy Security
Date: 2026-08-24
"""

import logging
import re
from typing import Pattern


class PIIMaskingFilter(logging.Filter):
    """
    Logging filter that masks PII (Personally Identifiable Information) in log records.
    
    Masks:
    - Phone numbers: +254712345678 → +25471234***
    - Email addresses: john@example.com → jo***@example.com
    - Amounts: 50000 → 50***
    - User IDs: 12345 → 1****
    - Credit cards: 4111111111111111 → 411111****1111
    
    This filter automatically processes all log records and applies masking to:
    - Log message
    - Log arguments (if any)
    - Exception information
    """
    
    # Regex patterns for different PII types
    # Phone numbers: +254712345678, 0712345678, 254712345678
    PHONE_PATTERN = re.compile(
        r'(?:\+254|254|0)(?:7|1)\d{8}',
        re.IGNORECASE
    )
    
    # Email addresses: john@example.com
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        re.IGNORECASE
    )
    
    # Credit card numbers: 4111111111111111
    CREDIT_CARD_PATTERN = re.compile(
        r'\b(?:\d[ -]*?){13,19}\b',
        re.IGNORECASE
    )
    
    # Customer IDs: id=12345, customer_id=42
    CUSTOMER_ID_PATTERN = re.compile(
        r'(?:customer_id|user_id|client_id)\s*=\s*(\d+)',
        re.IGNORECASE
    )
    
    # Amount values: amount=50000, amount_cents=50000
    AMOUNT_PATTERN = re.compile(
        r'(?:amount|amount_cents|price|cost|total)\s*[=:]\s*(\d+)',
        re.IGNORECASE
    )
    
    # Passport/ID numbers: PP12345678, ID12345
    DOCUMENT_ID_PATTERN = re.compile(
        r'\b(?:PP|ID|NAT_ID)\s*[\d-]+\b',
        re.IGNORECASE
    )

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter a log record and mask all PII.
        
        Args:
            record: LogRecord to process
            
        Returns:
            True (always allow record to be logged)
        """
        # Mask the log message
        if record.msg:
            record.msg = self._mask_pii(str(record.msg))
        
        # Mask log arguments if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._mask_pii(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._mask_pii(str(arg)) for arg in record.args)
        
        # Mask exception information if present
        if record.exc_info and len(record.exc_info) > 1:
            try:
                import traceback
                exc_text = ''.join(traceback.format_exception(*record.exc_info))
                exc_text = self._mask_pii(exc_text)
                # Store masked version for formatting
                record.exc_text = exc_text
            except Exception:
                pass  # If masking fails, use original
        
        return True

    @classmethod
    def _mask_pii(cls, text: str) -> str:
        """
        Mask all PII patterns in the given text.
        
        Args:
            text: Text containing potential PII
            
        Returns:
            Text with PII masked
        """
        if not isinstance(text, str):
            return str(text)
        
        # Mask phone numbers
        text = cls.PHONE_PATTERN.sub(cls._mask_phone, text)
        
        # Mask email addresses
        text = cls.EMAIL_PATTERN.sub(cls._mask_email, text)
        
        # Mask credit cards
        text = cls.CREDIT_CARD_PATTERN.sub(cls._mask_credit_card, text)
        
        # Mask customer IDs
        text = cls.CUSTOMER_ID_PATTERN.sub(cls._mask_customer_id, text)
        
        # Mask amounts
        text = cls.AMOUNT_PATTERN.sub(cls._mask_amount, text)
        
        # Mask document IDs
        text = cls.DOCUMENT_ID_PATTERN.sub(cls._mask_document_id, text)
        
        return text

    @staticmethod
    def _mask_phone(match) -> str:
        """Mask phone number: +254712345678 → +25471234***"""
        phone = match.group(0)
        # Show first 8 characters (+254712), mask the rest
        if len(phone) >= 8:
            return phone[:8] + '*' * (len(phone) - 8)
        return '*' * len(phone)

    @staticmethod
    def _mask_email(match) -> str:
        """Mask email: john@example.com → jo***@example.com"""
        email = match.group(0)
        # Show first 2 chars of local part, keep domain
        parts = email.split('@')
        local_part = parts[0]
        domain = '@'.join(parts[1:]) if len(parts) > 1 else ''
        
        if len(local_part) <= 2:
            masked_local = '*' * len(local_part)
        else:
            masked_local = local_part[:2] + '*' * (len(local_part) - 2)
        
        return f"{masked_local}@{domain}"

    @staticmethod
    def _mask_credit_card(match) -> str:
        """Mask credit card: 4111111111111111 → 411111****1111"""
        card = match.group(0).replace(' ', '').replace('-', '')
        # Show first 6 and last 4 digits
        if len(card) >= 10:
            return f"{card[:6]}****{card[-4:]}"
        return '*' * len(card)

    @staticmethod
    def _mask_customer_id(match) -> str:
        """Mask customer ID: customer_id=12345 → customer_id=1****"""
        full_match = match.group(0)
        customer_id = match.group(1)
        # Show first digit only
        masked_id = customer_id[0] + '*' * (len(customer_id) - 1)
        return full_match.replace(customer_id, masked_id)

    @staticmethod
    def _mask_amount(match) -> str:
        """Mask amount: amount=50000 → amount=50***"""
        full_match = match.group(0)
        amount = match.group(1)
        # Show first 2 digits
        masked_amount = amount[:2] + '*' * (len(amount) - 2) if len(amount) > 2 else '*' * len(amount)
        return full_match.replace(amount, masked_amount)

    @staticmethod
    def _mask_document_id(match) -> str:
        """Mask document ID: PP12345678 → PP****5678"""
        doc_id = match.group(0)
        # Show prefix and last 4 characters
        parts = re.split(r'[\d-]+', doc_id)
        prefix = parts[0] if parts else ''
        
        # Extract numbers/dashes
        numbers = re.findall(r'[\d-]+', doc_id)
        if numbers:
            num_part = numbers[-1]
            # Show last 4 characters
            if len(num_part.replace('-', '')) > 4:
                masked = '****' + num_part[-4:]
            else:
                masked = '*' * len(num_part)
            return f"{prefix}{masked}"
        
        return '*' * len(doc_id)


class StructuredPIIMasking:
    """
    Utility class for masking PII in structured data (dicts, lists).
    
    Useful for masking data before logging JSON or structured formats.
    """
    
    # Fields that should always be masked
    SENSITIVE_FIELDS = {
        'phone_number', 'phone', 'mobile', 'cell_phone',
        'email', 'email_address',
        'customer_id', 'user_id', 'client_id',
        'amount', 'amount_cents', 'price', 'cost', 'total',
        'credit_card', 'card_number', 'account_number',
        'password', 'pin', 'secret',
        'mpesa_receipt', 'receipt_number',
        'transaction_id', 'payment_id',
    }

    @classmethod
    def mask_dict(cls, data: dict, sensitive_fields: set = None) -> dict:
        """
        Mask PII in a dictionary.
        
        Args:
            data: Dictionary to mask
            sensitive_fields: Set of field names to mask (uses defaults if None)
            
        Returns:
            Dictionary with masked values
        """
        if not isinstance(data, dict):
            return data
        
        sensitive_fields = sensitive_fields or cls.SENSITIVE_FIELDS
        masked = {}
        
        for key, value in data.items():
            if key.lower() in {f.lower() for f in sensitive_fields}:
                masked[key] = PIIMaskingFilter._mask_pii(str(value))
            elif isinstance(value, dict):
                masked[key] = cls.mask_dict(value, sensitive_fields)
            elif isinstance(value, list):
                masked[key] = [cls.mask_dict(item, sensitive_fields) if isinstance(item, dict) else item for item in value]
            else:
                masked[key] = value
        
        return masked

    @classmethod
    def mask_json(cls, json_str: str, sensitive_fields: set = None) -> str:
        """
        Mask PII in a JSON string.
        
        Args:
            json_str: JSON string to mask
            sensitive_fields: Set of field names to mask
            
        Returns:
            JSON string with masked values
        """
        import json
        try:
            data = json.loads(json_str)
            masked_data = cls.mask_dict(data, sensitive_fields)
            return json.dumps(masked_data)
        except (json.JSONDecodeError, TypeError):
            # If not valid JSON, fall back to regex masking
            return PIIMaskingFilter._mask_pii(json_str)


def setup_pii_masking(logger_name: str = None) -> logging.Logger:
    """
    Convenience function to set up a logger with PII masking.
    
    Args:
        logger_name: Logger name (if None, uses root logger)
        
    Returns:
        Configured logger
    """
    logger = logging.getLogger(logger_name)
    logger.addFilter(PIIMaskingFilter())
    return logger


# Example usage
if __name__ == "__main__":
    # Test the masking filter
    import logging
    
    # Set up logger with masking
    logger = logging.getLogger('test')
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.addFilter(PIIMaskingFilter())
    logger.setLevel(logging.DEBUG)
    
    # Test various PII patterns
    logger.info("Customer phone: +254712345678")
    logger.info("Email: john.doe@example.com")
    logger.info("Payment: amount=50000, customer_id=42")
    logger.info("Card: 4111111111111111")
    logger.info("Receipt: NEF61H8J02, amount_cents=50000")
    
    # Test structured masking
    data = {
        "customer_id": 123,
        "phone_number": "+254712345678",
        "email": "john@example.com",
        "amount": 50000,
        "receipt": "NEF61H8J02"
    }
    masked_data = StructuredPIIMasking.mask_dict(data)
    print("\nStructured data masking:")
    print(f"Original: {data}")
    print(f"Masked:   {masked_data}")
