"""MCP integration endpoints - Phase 5 (HappyFox template #1) + Open WebUI Tool Server export.

Security model:
- Credentials are encrypted with Fernet (MCP_ENCRYPTION_KEY) before being written to
  the `user_mcp_configs` table. Only ciphertext is ever persisted.
- Decryption happens ONLY inside a request handler, in memory, for the duration of the
  request. Plaintext credentials are never logged, never returned to the client, and
  never written to disk.
- Every endpoint requires a valid JWT (get_current_user). The backend is the source of
  truth for authorization; the frontend is never trusted for access control.
- Proxy + connection-test endpoints (and the native MCP stream endpoint,
  POST /api/mcp/mcp) additionally accept a user-scoped, revocable Tool API Key
  (Bearer `eekey_...`). ONE key per user unlocks EVERY integration they have
  connected — this is what makes Open WebUI a single Tool Server connection and
  MCP clients (opencode, Claude Desktop, ...) a single MCP server connection.
  The key is accepted ONLY on /api/mcp/proxy/*, /api/mcp/mcp, and
  /api/mcp/config/* — never on /user/*, /auth/*, billing, or superuser routes —
  and each tool call still requires the user to have an active connection to
  the requested template. Auth uses a SHA-256 hash; a Fernet-encrypted copy of
  the plaintext is also stored so the owner can re-view the key later in the
  UI, but ONLY after re-entering their account password (POST
  /api/mcp/api-keys/{id}/reveal). The list endpoint never returns plaintext.
"""

import asyncio
import hashlib
import re
import secrets
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import mcp_bridge  # absolute import: Uvicorn runs main.py top-level
from auth import decode_access_token, verify_password
from database import User, get_db
from models.mcp_models import MCPTemplate, MCPUserToolKey, UserMCPConfig
from utils.crypto import decrypt_credentials, decrypt_secret, encrypt_credentials, encrypt_secret
from utils.logging_setup import logger

router = APIRouter(prefix="/api/mcp", tags=["mcp-integrations"])

# The native MCP (streamable-HTTP) endpoint served by api/mcp_stream.py — the
# "AI Platform connector" for MCP clients (opencode, Claude Desktop, ...).
# The constant lives here because the eekey scope check below is the single
# source of truth for which paths a Tool API Key may be used on.
MCP_STREAM_PATH = "/api/mcp/mcp"


# ---------------------------------------------------------------------------
# Auth dependency (self-contained to avoid circular import with main.py)
# ---------------------------------------------------------------------------
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")
    token = auth_header.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConfigRegisterIn(BaseModel):
    template_id: str = Field("happyfox")
    display_name: str | None = None
    credentials_json: dict[str, str] = Field(..., description="Plaintext template credentials. Encrypted server-side.")


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    config_schema: dict[str, Any]
    image_tag: str | None = None
    repo_url: str | None = None
    approved_by_admin: bool
    enabled_global: bool


class ConfigOut(BaseModel):
    id: int
    template_name: str
    name_display: str | None
    is_active: bool
    created_at: datetime | None
    last_used_at: datetime | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _config_to_out(cfg: UserMCPConfig) -> ConfigOut:
    return ConfigOut(
        id=cfg.id,
        template_name=cfg.template_name,
        name_display=cfg.name_display,
        is_active=cfg.is_active,
        created_at=cfg.created_at,
        last_used_at=cfg.last_used_at,
    )


def _load_active_creds(db: Session, user: User, template_id: str) -> dict[str, str]:
    """Return decrypted credentials for the user's active config of a template, or 404.

    A stored blob that no longer decrypts (the server's MCP_ENCRYPTION_KEY /
    SECRET_KEY changed since the user saved it) is reported as an explicit,
    actionable 409 instead of an opaque 500, and logged so it is visible in
    the backend debug console.
    """
    cfg = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == user.id, UserMCPConfig.template_name == template_id)
        .first()
    )
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail=f"No active {template_id} connection for this user.")
    try:
        return decrypt_credentials(cfg.credentials_json)
    except InvalidToken as exc:
        # The stored blob is intact but the server's key no longer matches:
        # MCP_ENCRYPTION_KEY / SECRET_KEY changed since the user saved it.
        # (InvalidToken subclasses ValueError, so it must be caught first.)
        logger.warning(
            f"mcp: stored {template_id} credentials for user {user.username} (config id={cfg.id}) "
            f"could not be decrypted (InvalidToken) - the server encryption key "
            f"(MCP_ENCRYPTION_KEY/SECRET_KEY) likely changed since they were saved."
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Your saved {template_id} credentials can no longer be decrypted: the server's "
                f"encryption key changed since you saved them. Re-enter your credentials "
                f"(dashboard → MCP Servers → Connect) to fix this."
            ),
        ) from exc
    except ValueError as exc:
        # No usable key configured at all, or a corrupt stored blob (JSONDecodeError).
        logger.warning(
            f"mcp: stored {template_id} credentials for user {user.username} (config id={cfg.id}) "
            f"unreadable ({exc.__class__.__name__})."
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Your saved {template_id} credentials are unreadable. Re-enter your credentials "
                f"(dashboard → MCP Servers → Connect) to fix this."
            ),
        ) from exc


