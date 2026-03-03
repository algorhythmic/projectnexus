"""Shared pytest fixtures for Nexus tests."""

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from nexus.core.config import Settings
from nexus.store.sqlite import SQLiteStore


@pytest.fixture
def rsa_key_pair(tmp_path):
    """Generate an ephemeral RSA key pair for testing auth."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    pem_path = tmp_path / "test_key.pem"
    pem_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return private_key, pem_path


@pytest.fixture
async def tmp_store(tmp_path):
    """Provides an initialized SQLiteStore backed by a temp file."""
    db_path = str(tmp_path / "test.db")
    store = SQLiteStore(db_path)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def sample_settings(tmp_path):
    """Settings with test-appropriate defaults."""
    return Settings(
        sqlite_path=str(tmp_path / "test.db"),
        kalshi_use_demo=True,
        log_level="DEBUG",
        kalshi_api_key="test-key-123",
        kalshi_private_key_path="",
    )
