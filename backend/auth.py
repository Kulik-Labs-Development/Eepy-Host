import os
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt  # PyJWT (migrated from python-jose: PYSEC-2024-232/-233, CVE-2024-29370; jose is unmaintained)

# JWT signing key — MUST be provided via the SECRET_KEY environment variable.
# No default is hardcoded so the service fails fast if misconfigured.
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a stored bcrypt hash.

    Bypasses passlib to avoid versioning and internal detection crashes.
    """
    try:
        # bcrypt only uses the first 72 bytes of a password; truncate explicitly
        # so long passwords behave identically at hash time and verify time.
        password_bytes = plain_password.encode("utf-8")[:72]
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Generate a bcrypt hash for a password (cost 12 by default)."""
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


# Pre-computed bcrypt hash of a random string. Checked against on every login
# for non-existent users so timing does not reveal which usernames exist.
# (Never a real user password — generated once and hard-coded here.)
DUMMY_HASH = "$2b$12$XQW5VqVz3fE1u9m7KpJ8ouZkQr0tYcB6nH2sD4gF5aE8wI1oM3jSu"  # noqa: S105
# Fallback: if the constant ever becomes malformed, derive a valid one at import.
try:
    bcrypt.checkpw(b"x", DUMMY_HASH.encode("utf-8"))
except ValueError:
    DUMMY_HASH = get_password_hash(secrets.token_hex(16))


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    # PyJWT signs with HMAC-SHA256; 'iat' is set automatically.
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT. Returns the payload, or None on ANY failure.

    The allowed algorithm list is pinned to HS256 — this is what prevents
    algorithm-confusion attacks (e.g. 'none' or RS/HS key-type swapping).
    PyJWT validates 'exp' (and 'nbf'/'iat') automatically.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
