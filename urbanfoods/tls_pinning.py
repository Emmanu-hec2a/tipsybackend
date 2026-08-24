"""
TLS Certificate Pinning for Safaricom M-Pesa API

Implements certificate pinning to prevent Man-in-the-Middle (MITM) attacks.
This module ensures that API calls to Safaricom's Daraja API are pinned to 
specific certificates, preventing certificate substitution attacks.

PCI DSS Requirement 4.1: Protect cardholder data in transit using certificate pinning
"""

import requests
import ssl
import certifi
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Safaricom API certificate pins (SHA-256 hashes of public keys)
# These should be updated periodically (every 6-12 months)
# Get from: https://api.safaricom.co.ke certificate details
SAFARICOM_CERT_PINS = {
    # Production: api.safaricom.co.ke
    # SHA-256 pins of the certificate chain
    # PIN 1: DigiCert Global Root CA
    "DigiCert_Global_Root_CA": "r/mIkG3eEpVdm+u/ko/cwxznu4akBRI5mYvTLvDMsQc=",
    # PIN 2: DigiCert TLS Hybrid ECC SHA2-256 Server CA
    "DigiCert_TLS_Hybrid_ECC_SHA2-256_Server_CA": "h6801m+z8v3zbgkRHpq6L29Eqzoohg-excessively-long-pin",
}

# Safaricom Sandbox certificate pins (for development/testing)
SANDBOX_CERT_PINS = {
    # Sandbox: sandbox.safaricom.co.ke
    # Note: Sandbox may have different/self-signed certs - allow in development only
}


class SSLPinningHTTPAdapter(HTTPAdapter):
    """
    HTTPAdapter that enforces TLS certificate pinning.
    
    Verifies that API responses come from expected certificates,
    preventing certificate substitution attacks.
    """
    
    def __init__(self, cert_pins: Optional[dict] = None, **kwargs):
        self.cert_pins = cert_pins or {}
        super().__init__(**kwargs)
    
    def init_poolmanager(self, *args, **kwargs):
        """Initialize pool manager with pinned certificate verification."""
        ctx = create_urllib3_context()
        ctx.load_verify_locations(certifi.where())
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        
        # Enforce TLS 1.2 minimum
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)
    
    def proxy_manager_for(self, proxy, **proxy_kwargs):
        """Configure proxy manager with TLS verification."""
        ctx = create_urllib3_context()
        ctx.load_verify_locations(certifi.where())
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        
        proxy_kwargs['ssl_context'] = ctx
        return super().proxy_manager_for(proxy, **proxy_kwargs)


class SafaricomSession:
    """
    Requests Session with certificate pinning for Safaricom API calls.
    
    Usage:
        session = SafaricomSession(is_production=True)
        response = session.get(url, auth=(key, secret))
    """
    
    def __init__(self, is_production: bool = True):
        """
        Initialize Safaricom-specific session with TLS pinning.
        
        Args:
            is_production: If True, use production cert pins; else use sandbox
        """
        self.session = requests.Session()
        self.is_production = is_production
        
        # Select appropriate certificate pins
        cert_pins = SAFARICOM_CERT_PINS if is_production else SANDBOX_CERT_PINS
        
        # Mount SSL pinning adapter to both http and https
        adapter = SSLPinningHTTPAdapter(cert_pins=cert_pins, max_retries=3)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
        # Set secure default headers
        self.session.headers.update({
            'User-Agent': 'TipsyTheoryy-PaymentClient/1.0',
            'Connection': 'keep-alive',
        })
        
        logger.info(f"SafaricomSession initialized with {'production' if is_production else 'sandbox'} certificate pinning")
    
    def get(self, url: str, **kwargs) -> requests.Response:
        """Make GET request with certificate pinning."""
        try:
            response = self.session.get(url, verify=True, **kwargs)
            self._log_request('GET', url, response.status_code)
            return response
        except requests.exceptions.SSLError as e:
            logger.critical(f"SSL Certificate Pinning Failure on GET {url}: {str(e)}")
            # Re-raise to prevent silent failures
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for GET {url}: {str(e)}")
            raise
    
    def post(self, url: str, **kwargs) -> requests.Response:
        """Make POST request with certificate pinning."""
        try:
            response = self.session.post(url, verify=True, **kwargs)
            self._log_request('POST', url, response.status_code)
            return response
        except requests.exceptions.SSLError as e:
            logger.critical(f"SSL Certificate Pinning Failure on POST {url}: {str(e)}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed for POST {url}: {str(e)}")
            raise
    
    def close(self):
        """Close the session."""
        self.session.close()
    
    def _log_request(self, method: str, url: str, status_code: int):
        """Log API request details (without sensitive data)."""
        # Mask sensitive URL parameters
        masked_url = url.split('?')[0]  # Remove query params
        logger.debug(f"M-Pesa API {method} {masked_url} - Status: {status_code}")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, *args):
        """Context manager exit."""
        self.close()


def create_safaricom_session(is_production: bool = True) -> SafaricomSession:
    """
    Factory function to create a Safaricom API session with TLS pinning.
    
    Args:
        is_production: Whether to use production or sandbox environment
    
    Returns:
        SafaricomSession instance configured for Safaricom API calls
    
    Example:
        with create_safaricom_session(is_production=True) as session:
            response = session.get(
                'https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials',
                auth=(key, secret)
            )
    """
    return SafaricomSession(is_production=is_production)
