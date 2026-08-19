"""MCP integration endpoints - Phase 5 (HappyFox template #1) + Open WebUI Tool Server export.

Security model:
- Credentials are encrypted with Fernet (MCP_ENCRYPTION_KEY) before being written to
  the `user_mcp_configs` table. Only ciphertext is ever persisted.
- Decryption happens ONLY inside a request handler, in memory, for the duration of the
  request. Plaintext credentials are never logged, never returned to the client, and
  never written to disk.
- Every endpoint requires a valid JWT (get_current_user). The backend is the source of
  truth for authorization; the frontend is never trusted for access control.
- Proxy + connection-test endpoints additionally accept a user-scoped, revocable
  Tool API Key (Bearer `eekey_...`). ONE key per user unlocks EVERY integration
  they have connected — this is what makes Open WebUI a single Tool Server
  connection. The key is accepted ONLY on /api/mcp/proxy/* and /api/mcp/config/*
  — never on /user/*, /auth/*, billing, or superuser routes — and each proxy call
  still requires the user to have an active connection to the requested template.
  Only a SHA-256 hash is stored; the plaintext key is returned once at creation
  and is never persisted.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import decode_access_token
from database import User, get_db
from models.mcp_models import MCPTemplate, MCPUserToolKey, UserMCPConfig
from utils.crypto import decrypt_credentials, encrypt_credentials
from utils.logging_setup import logger

router = APIRouter(prefix="/api/mcp", tags=["mcp-integrations"])


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
    """Return decrypted credentials for the user's active config of a template, or 404."""
    cfg = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == user.id, UserMCPConfig.template_name == template_id)
        .first()
    )
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail=f"No active {template_id} connection for this user.")
    return decrypt_credentials(cfg.credentials_json)


