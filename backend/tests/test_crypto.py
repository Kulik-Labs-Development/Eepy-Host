import base64
import hashlib

import pytest

from utils import crypto


@pytest.fixture(autouse=True)
def _fresh_fernet_cache(monkeypatch):
    crypto._get_fernet.cache_clear()
    yield
    crypto._get_fernet.cache_clear()


def test_round_trip(monkeypatch):
    monkeypatch.setenv("MCP_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    creds = {"HAPPYFOX_DOMAIN": "acme.happyfox.com", "HAPPYFOX_API_KEY": "k", "HAPPYFOX_AUTH_CODE": "c"}
    blob = crypto.encrypt_credentials(creds)
    assert "HAPPYFOX_API_KEY" not in blob, "ciphertext must not embed plaintext"
    assert crypto.decrypt_credentials(blob) == creds


def test_ciphertext_is_urlsafe_base64(monkeypatch):
    monkeypatch.setenv("MCP_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    blob = crypto.encrypt_credentials({"secret_value": "hunter2"})
    base64.urlsafe_b64decode(blob.encode())  # raises if not url-safe base64
    assert "hunter2" not in blob


def test_fallback_key_derivation(monkeypatch):
    monkeypatch.delenv("MCP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "my-secret")
    expected = base64.urlsafe_b64encode(hashlib.sha256(b"my-secret").digest())
    assert crypto._derive_key_from_secret() == expected


def test_no_key_raises(monkeypatch):
    monkeypatch.delenv("MCP_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="No usable encryption key"):
        crypto.encrypt_credentials({"a": "b"})
