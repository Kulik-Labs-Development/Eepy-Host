import base64
import datetime
import logging
import os
from collections import deque

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import create_access_token, decode_access_token, get_password_hash, verify_password
from database import Base, SessionLocal, User, UserRole, engine, get_db
from models import (
    mcp_models,  # noqa: F401  - register MCP tables on the shared Base so create_all builds them
)
from schemas import UserCreate, UserLogin


# --- LOGGING SYSTEM ---
class MemoryLogHandler(logging.Handler):
    def __init__(self, capacity=200):
        super().__init__()
        self.buffer = deque(maxlen=capacity)

    def emit(self, record):
        log_entry = self.format(record)
        timestamp = datetime.datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        self.buffer.append({
            "timestamp": timestamp,
            "level": record.levelname,
            "message": log_entry
        })

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eepy-backend")
memory_handler = MemoryLogHandler()
memory_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(memory_handler)

def sync_database_schema():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))
            existing_columns = {row[0] for row in result}

            required_columns = {
                "full_name": "VARCHAR",
                "profile_picture": "TEXT",
                "total_requests": "INTEGER DEFAULT 0 NOT NULL"
            }

            for col, col_type in required_columns.items():
                if col not in existing_columns:
                    logger.info(f"Adding missing column {col} to users table...")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))

            conn.commit()
            logger.info("Database columns synchronized.")
    except Exception as e:
        logger.error(f"Schema column synchronization failed: {e}")

    try:
        # Optional first-boot bootstrap: promote the account named in the
        # SUPERUSER_USERNAME env var to superuser (useful for the initial admin).
        bootstrap_username = os.getenv("SUPERUSER_USERNAME", "")
        if bootstrap_username:
            db = SessionLocal()
            user = db.query(User).filter(User.username == bootstrap_username).first()
            if user:
                if user.role != UserRole.SUPERUSER:
                    logger.info(f"Promoting {bootstrap_username} to superuser...")
                    user.role = UserRole.SUPERUSER
                    db.commit()
                    logger.info(f"User {bootstrap_username} promoted to superuser successfully.")
                else:
                    logger.info(f"{bootstrap_username} is already a superuser.")
            else:
                logger.warning(f"Promotion skipped: User '{bootstrap_username}' not found in database.")
            db.close()
    except Exception as e:
        logger.error(f"Superuser promotion failed: {e}")

def seed_mcp_templates():
    """Seed the admin-approved HappyFox template (template #1) into the library.

    Idempotent: only inserts if the slug does not already exist.
    """
    from models.mcp_models import MCPTemplate

    happyfox = MCPTemplate(
        id="happyfox",
        name="HappyFox Help Desk",
        description=(
            "Manage, read, and respond to support tickets in your HappyFox Help Desk. "
            "Agents can triage queues, read threads, post replies and private notes, "
            "change ticket status, and download attachments. All traffic is routed "
            "through the Eepy unified proxy with credentials encrypted at rest."
        ),
        config_schema={
            "category": "Support / Ticketing",
            "type": "object",
            "properties": {
                "HAPPYFOX_DOMAIN": {
                    "type": "string",
                    "label": "HappyFox Domain",
                    "placeholder": "yourcompany.happyfox.com",
                    "help": "The domain of your HappyFox instance.",
                    "required": True,
                },
                "HAPPYFOX_API_KEY": {
                    "type": "password",
                    "label": "API Key",
                    "help": "From HappyFox dashboard: Settings > Integrations > API Key.",
                    "required": True,
                },
                "HAPPYFOX_AUTH_CODE": {
                    "type": "password",
                    "label": "Auth Code",
                    "help": "Second API credential from the same panel.",
                    "required": True,
                },
            },
            "required": ["HAPPYFOX_DOMAIN", "HAPPYFOX_API_KEY", "HAPPYFOX_AUTH_CODE"],
        },
        image_tag="ghcr.io/glitch3dpenguin/happyfox-mcp",
        approved_by_admin=True,
        enabled_global=True,
    )

    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == "happyfox").first()
        if existing:
            existing.approved_by_admin = True
            existing.enabled_global = True
            existing.description = happyfox.description
            existing.config_schema = happyfox.config_schema
            db.commit()
            logger.info("HappyFox MCP template exists; ensured enabled.")
        else:
            db.add(happyfox)
            db.commit()
            logger.info("Seeded HappyFox MCP template (approved).")
    finally:
        db.close()

try:
    Base.metadata.create_all(bind=engine)
    sync_database_schema()
    seed_mcp_templates()
    logger.info("Database initialized and synchronized.")
except Exception as e:
    logger.error(f"Critical error initializing database: {e}")

# MCP endpoints (Phase 5: HappyFox template #1). Absolute import (never relative):
# Uvicorn runs this module top-level.
from api.mcp_endpoints import router as mcp_router  # noqa: E402

