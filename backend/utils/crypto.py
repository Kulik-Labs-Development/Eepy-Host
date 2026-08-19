"""Fernet encryption/decryption for MCP credentials.

Security rules:
- Encrypt at write, store ciphertext (Base64 string) in PostgreSQL.
- Decrypt ONLY temporarily inside request handlers, in memory.
- Never log or persist plaintext credentials.

Key resolution (in order):
1. ``MCP_ENCRYPTION_KEY`` env var (a 44-char url-safe Base64 Fernet key), if valid.
2. Derived deterministically from ``SECRET_KEY`` (SHA-256 -> urlsafe b64) so the
   server always has a working key even if MCP_ENCRYPTION_KEY is absent.

Only when NEITHER is available do we raise, and the caller surfaces a clear error.
"""

import base64
import hashlib
import json
import logging
import os
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet

logger = logging.getLogger("eepy-backend")


def _derive_key_from_secret() -> bytes:
    """Deterministically derive a valid 32-byte (url-safe Base64) Fernet key from
    the app's SECRET_KEY. Used as a fallback so encryption always works."""
    secret = os.getenv("SECRET_KEY", "")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Build the singleton Fernet instance, resolving the key as documented above."""
    explicit = os.getenv("MCP_ENCRYPTION_KEY", "").strip()
    if explicit:
        try:
            return Fernet(explicit.encode("utf-8"))
        except Exception:
            logger.warning(
                "MCP_ENCRYPTION_KEY is not a valid Fernet key; falling back to a key "
                "derived from SECRET_KEY. Set a valid key for production."
            )

    if os.getenv("SECRET_KEY", "").strip():
        return Fernet(_derive_key_from_secret())

    raise ValueError(
        "No usable encryption key available. Set MCP_ENCRYPTION_KEY (a valid Fernet key) "
        "or SECRET_KEY in the environment."
    )


def encrypt_credentials(credentials: dict[str, Any]) -> str:
    """Encrypt a credentials dict into a Fernet token (Base64 string) for storage."""
    fernet = _get_fernet()
    plaintext = json.dumps(credentials).encode("utf-8")
    return fernet.encrypt(plaintext).decode("utf-8")


def decrypt_credentials(encrypted_token: str) -> dict[str, Any]:
    """Decrypt a stored Fernet token back into a dict (in memory only)."""
    fernet = _get_fernet()
    plaintext = fernet.decrypt(encrypted_token.encode("utf-8"))
    return json.loads(plaintext.decode("utf-8"))
