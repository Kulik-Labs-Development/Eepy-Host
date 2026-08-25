import enum
import os
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, Index, Integer, String, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

# Database URL from environment variable (no hardcoded fallback - fail fast if unset)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. See deploy/stack.env.example for configuration.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserRole(enum.StrEnum):
    USER = "user"
    SUPERUSER = "superuser"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    profile_picture = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    total_requests = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    # Usernames are unique CASE-INSENSITIVELY: the plain unique constraint on
    # username would let "User123" and "user123" coexist (identity clash).
    # The expression index enforces lower(username) uniqueness at the DB level
    # on fresh installs (create_all); existing installs get it from
    # sync_database_schema() in main.py. NOTE: must reference the Column
    # object — a bare string inside func.lower() would be a literal.
    __table_args__ = (
        Index("users_username_lower_key", func.lower(username), unique=True),
    )

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
