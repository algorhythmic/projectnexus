"""Tests for Kalshi RSA-PSS authentication."""

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, utils

from nexus.adapters.auth import (
    generate_auth_headers,
    load_private_key,
    sign_request,
)


class TestLoadPrivateKey:
    def test_load_from_file(self, rsa_key_pair):
        """Loading a valid PEM file returns an RSA key."""
        _, pem_path = rsa_key_pair
        key = load_private_key(pem_path)
        assert key is not None
        assert key.key_size == 2048

    def test_load_from_bytes(self, rsa_key_pair):
        """Loading from raw PEM bytes also works."""
        _, pem_path = rsa_key_pair
        pem_bytes = pem_path.read_bytes()
        key = load_private_key(pem_bytes)
        assert key.key_size == 2048

    def test_load_invalid_path_raises(self, tmp_path):
        """A nonexistent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_private_key(tmp_path / "nonexistent.pem")

    def test_load_invalid_content_raises(self, tmp_path):
        """Invalid PEM content raises ValueError."""
        bad_file = tmp_path / "bad.pem"
        bad_file.write_text("not a real key")
        with pytest.raises(ValueError):
            load_private_key(bad_file)


class TestSignRequest:
    def test_signature_is_base64(self, rsa_key_pair):
        """sign_request returns a valid base64 string."""
        private_key, _ = rsa_key_pair
        sig = sign_request(private_key, "1234567890", "GET", "/v2/markets")
        # Should not raise
        raw = base64.b64decode(sig)
        assert len(raw) > 0

    def test_signature_is_verifiable(self, rsa_key_pair):
        """The signature can be verified with the corresponding public key."""
        private_key, _ = rsa_key_pair
        public_key = private_key.public_key()

        ts = "1709000000000"
        method = "GET"
        path = "/trade-api/v2/markets"
        sig_b64 = sign_request(private_key, ts, method, path)

        message = (ts + method.upper() + path).encode("utf-8")
        signature = base64.b64decode(sig_b64)

        # This will raise InvalidSignature if verification fails
        public_key.verify(
            signature,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256().digest_size,
            ),
            hashes.SHA256(),
        )

    def test_different_messages_produce_different_signatures(self, rsa_key_pair):
        """Different inputs yield different signatures."""
        private_key, _ = rsa_key_pair
        sig1 = sign_request(private_key, "1000", "GET", "/a")
        sig2 = sign_request(private_key, "2000", "POST", "/b")
        assert sig1 != sig2


class TestGenerateAuthHeaders:
    def test_returns_all_required_headers(self, rsa_key_pair):
        """Headers dict contains the three required Kalshi keys."""
        private_key, _ = rsa_key_pair
        headers = generate_auth_headers(
            api_key="my-key",
            private_key=private_key,
            method="GET",
            path="/trade-api/v2/markets",
        )
        assert "KALSHI-ACCESS-KEY" in headers
        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers
        assert headers["KALSHI-ACCESS-KEY"] == "my-key"

    def test_timestamp_is_numeric_string(self, rsa_key_pair):
        """The timestamp header is a numeric string (ms since epoch)."""
        private_key, _ = rsa_key_pair
        headers = generate_auth_headers(
            api_key="k",
            private_key=private_key,
            method="GET",
            path="/v2/markets",
        )
        ts = headers["KALSHI-ACCESS-TIMESTAMP"]
        assert ts.isdigit()
        assert len(ts) >= 13  # millisecond precision