def _happyfox_base(domain: str) -> str:
    domain = (domain or "").strip()
    if not domain:
        raise HTTPException(status_code=400, detail="HAPPYFOX_DOMAIN is empty.")
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    return f"{domain.rstrip('/')}/api/1.1/json"


def _assert_public_upstream(url: str) -> None:
    """SSRF guard for the legacy native path: the BACKEND itself dials this
    URL (httpx) and returns the response, so the user-supplied host must be a
    public HTTPS endpoint. Blocks:
      - plain http (the Basic-auth credentials would travel in the clear),
      - loopback / private / link-local / multicast / reserved targets, which
        otherwise lets any connected user read internal services or the cloud
        metadata endpoint (http://169.254.169.254) from the backend container.
    IP literals are range-checked directly; hostnames are resolved and every
    resolved address must be public. Sync on purpose (DNS) — call it via
    asyncio.to_thread from async routes.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Upstream host must use https.")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="Upstream host is empty.")

    try:
        candidates = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="Upstream host does not resolve.") from None
        candidates = [ipaddress.ip_address(info[4][0]) for info in infos]
    for ip in candidates:
        # is_global (Python 3.11+) is False for loopback, RFC1918, CGNAT
        # (100.64/10), link-local (incl. the cloud metadata 169.254.169.254),
        # ULA, multicast, reserved and unspecified ranges — exactly the set of
        # hosts the backend must never dial on a user's behalf.
        if not ip.is_global:
            raise HTTPException(status_code=400, detail="Upstream host resolves to a non-public address.")


# ---------------------------------------------------------------------------
# User-scoped Tool API Key auth (Open WebUI integration)
# ---------------------------------------------------------------------------
# The proxy + connection-test routes accept EITHER a session JWT OR a user-scoped
# Tool API Key. The key identifies ONE user and unlocks every MCP integration
# they have connected — a single Bearer token for their entire Eepy tool surface.
# It is deliberately NOT a general Eepy credential: it only works on MCP routes,
# and per-call the proxy additionally requires the user to have an ACTIVE
# connection to the requested template (see _load_active_creds), so a key can
# never reach an integration the owner hasn't connected.
def _resolve_scoped_user(request: Request, db: Session) -> User:
    """Auth for proxy + connection-test routes: accepts EITHER a session JWT OR a
    user-scoped Tool API Key.

    The key is ONLY honored on the proxy routes (canonical
    /api/mcp/proxy/{template}/{tool} and the alias /api/mcp/{template}/{tool}),
    the native MCP stream endpoint (MCP_STREAM_PATH), and
    /api/mcp/config/{template}/test. On any other route an eekey_ token is
    treated as a (invalid) JWT and rejected - so the key can never touch
    /user/*, /auth/*, /superuser/*, billing, or even other MCP management
    endpoints (keys, template list, config register/delete). Per-call, the
    proxy additionally requires the user to have an active connection to the
    requested template.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")
    token = auth_header.split(" ", 1)[1].strip()

    # Proxy shapes: the canonical /api/mcp/proxy/{template}/{tool} and the
    # backwards-compatible alias /api/mcp/{template}/{tool} (mcp_proxy_alias),
    # the native MCP stream endpoint (api/mcp_stream.py — proxy-equivalent:
    # tools/call routes through the same bridge + credential checks), and the
    # connection test. The alias regex must exclude the first segments of
    # every static two-segment MCP route so a tool key can never be honored
    # on management endpoints (config register/list, template list).
    key_allowed = bool(
        re.match(r"^/api/mcp/proxy/[\w-]+/", request.url.path)
        or re.match(r"^/api/mcp/(?!config/|templates/|api-keys/)[\w-]+/[\w-]+$", request.url.path)
        or re.match(r"^/api/mcp/config/[\w-]+/test$", request.url.path)
        or request.url.path == MCP_STREAM_PATH
    )

    if token.startswith("eekey_"):
        if not key_allowed:
            # Key presented outside its allowed routes: reject explicitly.
            raise HTTPException(status_code=401, detail="Tool API keys are only valid on the MCP proxy and connection-test routes.")
        key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        key_row = (
            db.query(MCPUserToolKey)
            .filter(MCPUserToolKey.key_hash == key_hash, MCPUserToolKey.is_active == True)  # noqa: E712
            .first()
        )
        if not key_row:
            raise HTTPException(status_code=401, detail="Invalid or revoked tool API key.")
        user = db.query(User).filter(User.id == key_row.owner_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Key owner no longer exists.")
        key_row.last_used_at = datetime.now(UTC)
        db.commit()
        return user

    # Session JWT path (also the rejection path for keys used on non-allowed routes
    # is handled above; a real JWT must decode cleanly).
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_current_user_or_key(request: Request, db: Session = Depends(get_db)) -> User:
    """Proxy-only auth: accepts EITHER a JWT OR a scoped Tool API Key."""
    return _resolve_scoped_user(request, db)


def get_proxy_context(
    template_id: str,
    current_user: User = Depends(get_current_user_or_key),
    db: Session = Depends(get_db),
) -> tuple[MCPTemplate, dict[str, str], User]:
    """Sync dependency (runs in the threadpool, never blocks the event loop).

    Loads the approved+enabled template and the caller's decrypted credentials
    for the proxy / connection-test routes. Accepts JWT or Tool API Key via
    get_current_user_or_key (eekey route scoping is enforced there).
    """
    template = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
    if not template or not template.approved_by_admin or not template.enabled_global:
        raise HTTPException(status_code=404, detail=f"Unknown template '{template_id}'.")
    creds = _load_active_creds(db, current_user, template_id)
    return template, creds, current_user


def _generate_tool_key() -> str:
    return "eekey_" + secrets.token_urlsafe(32)


def _tool_key_out(row: MCPUserToolKey, show_plaintext: str | None = None) -> dict[str, Any]:
    out = {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "is_active": row.is_active,
        # False for legacy rows created before the re-view feature: the UI
        # hides the "View key" option for those (reveal would 410).
        "can_reveal": bool(row.key_encrypted),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }
    if show_plaintext is not None:
        # Returned at creation time (the list endpoint never sets this).
        out["key"] = show_plaintext
    return out


# ---------------------------------------------------------------------------
# User Tool API Keys (single connection for Open WebUI / any external tool server)
# ---------------------------------------------------------------------------
class ToolKeyCreateIn(BaseModel):
    name: str | None = Field("Open WebUI", description="Label shown in the Eepy UI.")


@router.post("/api-keys")
def create_tool_api_key(
    body: ToolKeyCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a user-scoped, revocable Tool API Key (ADDs a key — never
    replaces existing ones; the user may hold several active keys at once).

    ONE key per user covers EVERY integration they have connected — this is
    what makes Open WebUI a single Tool Server connection. The plaintext key
    is returned at creation; auth uses a SHA-256 hash and a Fernet-encrypted
    copy is stored so the owner can re-view the key later (password
    re-entry). The key works only on /api/mcp/proxy/* and /api/mcp/config/*,
    and each call still requires an active connection to the requested
    template.
    """
    has_active = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == current_user.id, UserMCPConfig.is_active == True)  # noqa: E712
        .first()
    )
    if not has_active:
        raise HTTPException(status_code=400, detail="Connect to at least one integration first, then generate a key.")

    plaintext = _generate_tool_key()
    row = MCPUserToolKey(
        owner_id=current_user.id,
        name=body.name or "Open WebUI",
        key_hash=hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
        key_prefix=plaintext[:8],
        key_encrypted=encrypt_secret(plaintext),
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(f"User {current_user.username} created user tool API key id={row.id}")
    return _tool_key_out(row, show_plaintext=plaintext)


@router.get("/api-keys")
def list_tool_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the user's tool API keys. Never returns plaintext — only a short prefix."""
    rows = (
        db.query(MCPUserToolKey)
        .filter(MCPUserToolKey.owner_id == current_user.id)
        .order_by(MCPUserToolKey.created_at.desc())
        .all()
    )
    return [_tool_key_out(r) for r in rows]


@router.delete("/api-keys/{key_id}")
def revoke_tool_api_key(
    key_id: int,
    hard: bool = Query(False, description="Physically delete the key row (default: soft revoke, the entry stays listed)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a tool API key. The next call using it will 401.

    With ?hard=true the row is deleted entirely instead of soft-revoked —
    this is the "remove entry" action for revoked keys in the UI. Only the
    owner can delete their own key.
    """
    row = (
        db.query(MCPUserToolKey)
        .filter(MCPUserToolKey.id == key_id, MCPUserToolKey.owner_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if hard:
        db.delete(row)
        db.commit()
        logger.info(f"User {current_user.username} deleted tool API key id={row.id}")
        return {"status": "deleted", "id": key_id}
    row.is_active = False
    row.revoked_at = datetime.now(UTC)
    db.commit()
    logger.info(f"User {current_user.username} revoked tool API key id={row.id}")
    return {"status": "revoked", "id": row.id}


class ToolKeyRevealIn(BaseModel):
    password: str = Field(..., description="The account password, re-entered to re-view the key.")


@router.post("/api-keys/{key_id}/reveal")
def reveal_tool_api_key(
    key_id: int,
    body: ToolKeyRevealIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-view a tool key's plaintext after re-entering the account password.

    Session JWT only (Tool API Keys are scoped away from /api/mcp/api-keys/*).
    The plaintext comes from the Fernet-encrypted copy stored at creation —
    the value is returned in memory for the response and never logged.
    """
    if not verify_password(body.password[:72], current_user.hashed_password):
        logger.info(f"User {current_user.username} failed tool-key reveal (wrong password) for key id={key_id}")
        raise HTTPException(status_code=401, detail="Invalid password.")
    row = (
        db.query(MCPUserToolKey)
        .filter(MCPUserToolKey.id == key_id, MCPUserToolKey.owner_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if not row.key_encrypted:
        raise HTTPException(
            status_code=410,
            detail="This key was created before re-viewing was available and cannot be recovered. Add a new key to get one you can re-view.",
        )
    try:
        plaintext = decrypt_secret(row.key_encrypted)
    except InvalidToken as err:
        logger.warning(
            f"mcp: stored tool key id={row.id} for user {current_user.username} could not be "
            "decrypted (InvalidToken) - the server encryption key (MCP_ENCRYPTION_KEY/SECRET_KEY) "
            "likely changed since it was created."
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "This key can no longer be decrypted: the server's encryption key changed since "
                "you created it. Add a new key to replace it."
            ),
        ) from err
    logger.info(f"User {current_user.username} re-viewed tool API key id={row.id}")
    return {"id": row.id, "name": row.name, "key": plaintext}


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------
@router.get("/templates/list", response_model=list[TemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all admin-approved, globally-enabled MCP templates."""
    templates = (
        db.query(MCPTemplate)
        .filter(MCPTemplate.approved_by_admin == True, MCPTemplate.enabled_global == True)  # noqa: E712
        .order_by(MCPTemplate.name)
        .all()
    )
    return [
        TemplateOut(
            id=t.id,
            name=t.name,
            description=t.description,
            config_schema=t.config_schema or {},
            image_tag=t.image_tag,
            repo_url=t.repo_url,
            approved_by_admin=t.approved_by_admin,
            enabled_global=t.enabled_global,
        )
        for t in templates
    ]


# ---------------------------------------------------------------------------
# Connection configuration (credential lifecycle)
# ---------------------------------------------------------------------------
@router.post("/config/register")
def register_mcp_config(
    body: ConfigRegisterIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Encrypt credentials and store (or upsert) the user's config for a template."""
    template = db.query(MCPTemplate).filter(MCPTemplate.id == body.template_id).first()
    if not template or not template.approved_by_admin or not template.enabled_global:
        raise HTTPException(status_code=404, detail=f"Template '{body.template_id}' is not available.")

    creds = dict(body.credentials_json)
    try:
        encrypted_blob = encrypt_credentials(creds)
    except ValueError as err:
        raise HTTPException(status_code=500, detail="Credential encryption is not configured on the server.") from err

    existing = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == current_user.id, UserMCPConfig.template_name == body.template_id)
        .first()
    )

    if existing:
        existing.credentials_json = encrypted_blob
        existing.name_display = body.display_name or existing.name_display
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        cfg = existing
    else:
        cfg = UserMCPConfig(
            owner_id=current_user.id,
            template_name=body.template_id,
            name_display=body.display_name,
            credentials_json=encrypted_blob,
            is_active=True,
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)

    # Never log credential values. Log only which template was connected.
    logger.info(f"User {current_user.username} registered {body.template_id} config id={cfg.id}")
    out = _config_to_out(cfg)
    # Return the unified proxy URL alongside the config so the UI can surface it.
    return {**out.model_dump(), "proxy_url": f"/api/mcp/proxy/{body.template_id}"}


@router.get("/config/list", response_model=list[ConfigOut])
def list_my_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's MCP connections (never includes credentials)."""
    configs = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == current_user.id)
        .order_by(UserMCPConfig.created_at.desc())
        .all()
    )
    return [_config_to_out(c) for c in configs]


@router.delete("/config/{template_id}")
def delete_mcp_config(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cfg = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == current_user.id, UserMCPConfig.template_name == template_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(cfg)
    db.commit()
    # The user's live sidecar (if any) still holds their DECRYPTED credentials
    # in its process env — tear it down NOW instead of letting the idle
    # reaper keep it up to EEPY_MCP_INSTANCE_IDLE_TIMEOUT more. Sync def on
    # purpose: this runs in the threadpool, where the blocking Docker/proc
    # calls are allowed.
    killed = mcp_bridge.kill_instances_for_user(current_user.id, template_id)
    logger.info(f"User {current_user.username} deleted {template_id} config (sidecars killed: {killed})")
    return {"status": "deleted", "template_id": template_id}


@router.get("/config/{template_id}/mcp-url")
def mcp_proxy_url(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the unified proxy URL an agent should point its MCP client at.

    Per architecture: a single backend endpoint per integration, routed through
    /api/mcp/proxy/{template_id}/*. The agent authenticates with its Eepy JWT.
    """
    cfg = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == current_user.id, UserMCPConfig.template_name == template_id)
        .first()
    )
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail=f"No active {template_id} connection.")
    return {
        "template_id": template_id,
        "proxy_url": f"/api/mcp/proxy/{template_id}",
        "usage": "Send MCP tool calls to POST {proxy_url}/{tool}?params=... with your Eepy Bearer token.",
    }


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------
@router.post("/config/{template_id}/test")
async def test_mcp_connection(
    template_id: str,
    # Sync dependency (threadpool): auth (JWT or Tool API Key — eekey route
    # scoping enforced there) + template lookup + credential decryption.
    context: tuple[MCPTemplate, dict[str, str], User] = Depends(get_proxy_context),
):
    """Validate stored credentials against the external API (read-only call).

    mcp-server runtime: run the template's `test_tool` (a read-only tool from
    the upstream server) through a short-lived sidecar. The server's text
    output is inspected for error markers.
    native runtime: the original hardcoded HappyFox path.
    """
    template, creds, current_user = context

    if template.runtime == "mcp-server":
        rctx = template.runtime_config or {}
        test_spec = rctx.get("test_tool") or {}
        test_name = test_spec.get("name")
        if not test_name:
            raise HTTPException(status_code=500,
                                detail="Template has no test_tool configured in runtime_config.")
        try:
            data, is_error = await mcp_bridge.bridge_call(
                current_user, template, creds, test_name, test_spec.get("arguments") or {})
        except mcp_bridge.BridgeError as exc:
            raise HTTPException(status_code=502, detail=f"Connection test failed: {exc}") from exc
        text = (data or "") if isinstance(data, str) else str(data)
        if is_error or re.search(r"^\s*Error\b", text) or "401" in text[:200] or "403" in text[:200]:
            return {"status": "failed",
                    "detail": "Authentication or upstream failure. "
                              + (text[:200] if text else "(no response body)")}
        return {"status": "ok", "detail": f"Sidecar responded via '{test_name}'."}

    # --- native HappyFox path (reference implementation) ---
    if template_id != "happyfox":
        raise HTTPException(status_code=400, detail=f"Connection test not implemented for '{template_id}'.")

    domain = creds.get("HAPPYFOX_DOMAIN", "")
    api_key = creds.get("HAPPYFOX_API_KEY", "")
    auth_code = creds.get("HAPPYFOX_AUTH_CODE", "")
    if not (domain and api_key):
        raise HTTPException(status_code=400, detail="Stored credentials are incomplete.")

    base = _happyfox_base(domain)
    await asyncio.to_thread(_assert_public_upstream, base)  # SSRF guard (DNS off-loop)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{base}/tickets/",
                auth=(api_key, auth_code),
                params={"status": "_pending", "size": 1},
            )
    except httpx.HTTPError as exc:
        logger.warning(f"HappyFox connection test failed to reach {domain}: {exc.__class__.__name__}")
        raise HTTPException(status_code=502, detail="Could not reach the HappyFox instance.") from exc

    if r.status_code == 200:
        data = r.json()
        total = data.get("page_info", {}).get("count", "unknown")
        return {"status": "ok", "detail": f"Connected to {domain}. Pending tickets: {total}."}
    if r.status_code in (401, 403):
        return {"status": "failed", "detail": "Authentication failed (bad API key / auth code)."}
    return {"status": "failed", "detail": f"HappyFox returned HTTP {r.status_code}."}


# ---------------------------------------------------------------------------
# Unified MCP proxy - single backend endpoint per integration
# ---------------------------------------------------------------------------
# Per-tool parameter metadata (name, json type, description).
# GET tools take params as query strings; POST/PUT tools send a JSON body.
TOOL_PARAMS: dict[str, dict[str, dict[str, Any]]] = {
    "list_tickets": {
        "status": {"type": "string", "description": "Ticket status filter (e.g. 'open', 'pending', 'resolved')."},
        "size": {"type": "integer", "description": "Page size (default 20)."},
        "page": {"type": "integer", "description": "Page number (default 1)."},
    },
    "list_statuses": {},
    "list_staff": {},
    "get_ticket_details": {
        "ticket_id": {"type": "string", "description": "The ticket ID to fetch."},
    },
    "get_ticket_messages": {
        "ticket_id": {"type": "string", "description": "The ticket ID whose messages to fetch."},
    },
    "add_ticket_update": {
        "ticket_id": {"type": "string", "description": "The ticket ID to update."},
        "comment": {"type": "string", "description": "Text of the reply or private note."},
        "is_private": {"type": "boolean", "description": "If true, post as a private internal note (default false)."},
    },
    "create_ticket": {
        "summary": {"type": "string", "description": "Subject line of the new ticket."},
        "message": {"type": "string", "description": "Body text of the ticket."},
        "email": {"type": "string", "description": "Requester's email address."},
        "first_name": {"type": "string", "description": "Requester's first name."},
        "last_name": {"type": "string", "description": "Requester's last name."},
    },
    "rename_ticket": {
        "ticket_id": {"type": "string", "description": "The ticket ID to rename."},
        "summary": {"type": "string", "description": "New subject line for the ticket."},
    },
    "change_ticket_status": {
        "ticket_id": {"type": "string", "description": "The ticket ID to change."},
        "status": {"type": "string", "description": "New ticket status (e.g. 'resolved', 'pending', 'open')."},
    },
}

TOOL_SUMMARIES = {
    "list_tickets": "List support tickets with optional status/pagination filters.",
    "list_statuses": "List all ticket statuses in the HappyFox account.",
    "list_staff": "List staff members in the HappyFox account.",
    "get_ticket_details": "Get full details of a single ticket.",
    "get_ticket_messages": "Get all messages on a ticket thread.",
    "add_ticket_update": "Post a public reply or private note on a ticket.",
    "create_ticket": "Create a new support ticket.",
    "rename_ticket": "Change the subject line of a ticket.",
    "change_ticket_status": "Change the status of a ticket.",
}

# Registry of integrations and their tools. Each entry: template id ->
# (display name, tool map of tool_name -> (upstream method, upstream path)).
# Adding a new integration adds a new entry here and a proxy handler branch;
# the unified OpenAPI spec and the single Open WebUI connection then include
# its tools automatically - users never add a second tool server connection.
TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "happyfox": {
        "display_name": "HappyFox Help Desk",
        "tool_map": {
            "list_tickets": ("GET", "/tickets/"),
            "list_statuses": ("GET", "/statuses/"),
            "list_staff": ("GET", "/staff/"),
            "get_ticket_details": ("GET", "/ticket/{ticket_id}/"),
            "get_ticket_messages": ("GET", "/ticket/{ticket_id}/"),
            "add_ticket_update": ("POST", "/ticket/{ticket_id}/update"),
            "create_ticket": ("POST", "/ticket"),
            "rename_ticket": ("PUT", "/ticket/{ticket_id}/"),
            "change_ticket_status": ("POST", "/ticket/{ticket_id}/status"),
        },
    },
}

# Backwards-compatible alias for the proxy handler below.
TOOL_MAP = TEMPLATE_REGISTRY["happyfox"]["tool_map"]


@router.api_route(
    "/proxy/{template_id}/{tool_name}",
    methods=["GET", "POST", "PUT"],
)
async def mcp_proxy(
    template_id: str,
    tool_name: str,
    request: Request,
    # Sync dependency (threadpool): auth (JWT or Tool API Key — eekey route
    # scoping enforced there) + template lookup + credential decryption.
    context: tuple[MCPTemplate, dict[str, str], User] = Depends(get_proxy_context),
    # Same shared session (FastAPI caches the dependency per request); used
    # for the usage counter after the call.
    db: Session = Depends(get_db),
):
    """Route a single MCP tool call through the user's encrypted credentials.

    Also reachable at `/api/mcp/{template_id}/{tool_name}` (no `proxy`
    segment) via the mcp_proxy_alias bound at the very end of this module:
    the unified OpenAPI spec is consumed by clients (notably Open WebUI)
    that append spec paths to the pasted base URL and ignore
    `servers[].url`, so both call shapes must hit the same handler. The
    alias MUST stay the LAST route registered on this router — it is a
    two-segment catch-all that would otherwise shadow every static
    two-segment route registered after it (including the doubled
    /openapi.json/openapi.json spec path); unknown templates 404 via
    get_proxy_context.

    `params` may arrive as query params (GET) or a JSON body (POST/PUT).
    Credentials are decrypted in memory only (on a worker thread) and never
    appear in the response path.

    Two runtimes:
      mcp-server - generic sidecar bridge: spawn/reuse the upstream MCP server
                   (per user+credentials) and forward a standard tools/call.
      native     - hardcoded in-backend tool map (reference implementation).
    """
    template, creds, current_user = context

    # Collect params from either the JSON body or the query string.
    params: dict[str, Any] = {}
    try:
        body = await request.json()
        if isinstance(body, dict):
            params.update(body)
    except Exception:
        pass
    if request.query_params:
        params.update(dict(request.query_params))

    if template.runtime == "mcp-server":
        return await _proxy_mcp_server(db, template, current_user, creds, tool_name, params)
    return await _proxy_native(db, template, current_user, creds, tool_name, params)


def _mark_used(db: Session, user: User, template_id: str) -> None:
    cfg = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == user.id, UserMCPConfig.template_name == template_id)
        .first()
    )
    if cfg:
        cfg.last_used_at = datetime.now(UTC)
        db.commit()


async def _proxy_mcp_server(db: Session, template: MCPTemplate, user: User,
                            creds: dict[str, str], tool_name: str,
                            params: dict[str, Any]) -> dict[str, Any]:
    """Generic proxy: forward the call to the upstream MCP server sidecar."""
    known = {t.get("name") for t in (template.discovered_tools or []) if isinstance(t, dict)}
    if known and tool_name not in known:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'.",
                            headers={"X-Allowed-Tools": ", ".join(sorted(n for n in known if n))})
    try:
        data, is_error = await mcp_bridge.bridge_call(user, template, creds, tool_name, params or {})
    except mcp_bridge.BridgeError as exc:
        raise HTTPException(status_code=502, detail=f"Sidecar call failed: {exc}") from exc

    await asyncio.to_thread(_mark_used, db, user, template.id)  # sync DB commit off the loop
    return {"status_code": 200 if not is_error else 502,
            "tool": tool_name,
            "data": data,
            "is_error": is_error}


async def _proxy_native(db: Session, template: MCPTemplate, user: User, creds: dict[str, str],
                        tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Native (hardcoded) proxy path - reference implementation (HappyFox)."""
    entry = TEMPLATE_REGISTRY.get(template.id)
    if not entry:
        raise HTTPException(status_code=400, detail=f"Native proxy not implemented for '{template.id}'.")
    tool_map = entry["tool_map"]
    if tool_name not in tool_map:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'.",
                            headers={"X-Allowed-Tools": ", ".join(tool_map)})

    method, path_tpl = tool_map[tool_name]

    p = dict(params or {})
    # Pull path params out of the params dict.
    path = path_tpl
    for m in re.findall(r"\{(\w+)\}", path_tpl):
        if m in p:
            path = path.replace(f"{{{m}}}", str(p.pop(m)))
        else:
            raise HTTPException(status_code=400, detail=f"Missing required param '{m}' for {tool_name}.")

    base = _happyfox_base(creds.get("HAPPYFOX_DOMAIN", ""))
    await asyncio.to_thread(_assert_public_upstream, base)  # SSRF guard (DNS off-loop)
    api_key = creds.get("HAPPYFOX_API_KEY", "")
    auth_code = creds.get("HAPPYFOX_AUTH_CODE", "")

    # GET tools take params as query string; write tools send a JSON body.
    query = {k: v for k, v in p.items()}
    json_body = p if method in ("POST", "PUT") else None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                r = await client.get(f"{base}{path}", auth=(api_key, auth_code), params=query)
            else:
                r = await client.request(
                    method,
                    f"{base}{path}",
                    auth=(api_key, auth_code),
                    params=query or None,
                    json=json_body,
                )
    except httpx.HTTPError as exc:
        logger.warning(f"HappyFox proxy {tool_name} network error: {exc.__class__.__name__}")
        raise HTTPException(status_code=502, detail="Upstream HappyFox request failed.") from exc

    await asyncio.to_thread(_mark_used, db, user, template.id)  # sync DB commit off the loop

    try:
        payload = r.json()
    except Exception:
        payload = r.text

    return {"status_code": r.status_code, "tool": tool_name, "data": payload}


# ---------------------------------------------------------------------------
# Unified OpenAPI 3 spec - the SINGLE Open WebUI "Tool Server" connection
# ---------------------------------------------------------------------------
# Open WebUI's external Tool Server connector consumes a standard OpenAPI doc:
# it takes a URL, fetches the spec, and lists every operation as a tool the LLM
# can call, sending the configured auth (Bearer) on each request.
#
# This is ONE document covering EVERY Eepy integration. Users make a single
# connection in Open WebUI; when Eepy ships a new integration (or the user
# connects a new one), its tools appear here automatically - no re-import,
# no second tool server, no second key. The key is user-scoped, so each call
# still resolves against the caller's own active connections (404 otherwise).
# Public on purpose: contains no credentials - only tool names, parameters,
# and the base URL.


def _build_tool_operation(tool_name: str, method: str, path_tpl: str, tag: str, display_name: str) -> dict[str, Any]:
    """Build a single OpenAPI operation object for one native (hardcoded) tool."""
    params_meta = TOOL_PARAMS.get(tool_name, {})
    path_params = {m for m in re.findall(r"\{(\w+)\}", path_tpl)}
    required = [p for p in path_params] + [
        p for p, spec in params_meta.items() if spec.get("required")
    ]
    verb = method.lower()

    if method == "GET":
        parameters = []
        for pname, spec in params_meta.items():
            parameters.append({
                "name": pname,
                "in": "query",
                "required": pname in required,
                "schema": {"type": spec["type"]},
                "description": spec.get("description", ""),
            })
        op = {
            "operationId": tool_name,
            "summary": TOOL_SUMMARIES.get(tool_name, tool_name),
            "description": f"{display_name} tool '{tool_name}' proxied by Eepy (upstream {method} {path_tpl}).",
            "tags": [tag],
            "parameters": parameters,
            "responses": {"200": {"description": "Success"}},
        }
    else:  # POST / PUT -> JSON body
        body_props: dict[str, Any] = {}
        for pname, spec in params_meta.items():
            body_props[pname] = {"type": spec["type"]}
            if spec.get("description"):
                body_props[pname]["description"] = spec["description"]
        for p in path_params:
            if p not in body_props:
                body_props[p] = {"type": "string", "description": f"{p} (path parameter)."}
        op = {
            "operationId": tool_name,
            "summary": TOOL_SUMMARIES.get(tool_name, tool_name),
            "description": f"{display_name} tool '{tool_name}' proxied by Eepy (upstream {method} {path_tpl}).",
            "tags": [tag],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": body_props,
                            "required": required or (list(body_props.keys()) if body_props else []),
                        }
                    }
                },
            },
            "responses": {"200": {"description": "Success"}},
        }
    return {verb: op}


def _build_discovered_operation(tool: dict[str, Any], tag: str, display_name: str) -> dict[str, Any]:
    """Build an OpenAPI operation from a discovered (tools/list) tool schema.

    mcp-server templates are all invoked via POST /api/mcp/proxy/{template}/{tool}
    with a JSON arguments body - the upstream server owns the parameter schema,
    so we pass it through verbatim.
    """
    tool_name = tool["name"]
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    body_props: dict[str, Any] = {}
    for pname, spec in props.items():
        if isinstance(spec, dict):
            body_props[pname] = spec
        else:
            body_props[pname] = {"type": "string"}
    return {
        "post": {
            "operationId": tool_name,
            "summary": (tool.get("description") or tool_name).split("\n", 1)[0][:200],
            "description": f"{display_name} tool '{tool_name}' served by the upstream MCP server and proxied by Eepy.",
            "tags": [tag],
            "requestBody": {
                "required": bool(required or props),
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": body_props,
                            "required": [r for r in required if r in props] or (list(props.keys()) if props else []),
                        }
                    }
                },
            },
            "responses": {"200": {"description": "Success (tool text result)"}},
        }
    }


def _build_minimal_operation(tag: str, tool_name: str, display_name: str) -> dict[str, Any]:
    """Fallback operation for an mcp-server tool that has no discovered schema yet.

    The bridge forwards the whole JSON body as the tool's arguments, so an
    untyped object schema still works at call time. Admin discovery
    (POST /superuser/mcp/templates/{id}/discover) replaces this with the real
    schema from the upstream server.
    """
    return {
        "post": {
            "operationId": tool_name,
            "summary": f"{display_name} tool '{tool_name}' (run admin discovery for the full schema)",
            "description": f"{display_name} tool proxied by Eepy. Argument schema pending admin discovery.",
            "tags": [tag],
            "requestBody": {
                "required": False,
                "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}},
            },
            "responses": {"200": {"description": "Success (tool text result)"}},
        }
    }


@router.get("/openapi.json")
@router.get("/openapi.json/openapi.json", include_in_schema=False)
def unified_openapi_spec(request: Request, db: Session = Depends(get_db)):
    """The single OpenAPI 3.0 document for the ENTIRE Eepy tool surface.

    Users import THIS one URL into Open WebUI as their only Tool Server
    connection. It lists every approved+enabled template: native integrations
    from the hardcoded registry, mcp-server integrations from their stored
    tools/list discovery. Per-user availability is enforced at call time.

    Served at BOTH /api/mcp/openapi.json and /api/mcp/openapi.json/openapi.json:
    Open WebUI's Tool Server connector appends "/openapi.json" to whatever URL
    the user pastes, so pasting the spec URL itself would hit the doubled path.
    The doubled route is the same spec — both forms work.
    """
    base_url = str(request.base_url).rstrip("/")
    # The spec is rooted at /api/mcp (the URL users paste into Open WebUI).
    # Paths below are "/proxy/{id}/{tool}" so the full call URL is the same
    # whether a client (a) concatenates spec path onto the pasted base URL —
    # Open WebUI does this and IGNORES servers[].url — or (b) composes
    # servers[0].url + path per the OpenAPI spec. Both yield
    # /api/mcp/proxy/{id}/{tool}.
    api_base = f"{base_url}/api/mcp"

    paths: dict[str, Any] = {}
    tags: list = []

    rows = (
        db.query(MCPTemplate)
        .filter(MCPTemplate.approved_by_admin == True, MCPTemplate.enabled_global == True)  # noqa: E712
        .order_by(MCPTemplate.name)
        .all()
    )
    for t in rows:
        tags.append({"name": t.id, "description": t.name})
        if t.runtime == "mcp-server":
            tools = [x for x in (t.discovered_tools or []) if isinstance(x, dict) and x.get("name")]
            if tools:
                for tool in tools:
                    paths[f"/proxy/{t.id}/{tool['name']}"] = _build_discovered_operation(tool, t.id, t.name)
            else:
                # Not discovered yet: list the known tool names (from
                # runtime_config.tool_names, or the native registry as a last
                # resort) so the integration still appears in Open WebUI before
                # an admin runs discovery.
                rctx = t.runtime_config or {}
                known_names = [str(n) for n in (rctx.get("tool_names") or [])]
                if not known_names:
                    entry = TEMPLATE_REGISTRY.get(t.id)
                    known_names = list(entry["tool_map"].keys()) if entry else ["(run discovery)"]
                for name in known_names:
                    paths[f"/proxy/{t.id}/{name}"] = _build_minimal_operation(t.id, name, t.name)
        else:
            entry = TEMPLATE_REGISTRY.get(t.id)
            if not entry:
                continue
            for tool_name, (method, path_tpl) in entry["tool_map"].items():
                paths[f"/proxy/{t.id}/{tool_name}"] = _build_tool_operation(
                    tool_name, method, path_tpl, t.id, t.name)

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "Eepy Host - Unified Integration Tools",
            "version": "1.0.0",
            "description": (
                "Eepy Host managed integration tools, delivered as a SINGLE external tool server. "
                "Each operation is a tool; Eepy holds your encrypted credentials server-side and "
                "proxies the call. Authenticate with your Eepy Tool API Key (Bearer) - one key "
                "covers every integration you have connected. New Eepy integrations appear here "
                "automatically; no re-import required. Tools for integrations you have not connected "
                "return 404."
            ),
        },
        "servers": [{"url": api_base, "description": "Eepy Host API root - tool calls live under /proxy/{template}/{tool}"}],
        "tags": tags,
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Eepy Tool API Key (starts with 'eekey_'). Generated in the Eepy dashboard, Open WebUI section.",
                }
            }
        },
        "security": [{"bearerAuth": {}}],
    }

    return JSONResponse(content=spec, media_type="application/json")


@router.api_route(
    "/{template_id}/{tool_name}",
    methods=["GET", "POST", "PUT"],
    include_in_schema=False,
)
async def mcp_proxy_alias(
    template_id: str,
    tool_name: str,
    request: Request,
    context: tuple[MCPTemplate, dict[str, str], User] = Depends(get_proxy_context),
    db: Session = Depends(get_db),
):
    """Backwards-compatible proxy shape without the `proxy` segment.

    Open WebUI (and any OpenAPI client that ignores servers[].url) appends
    the spec's paths to the pasted base URL (.../api/mcp), producing
    /api/mcp/{template_id}/{tool_name}. Pre-fix spec imports call this shape,
    so it must keep working without a re-import. Bound LAST in this module on
    purpose: as a two-segment catch-all it would shadow later-registered
    static routes (e.g. /openapi.json/openapi.json) if registered earlier.
    """
    return await mcp_proxy(template_id, tool_name, request, context, db)
