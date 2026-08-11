from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt

# Use the same key as in docker-compose for dev consistency
SECRET_KEY = "[ROTATED_JWT_SECRET]" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 hours

def verify_password(plain_password: str, hashed_password: str):
    """
    Verifies a password against a hash using the bcrypt library directly.
    Bypasses passlib to avoid versioning and internal detection crashes.
    """
    try:
        # Ensure we are working with bytes and respecting the 72-byte limit
        password_bytes = plain_password.encode('utf-8')[:72]
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False

def get_password_hash(password: str):
    """
    Generates a bcrypt hash for a password.
    Bypasses passlib to avoid versioning and internal detection crashes.
    """
    # Ensure we are working with bytes and respecting the 72-byte limit
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    # Use utcnow for consistency with decode
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # jose handles 'exp' validation automatically unless specified otherwise, 
        # but we can explicitly check if we want a custom behavior.
        return payload
    except JWTError:
        return None
