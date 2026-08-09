from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

# Use the same key as in docker-compose for dev consistency
SECRET_KEY = "[ROTATED_JWT_SECRET]" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    # Bcrypt has a maximum password length of 72 bytes.
    # To prevent errors with extremely long passwords, we truncate to 72.
    return pwd_context.verify(plain_password[:72], hashed_password)

def get_password_hash(password):
    # Bcrypt has a maximum password length of 72 bytes.
    # Truncating here ensures the hash is generated without error.
    return pwd_context.hash(password[:72])

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload if payload["exp"] >= datetime.utcnow().timestamp() else None
    except JWTError:
        return None
