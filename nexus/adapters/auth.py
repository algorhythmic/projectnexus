"""Kalshi API RSA-PSS SHA-256 authentication.

Kalshi requires three headers on every authenticated request:
  - KALSHI-ACCESS-KEY: the API key ID
  - KALSHI-ACCESS-TIMESTAMP: current time in milliseconds
  - KALSHI-ACCESS-SIGNATURE: base64(RSA-PSS-SHA256(timestamp + method + path))

The message to sign is the concatenation of the timestamp string, the
uppercase HTTP method, and the request path (e.g. "/trade-api/v2/markets").
"""

import base64
import time
from pathlib import Path
from typing import Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def load_private_key(key_source: Union[str, Path, bytes]) -> RSAPrivateKey:
    """Load an RSA private key from a PEM file path or raw bytes.

    Supports both PKCS#8 (BEGIN PRIVATE KEY) and PKCS#1
    (BEGIN RSA PRIVATE KEY) formats.
    """
    if isinstance(key_source, (str, Path)):
        pem_data = Path(key_source).read_bytes()
    else:
        pem_data = key_source

    key = serialization.load_pem_private_key(pem_data, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise TypeError("Key is not an RSA private key")
    return key


def sign_request(
    private_key: RSAPrivateKey,
    timestamp_ms: str,
    method: str,
    path: str,
) -> str:
    """Generate RSA-PSS SHA-256 signature for Kalshi API.

    Args:
        private_key: Loaded RSA private key.
        timestamp_ms: Current time in milliseconds as a string.
        method: HTTP method (GET, POST, etc.).
        path: Request path including any prefix (e.g. "/trade-api/v2/markets").

    Returns:
        Base64-encoded signature.
    """
    message = (timestamp_ms + method.upper() + path).encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def generate_auth_headers(
    api_key: str,
    private_key: RSAPrivateKey,
    method: str,
    path: str,
) -> dict[str, str]:
    """Generate the three Kalshi authentication headers.

    Returns:
        Dict with KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP,
        and KALSHI-ACCESS-SIGNATURE.
    """
    timestamp_ms = str(int(time.time() * 1000))
    signature = sign_request(private_key, timestamp_ms, method.upper(), path)
    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }
