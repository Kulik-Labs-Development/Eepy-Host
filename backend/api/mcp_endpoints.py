"""MCP integration endpoints - Phase 5 (HappyFox template #1).

Security model:
- Credentials are encrypted with Fernet (MCP_ENCRYPTION_KEY) before being written to
  the `user_mcp_configs` table. Only ciphertext is ever persisted.
- Decryption happens ONLY inside a request handler, in memory, for the duration of the
  request. Plaintext credentials are never logged, never returned to the client, and
  never written to disk.
- Every endpoint requires a valid JWT (get_current_user). The backend is the source of
  truth for authorization; the frontend is never trusted for access control.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import decode_access_token
from database import get_db, User
from models.mcp_models import MCPTemplate, UserMCPConfig
from utils.crypto import encrypt_credentials, decrypt_credentials

logger = logging.getLogger("eepy-backend")

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
    display_name: Optional[str] = None
    credentials_json: Dict[str, str] = Field(..., description="Plaintext template credentials. Encrypted server-side.")


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    config_schema: Dict[str, Any]
    image_tag: Optional[str] = None
    approved_by_admin: bool
    enabled_global: bool


class ConfigOut(BaseModel):
    id: int
    template_name: str
    name_display: Optional[str]
    is_active: bool
    created_at: Optional[datetime]
    last_used_at: Optional[datetime]


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


def _load_active_creds(db: Session, user: User, template_id: str) -> Dict[str, str]:
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
    except ValueError:
        raise HTTPException(status_code=500, detail="Credential encryption is not configured on the server.")

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
    current_user: User = Depends(get_current_user),
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
        raise HTTPException(status_code=502, detail="Could not reach the HappyFox instance.")

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
# Maps an MCP tool name -> (happyfox http method, path template, param transform).
# This lets agents use the standard HappyFox MCP tool names over the Eepy gateway
# without running a per-user container.
TOOL_MAP = {
    "list_tickets": ("GET", "/tickets/"),
    "list_statuses": ("GET", "/statuses/"),
    "list_staff": ("GET", "/staff/"),
    "get_ticket_details": ("GET", "/ticket/{ticket_id}/"),
    "get_ticket_messages": ("GET", "/ticket/{ticket_id}/"),
    "add_ticket_update": ("POST", "/ticket/{ticket_id}/update"),
    "create_ticket": ("POST", "/ticket"),
    "rename_ticket": ("PUT", "/ticket/{ticket_id}/"),
    "change_ticket_status": ("POST", "/ticket/{ticket_id}/status"),
}


@router.api_route(
    "/proxy/{template_id}/{tool_name}",
    methods=["GET", "POST", "PUT"],
)
async def mcp_proxy(
    template_id: str,
    tool_name: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Collect params from either the JSON body or the query string.
    params: Dict[str, Any] = {}
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
        raise HTTPException(status_code=502, detail="Upstream HappyFox request failed.")

    # Track last-used for monetization metrics.
    cfg = (
        db.query(UserMCPConfig)
        .filter(UserMCPConfig.owner_id == current_user.id, UserMCPConfig.template_name == template_id)
        .first()
    )
    if cfg:
        cfg.last_used_at = datetime.utcnow()
        db.commit()

    try:
        payload = r.json()
    except Exception:
        payload = r.text

    return {"status_code": r.status_code, "tool": tool_name, "data": payload}