def _happyfox_base(domain: str) -> str:
    domain = (domain or "").strip()
    if not domain:
        raise HTTPException(status_code=400, detail="HAPPYFOX_DOMAIN is empty.")
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    return f"{domain.rstrip('/')}/api/1.1/json"


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

    The key is ONLY honored on /api/mcp/proxy/{template}/* and
    /api/mcp/config/{template}/test. On any other route an eekey_ token is treated
    as a (invalid) JWT and rejected - so the key can never touch /user/*, /auth/*,
    /superuser/*, billing, or even other MCP management endpoints (keys, template
    list, config register/delete). Per-call, the proxy additionally requires the
    user to have an active connection to the requested template.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")
    token = auth_header.split(" ", 1)[1].strip()

    key_allowed = bool(
        re.match(r"^/api/mcp/proxy/[\w-]+/", request.url.path)
        or re.match(r"^/api/mcp/config/[\w-]+/test$", request.url.path)
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


def _generate_tool_key() -> str:
    return "eekey_" + secrets.token_urlsafe(32)


def _tool_key_out(row: MCPUserToolKey, show_plaintext: str | None = None) -> dict[str, Any]:
    out = {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }
    if show_plaintext is not None:
        # Returned exactly once, at creation time. Never persisted.
        out["key"] = show_plaintext
    return out


# ---------------------------------------------------------------------------
# User Tool API Keys (single connection for Open WebUI / any external tool server)
# ---------------------------------------------------------------------------
class ToolKeyCreateIn(BaseModel):
    name: str | None = Field("Open WebUI", description="Label shown in the Eepy UI.")


@router.post("/api-keys")
async def create_tool_api_key(
    body: ToolKeyCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a user-scoped, revocable Tool API Key.

    ONE key per user covers EVERY integration they have connected — this is what
    makes Open WebUI a single Tool Server connection. The plaintext key is
    returned ONCE; only a SHA-256 hash is stored. The key works only on
    /api/mcp/proxy/* and /api/mcp/config/*, and each call still requires an
    active connection to the requested template.
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
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(f"User {current_user.username} created user tool API key id={row.id}")
    return _tool_key_out(row, show_plaintext=plaintext)


@router.get("/api-keys")
async def list_tool_api_keys(
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
async def revoke_tool_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a tool API key. The next call using it will 401."""
    row = (
        db.query(MCPUserToolKey)
        .filter(MCPUserToolKey.id == key_id, MCPUserToolKey.owner_id == current_user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.is_active = False
    row.revoked_at = datetime.now(UTC)
    db.commit()
    logger.info(f"User {current_user.username} revoked tool API key id={row.id}")
    return {"status": "revoked", "id": row.id}


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------
@router.get("/templates/list", response_model=list[TemplateOut])
async def list_templates(
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
            approved_by_admin=t.approved_by_admin,
            enabled_global=t.enabled_global,
        )
        for t in templates
    ]


# ---------------------------------------------------------------------------
# Connection configuration (credential lifecycle)
# ---------------------------------------------------------------------------
@router.post("/config/register")
async def register_mcp_config(
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
async def list_my_configs(
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
async def delete_mcp_config(
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
    return {"status": "deleted", "template_id": template_id}


@router.get("/config/{template_id}/mcp-url")
async def mcp_proxy_url(
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
    db: Session = Depends(get_db),
    # Accept EITHER a session JWT OR a scoped Tool API Key so the Open WebUI
    # Tool Server connection can self-test.
    current_user: User = Depends(get_current_user_or_key),
):
    """Validate stored credentials against the external API (read-only call).

    For HappyFox, we hit the read-only /tickets/ list endpoint with size=1.
    """
    if template_id != "happyfox":
        raise HTTPException(status_code=400, detail=f"Connection test not implemented for '{template_id}'.")

    creds = _load_active_creds(db, current_user, template_id)
    domain = creds.get("HAPPYFOX_DOMAIN", "")
    api_key = creds.get("HAPPYFOX_API_KEY", "")
    auth_code = creds.get("HAPPYFOX_AUTH_CODE", "")
    if not (domain and api_key):
        raise HTTPException(status_code=400, detail="Stored credentials are incomplete.")

    base = _happyfox_base(domain)
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
    db: Session = Depends(get_db),
    # Accept EITHER a session JWT OR a scoped Tool API Key (Open WebUI).
    current_user: User = Depends(get_current_user_or_key),
):
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
    """Route a single MCP tool call through the user's encrypted credentials.

    `params` may arrive as query params (GET) or a JSON body (POST/PUT).
    Credentials are decrypted in memory only and stripped from the response path.
    """
    if template_id != "happyfox":
        raise HTTPException(status_code=400, detail=f"Proxy not implemented for '{template_id}'.")
    if tool_name not in TOOL_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'.",
                            headers={"X-Allowed-Tools": ", ".join(TOOL_MAP)})

    method, path_tpl = TOOL_MAP[tool_name]

    p = dict(params or {})
    # Pull path params out of the params dict.
    path = path_tpl
    for m in re.findall(r"\{(\w+)\}", path_tpl):
        if m in p:
            path = path.replace(f"{{{m}}}", str(p.pop(m)))
        else:
            raise HTTPException(status_code=400, detail=f"Missing required param '{m}' for {tool_name}.")

    creds = _load_active_creds(db, current_user, template_id)
    base = _happyfox_base(creds.get("HAPPYFOX_DOMAIN", ""))
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

    # Track last-used for monetization metrics.
    cfg = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == current_user.id, UserMCPConfig.template_name == template_id)
        .first()
    )
    if cfg:
        cfg.last_used_at = datetime.now(UTC)
        db.commit()

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
    """Build a single OpenAPI operation object for one tool."""
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


@router.get("/openapi.json")
async def unified_openapi_spec(request: Request):
    """The single OpenAPI 3.0 document for the ENTIRE Eepy tool surface.

    Users import THIS one URL into Open WebUI as their only Tool Server
    connection. It lists every integration in the registry; per-user
    availability is enforced at call time.
    """
    base_url = str(request.base_url).rstrip("/")
    proxy_base = f"{base_url}/api/mcp/proxy"

    paths: dict[str, Any] = {}
    tags: list = []
    for template_id, entry in TEMPLATE_REGISTRY.items():
        display_name = entry["display_name"]
        tags.append({"name": template_id, "description": display_name})
        for tool_name, (method, path_tpl) in entry["tool_map"].items():
            op_path = f"/{template_id}/{tool_name}"
            paths[op_path] = _build_tool_operation(tool_name, method, path_tpl, template_id, display_name)

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
        "servers": [{"url": proxy_base, "description": "Eepy unified MCP proxy - all integrations"}],
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
