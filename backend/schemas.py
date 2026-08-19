from pydantic import BaseModel, EmailStr, Field

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    # SECURITY: no client-supplied role field. Accounts are ALWAYS created as
    # USER; promotion to SUPERUSER only happens via the SUPERUSER_USERNAME
    # bootstrap or an existing superuser's admin endpoints.
    password: str = Field(min_length=8, max_length=128)

class UserLogin(BaseModel):
    username: str
    password: str

class PasswordResetIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)