app = FastAPI(title="Eepy Host API")

# Mount the MCP integration router (Phase 5: HappyFox template #1).
app.include_router(mcp_router)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
    first_error = exc.errors[0] if exc.errors else {"msg": "Invalid request data"}
    return JSONResponse(
        status_code=422,
        content={"detail": first_error.get("msg", "Validation failed")},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dev.eepy.host", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")

    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def get_superuser(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.SUPERUSER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operation restricted to superusers only")
    return current_user

@app.get("/")
async def root():
    return {"status": "online", "message": "Welcome to Eepy Host API. Stay cozy."}

@app.get("/health")
async def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

@app.post("/auth/signup")
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    try:
        logger.info(f"Signup request received for user: {user_in.username}")
        existing_user = db.query(User).filter((User.username == user_in.username) | (User.email == user_in.email)).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username or email already registered")

        try:
            role = UserRole(user_in.role)
        except ValueError:
            logger.warning(f"Invalid role provided: {user_in.role}. Defaulting to USER.")
            role = UserRole.USER

        safe_password = user_in.password[:72]
        new_user = User(username=user_in.username, email=user_in.email, hashed_password=get_password_hash(safe_password), role=role)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info(f"New user created: {user_in.username}")
        return {"message": "Account created successfully", "user_id": new_user.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during signup")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") from e

@app.post("/auth/login")
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    try:
        logger.info(f"Login request received for user: {credentials.username}")
        user = db.query(User).filter(User.username == credentials.username).first()
        if not user or not verify_password(credentials.password[:72], user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token({"sub": user.username, "role": user.role})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {"username": user.username, "role": user.role, "email": user.email, "full_name": user.full_name}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during login")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") from e

@app.get("/user/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    return {"full_name": current_user.full_name, "email": current_user.email, "profile_picture": current_user.profile_picture, "username": current_user.username}

@app.patch("/user/profile")
async def update_profile(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        data = await request.json()
        if "full_name" in data:
            current_user.full_name = data["full_name"]
            db.commit()
            db.refresh(current_user)
        return {"message": "Profile updated successfully", "full_name": current_user.full_name}
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile") from e

@app.post("/user/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"Avatar upload started for user: {current_user.username}")
        if not file.content_type.startswith("image/"):
            logger.warning(f"Invalid file type attempted by {current_user.username}: {file.content_type}")
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload an image.")
        contents = await file.read()
        base64_encoded = base64.b64encode(contents).decode('utf-8')
        logger.info(f"Encoded image for {current_user.username} to Base64 string of length {len(base64_encoded)} bytes")
        data_uri = f"data:{file.content_type};base64,{base64_encoded}"
        current_user.profile_picture = data_uri
        db.commit()
        db.refresh(current_user)
        logger.info(f"Avatar successfully persisted to database for {current_user.username}.")
        return {"message": "Avatar uploaded successfully", "profile_picture": data_uri}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error uploading avatar for {current_user.username}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload avatar") from e

@app.get("/superuser/users", response_model=list[dict])
def list_all_users(superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "email": u.email, "full_name": u.full_name, "role": u.role, "total_requests": u.total_requests, "created_at": u.created_at} for u in users]

@app.get("/superuser/logs")
def get_system_logs(superuser: User = Depends(get_superuser)):
    return list(memory_handler.buffer)

@app.patch("/superuser/users/{user_id}/role")
def update_user_role(user_id: int, role: str, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        new_role = UserRole(role)
        user.role = new_role
        db.commit()
        logger.info(f"Superuser {superuser.username} updated user {user.username} role to {role}")
        return {"message": f"User {user.username} role updated to {role}"}
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid role specified") from err
    except Exception as e:
        logger.error(f"Error updating user role: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user role") from e

@app.post("/superuser/users/{user_id}/password")
def reset_user_password(user_id: int, password: str, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = get_password_hash(password[:72])
    db.commit()
    return {"message": f"Password for {user.username} has been reset successfully"}

@app.delete("/superuser/users/{user_id}")
def delete_user_by_admin(user_id: int, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if target_user.id == superuser.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own superuser account")
    db.delete(target_user)
    db.commit()
    return {"message": f"User {target_user.username} has been removed from the system"}

@app.patch("/superuser/users/{user_id}/update")
async def update_user_details(user_id: int, request: Request, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    try:
        data = await request.json()
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if "full_name" in data:
            user.full_name = data["full_name"]
        if "email" in data:
            user.email = data["email"]
        if "role" in data:
            try:
                user.role = UserRole(data["role"])
            except ValueError as err:
                raise HTTPException(status_code=400, detail="Invalid role specified") from err
        db.commit()
        db.refresh(user)
        return {"message": "User updated successfully", "user": user.username}
    except Exception as e:
        logger.error(f"Admin update error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user") from e
