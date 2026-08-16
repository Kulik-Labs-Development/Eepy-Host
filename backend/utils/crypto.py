"""Fernet encryption/decryption for MCP credentials.

Security rules:
- Encrypt at write, store ciphertext (Base64 string) in PostgreSQL.
- Decrypt ONLY temporarily inside request handlers, in memory.
- Never log or persist plaintext credentials.
"""

import json
import os
from functools import lru_cache
from typing import Any, Dict

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Lazily build the Fernet instance so the backend can start before env is
    validated (e.g. during import checks / tests without a key)."""
    key = os.getenv("MCP_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError("MCP_ENCRYPTION_KEY is not set. Provide a 44-char Base64 Fernet key in the environment.")
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise ValueError("MCP_ENCRYPTION_KEY is not a valid Fernet key (expected 44-char Base64).") from exc


def encrypt_credentials(credentials: Dict[str, Any]) -> str:
    """Encrypt a credentials dict into a Fernet token (Base64 string) for storage."""
    fernet = _get_fernet()
    plaintext = json.dumps(credentials).encode("utf-8")
    return fernet.encrypt(plaintext).decode("utf-8")


def decrypt_credentials(encrypted_token: str) -> Dict[str, Any]:
    """Decrypt a stored Fernet token back into a dict (in memory only)."""
    fernet = _get_fernet()
    plaintext = fernet.decrypt(encrypted_token.encode("utf-8"))
    return json.loads(plaintext.decode("utf-8"))
