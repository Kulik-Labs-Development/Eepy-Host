import base64
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import DUMMY_HASH, create_access_token, decode_access_token, get_password_hash, verify_password
from database import Base, SessionLocal, User, UserRole, engine, get_db
from models import (
    mcp_models,  # noqa: F401  - register MCP tables on the shared Base so create_all builds them
)
from models.mcp_models import MCPTemplate
from schemas import PasswordResetIn, UserCreate, UserLogin
from utils.logging_setup import MemoryLogHandler, logger

# Build a dedicated handler instance for the superuser log endpoint so the
# buffer is decoupled from any module-level shared handler.
memory_handler = MemoryLogHandler()
memory_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(memory_handler)

def sync_database_schema():
    try:
        with engine.connect() as conn:
            # users table columns (existing behavior).
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

            # mcp_templates columns for the modular MCP sidecar runtime.
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='mcp_templates'"))
            template_cols = {row[0] for row in result}
            template_required = {
                "runtime": "VARCHAR NOT NULL DEFAULT 'native'",
                "runtime_config": "JSON",
                "discovered_tools": "JSON",
                "tools_discovered_at": "TIMESTAMP WITH TIME ZONE",
            }
            for col, col_type in template_required.items():
                if col not in template_cols:
                    logger.info(f"Adding missing column {col} to mcp_templates table...")
                    conn.execute(text(f"ALTER TABLE mcp_templates ADD COLUMN {col} {col_type}"))

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

    The HappyFox MCP server code lives OUTSIDE this backend, in the
    integrations/happyfox-mcp git submodule (github.com/Glitch3dPenguin/
    happyfox-mcp). This row only registers *how to run* it:

    - docker backend (production/Portainer): CI builds the submodule into
      ghcr.io/kulik-labs-development/eepy-host-happyfox:latest on every
      push (the submodule pin in git = exactly that code).
    - subprocess backend (local dev): runs the submodule in-repo directly.

    Updating HappyFox = update the submodule ref + re-run admin discovery;
    never edit its code inside the backend.
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
        image_tag="ghcr.io/kulik-labs-development/eepy-host-happyfox",
        runtime="mcp-server",
        # Modular sidecar spec. Production (docker backend): CI builds the
        # integrations/happyfox-mcp submodule into the image below on every
        # push, so the sidecar always runs exactly the upstream commit this
        # repo pins. Local (subprocess backend): the command + cwd run the
        # submodule's server straight from the repo (stdio transport).
        runtime_config={
            "image": "ghcr.io/kulik-labs-development/eepy-host-happyfox:latest",
            "command": ["python", "happyfox_mcp.py"],
            "cwd": "integrations/happyfox-mcp",
            "env": {
                "MCP_TRANSPORT": "streamable-http",
                "PORT": "8000",
            },
            "endpoint": "/",
            "port": "8000",
            "env_mapping": {
                "HAPPYFOX_DOMAIN": "HAPPYFOX_DOMAIN",
                "HAPPYFOX_API_KEY": "HAPPYFOX_API_KEY",
                "HAPPYFOX_AUTH_CODE": "HAPPYFOX_AUTH_CODE",
            },
            # Read-only tool used by POST /config/{id}/test. The server returns
            # "Error ..." as tool text on auth failure, so the test inspects it.
            "test_tool": {"name": "list_tickets", "arguments": {"status": "_pending", "size": 1}},
            # Best-effort tool list for the OpenAPI spec until admin discovery
            # stores the authoritative tools/list (from the upstream repo).
            # Kept in sync with integrations/happyfox-mcp (16 tools at submodule
            # commit 91906dc, verified through the subprocess sidecar path).
            "tool_names": [
                "list_tickets", "get_ticket_details", "get_ticket_messages",
                "get_ticket_attachments", "download_attachment", "list_statuses",
                "list_categories", "list_staff", "list_priorities",
                "add_ticket_update", "create_ticket", "assign_ticket",
                "suggest_ticket_rename", "change_ticket_status",
                "change_ticket_priority", "change_ticket_category",
            ],
        },
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
            existing.image_tag = happyfox.image_tag
            # Roll forward to the modular sidecar runtime on every boot so the
            # seeded reference template always matches this code's expectations.
            existing.runtime = happyfox.runtime
            existing.runtime_config = happyfox.runtime_config
            db.commit()
            logger.info("HappyFox MCP template exists; ensured enabled (mcp-server runtime).")
        else:
            db.add(happyfox)
            db.commit()
            logger.info("Seeded HappyFox MCP template (approved, mcp-server runtime).")
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
from api import mcp_bridge  # noqa: E402
from api.mcp_endpoints import router as mcp_router  # noqa: E402

app = FastAPI(title="Eepy Host API")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifecycle: start the MCP sidecar idle-reaper on boot,
    tear down any live sidecars on shutdown."""
    mcp_bridge.ensure_reaper_started()
    try:
        yield
    finally:
        mcp_bridge.shutdown_all_instances()


app.router.lifespan_context = _lifespan

# --- RATE LIMITING ---
# Brute-force protection for credential endpoints. In-memory limiter (single
# backend process); keyed by client IP.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount the MCP integration router (Phase 5: HappyFox template #1).
app.include_router(mcp_router)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.url.path}: {exc.errors() if callable(getattr(exc, 'errors', None)) else exc.errors}")
    errors = exc.errors() if callable(getattr(exc, "errors", None)) else exc.errors
    first_error = errors[0] if errors else {"msg": "Invalid request data"}
    return JSONResponse(
        status_code=422,
        content={"detail": first_error.get("msg", "Validation failed")},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dev.eepy.host",
        "https://www.eepy.host",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
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
@limiter.limit("5/hour")
def signup(
    request: Request,
    user_in: UserCreate,
    db: Session = Depends(get_db),
):
    try:
        logger.info(f"Signup request received for user: {user_in.username}")
        existing_user = db.query(User).filter((User.username == user_in.username) | (User.email == user_in.email)).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username or email already registered")

        # SECURITY: role is NOT accepted from the client. Every account starts
        # as USER; superuser status comes only from the SUPERUSER_USERNAME
        # bootstrap or an admin role change (see /superuser/* endpoints).
        new_user = User(
            username=user_in.username,
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password[:72]),
            role=UserRole.USER,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info(f"New user created: {user_in.username}")
        return {"message": "Account created successfully", "user_id": new_user.id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during signup")
        raise HTTPException(status_code=500, detail="Internal server error") from None

@app.post("/auth/login")
@limiter.limit("10/minute")
def login(
    request: Request,
    credentials: UserLogin,
    db: Session = Depends(get_db),
):
    try:
        logger.info(f"Login request received for user: {credentials.username}")
        user = db.query(User).filter(User.username == credentials.username).first()
        # Always run bcrypt on a dummy hash when the user does not exist so
        # response timing does not reveal which usernames are registered.
        if not user:
            verify_password(credentials.password[:72], DUMMY_HASH)
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(credentials.password[:72], user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token({"sub": user.username, "role": user.role})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {"username": user.username, "role": user.role, "email": user.email, "full_name": user.full_name}
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during login")
        raise HTTPException(status_code=500, detail="Internal server error") from None

@app.get("/user/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    return {"full_name": current_user.full_name, "email": current_user.email, "profile_picture": current_user.profile_picture, "username": current_user.username}

@app.patch("/user/profile")
async def update_profile(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        data = await request.json()
        if "full_name" in data:
            if not isinstance(data["full_name"], str):
                raise HTTPException(status_code=400, detail="full_name must be a string")
            current_user.full_name = data["full_name"][:255]
            db.commit()
            db.refresh(current_user)
        return {"message": "Profile updated successfully", "full_name": current_user.full_name}
    except HTTPException:
        raise
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
        logger.exception(f"Unexpected error uploading avatar for {current_user.username}")
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
        new_role = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role specified") from None
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = new_role
    db.commit()
    logger.info(f"Superuser {superuser.username} updated user {user.username} role to {role}")
    return {"message": f"User {user.username} role updated to {role}"}

@app.post("/superuser/users/{user_id}/password")
def reset_user_password(user_id: int, body: PasswordResetIn, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    # SECURITY: password arrives in the JSON body, never the URL query string
    # (query strings end up in access logs, proxy logs, and browser history).
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = get_password_hash(body.password[:72])
    db.commit()
    logger.info(f"Superuser {superuser.username} reset password for user {user.username}")
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
            if not isinstance(data["full_name"], str):
                raise HTTPException(status_code=400, detail="full_name must be a string")
            user.full_name = data["full_name"][:255]
        if "email" in data:
            if not isinstance(data["email"], str) or "@" not in data["email"]:
                raise HTTPException(status_code=400, detail="Invalid email")
            user.email = data["email"]
        if "role" in data:
            try:
                user.role = UserRole(data["role"])
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid role specified") from None
        db.commit()
        db.refresh(user)
        return {"message": "User updated successfully", "user": user.username}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin update error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user") from e


# ---------------------------------------------------------------------------
# Superuser: MCP template runtime management (modular sidecar integrations)
# ---------------------------------------------------------------------------
class TemplateRuntimeIn(BaseModel):
    runtime: str | None = None  # "native" | "mcp-server"
    runtime_config: dict | None = None  # sidecar spec (image/command/env_mapping/...)
    approved_by_admin: bool | None = None
    enabled_global: bool | None = None


@app.patch("/superuser/mcp/templates/{template_id}/runtime")
async def update_mcp_template_runtime(
    template_id: str,
    body: TemplateRuntimeIn,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db),
):
    """Register/update the sidecar spec for an integration.

    `runtime_config` never contains secrets -- only template-level static
    config (image, command, env mapping, endpoint, test_tool). User secrets
    come from each user's encrypted config and are injected per sidecar.
    """
    template = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    if body.runtime is not None:
        if body.runtime not in ("native", "mcp-server"):
            raise HTTPException(status_code=400, detail="runtime must be 'native' or 'mcp-server'.")
        template.runtime = body.runtime
    if body.runtime_config is not None:
        template.runtime_config = body.runtime_config
    if body.approved_by_admin is not None:
        template.approved_by_admin = body.approved_by_admin
    if body.enabled_global is not None:
        template.enabled_global = body.enabled_global
    db.commit()
    logger.info(f"Superuser {superuser.username} updated runtime for template '{template_id}'")
    return {"status": "updated", "template_id": template_id, "runtime": template.runtime}


@app.post("/superuser/mcp/templates/{template_id}/discover")
async def discover_mcp_tools(
    template_id: str,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db),
):
    """Run tools/list against the template's sidecar using the superuser's OWN
    stored credentials for that template, and store the result on the row.

    This is what makes a new upstream-repo integration appear in the unified
    OpenAPI spec (and dashboard) with zero backend code: the upstream repo's
    author owns the tool definitions; we just capture them. The sidecar is
    ephemeral and is torn down immediately after discovery.
    """
    from api.mcp_bridge import discover_tools_for_template
    from utils.crypto import decrypt_credentials

    template = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    if template.runtime != "mcp-server":
        raise HTTPException(status_code=400, detail="Template does not use the mcp-server runtime.")

    cfg_row = (
        db.query(mcp_models.UserMCPConfig)
        .filter(mcp_models.UserMCPConfig.owner_id == superuser.id,
                mcp_models.UserMCPConfig.template_name == template_id,
                mcp_models.UserMCPConfig.is_active == True)  # noqa: E712
        .first()
    )
    if not cfg_row:
        raise HTTPException(
            status_code=400,
            detail=f"You must first connect to '{template_id}' with your own account "
                   f"(dashboard > Connect) before discovering its tools.",
        )

    credentials = decrypt_credentials(cfg_row.credentials_json)  # memory-only

    tools = await discover_tools_for_template(db, superuser, template, credentials)
    template.discovered_tools = tools
    template.tools_discovered_at = datetime.now(UTC)
    db.commit()
    logger.info(f"Superuser {superuser.username} discovered {len(tools)} tools for '{template_id}'")
    return {"template_id": template_id, "tool_count": len(tools), "tools": [t["name"] for t in tools]}
