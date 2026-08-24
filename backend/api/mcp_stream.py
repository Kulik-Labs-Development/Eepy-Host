"""MCP streamable-HTTP endpoint - the Eepy "AI Platform connector".

Eepy Host's public surface is an OpenAPI REST proxy (for Open WebUI and other
tool-server connectors). This module adds the other half of the agent story:
a REAL Model Context Protocol endpoint at POST /api/mcp/mcp speaking
streamable-HTTP, so any MCP client (opencode, Claude Desktop, Cursor, ...)
can connect with a URL + a Tool API Key and use every integration the user
has connected - the same one-key-unlocks-everything contract as the proxy.

Design:
- Stateful-free (stateless=True, json_response=True): every request is a
  self-contained JSON-RPC exchange; no server-side session store, so any
  backend replica on the host can serve any request (multi-replica safe the
  same way the proxy is). Plain JSON responses (no SSE) also avoid
  proxy/Portainer SSE buffering issues.
- Auth is an ASGI middleware in front of the session manager: it resolves
  the caller via the SAME _resolve_scoped_user used by the proxy (session
  JWT OR eekey_ Tool API Key; eekey scope is widened to this path in
  mcp_endpoints) and hands the User to the handlers through a ContextVar -
  the SDK's low-level Server handlers have no access to the HTTP request.
- tools/list is PER-USER: only integrations the caller has an ACTIVE
  connection for are listed (a tool you cannot call should not be offered).
- tools/call routes exactly like the REST proxy: mcp-server runtime through
  the generic sidecar bridge, native runtime through the hardcoded registry
  (reference path). Credentials are decrypted in memory only, per the
  project's security model.

Wired in main.py: the session manager's run() context lives in the app
lifespan; the middleware is added INSIDE the CORS middleware so responses
carry the normal CORS headers (harmless; the clients are non-browser).
"""

import asyncio
import json
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from mcp import types
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.orm import Session

from api import mcp_bridge
from api.mcp_endpoints import (
    MCP_STREAM_PATH,
    TEMPLATE_REGISTRY,
    TOOL_PARAMS,
    TOOL_SUMMARIES,
    _load_active_creds,
    _resolve_scoped_user,
)
from database import SessionLocal, User
from models.mcp_models import MCPTemplate, UserMCPConfig
from utils.logging_setup import logger

# The authenticated caller for the in-flight /api/mcp/mcp request. Set by the
# ASGI middleware, read by the low-level Server handlers below (the SDK gives
# handlers no access to the HTTP request, so the user rides a ContextVar).
_current_mcp_user: ContextVar[User | None] = ContextVar("eepy_mcp_user", default=None)

_MCP_TOOL_NAME_MAX = 64


def _sanitize_tool_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:_MCP_TOOL_NAME_MAX]


def _tool_ref(template_id: str, tool_name: str) -> str:
    """The MCP-side name for one Eepy tool: {template_id}__{tool_name}."""
    return _sanitize_tool_name(f"{template_id}__{tool_name}")


# ---------------------------------------------------------------------------
# Tool listing (per-user)
# ---------------------------------------------------------------------------
def _mcp_tools_for_template(template: MCPTemplate) -> list[types.Tool]:
    """MCP Tool objects for one template (discovered schemas when available)."""
    if template.runtime == "mcp-server":
        tools = [t for t in (template.discovered_tools or []) if isinstance(t, dict) and t.get("name")]
        if tools:
            return [
                types.Tool(
                    name=_tool_ref(template.id, str(t["name"])),
                    description=(t.get("description") or "").strip() or f"{template.name} tool '{t['name']}'.",
                    inputSchema=t.get("inputSchema") or {"type": "object", "properties": {}},
                )
                for t in tools
            ]
        # Not discovered yet: expose the best-effort names so the integration
        # is usable immediately (arguments are forwarded verbatim upstream).
        rctx = template.runtime_config or {}
        names = [str(n) for n in (rctx.get("tool_names") or [])]
        if not names:
            entry = TEMPLATE_REGISTRY.get(template.id)
            names = list(entry["tool_map"].keys()) if entry else []
        return [
            types.Tool(
                name=_tool_ref(template.id, n),
                description=f"{template.name} tool '{n}' (schema pending admin discovery; arguments are "
                            "forwarded to the upstream server as-is).",
                inputSchema={"type": "object"},
            )
            for n in names
        ]
    # native runtime (legacy/reference path)
    entry = TEMPLATE_REGISTRY.get(template.id)
    if not entry:
        return []
    out = []
    for tool_name, (_method, path_tpl) in entry["tool_map"].items():
        params_meta = TOOL_PARAMS.get(tool_name, {})
        path_params = {m for m in re.findall(r"\{(\w+)\}", path_tpl)}
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in sorted(path_params):
            props[p] = {"type": "string", "description": f"{p} (path parameter)."}
            required.append(p)
        for pname, spec in params_meta.items():
            props[pname] = {"type": spec["type"]}
            if spec.get("description"):
                props[pname]["description"] = spec["description"]
            if spec.get("required"):
                required.append(pname)
        out.append(types.Tool(
            name=_tool_ref(template.id, tool_name),
            description=TOOL_SUMMARIES.get(tool_name, tool_name),
            inputSchema={"type": "object", "properties": props, "required": required},
        ))
    return out


def _list_tools_sync(user: User) -> list[types.Tool]:
    """tools/list payload: tools for the user's ACTIVE connections only."""
    db: Session = SessionLocal()
    try:
        templates = (
            db.query(MCPTemplate)
            .filter(MCPTemplate.approved_by_admin == True, MCPTemplate.enabled_global == True)  # noqa: E712
            .order_by(MCPTemplate.id)
            .all()
        )
        active = {
            c.template_name
            for c in db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user.id, UserMCPConfig.is_active == True)  # noqa: E712
        }
        tools: list[types.Tool] = []
        for t in templates:
            if t.id in active:
                tools.extend(_mcp_tools_for_template(t))
        return tools
    finally:
        db.close()


def _mark_used_sync(user_id: int, template_id: str) -> None:
    db: Session = SessionLocal()
    try:
        cfg = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user_id, UserMCPConfig.template_name == template_id)
            .first()
        )
        if cfg:
            cfg.last_used_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


def _load_template_creds(user: User, template_id: str) -> tuple[MCPTemplate, dict[str, str]]:
    """Template + decrypted credentials for one active connection (or HTTPException)."""
    db: Session = SessionLocal()
    try:
        template = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if not template or not template.approved_by_admin or not template.enabled_global:
            raise HTTPException(status_code=404, detail=f"Unknown template '{template_id}'.")
        creds = _load_active_creds(db, user, template_id)
        return template, creds
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The MCP server
# ---------------------------------------------------------------------------
server = Server(
    "eepy-host",
    instructions=(
        "Eepy Host integration tools. Tool names are {template}__{tool} for the "
        "integrations this user has connected in the Eepy dashboard (call "
        "eepy__status to see which). Calls are proxied through Eepy with the "
        "user's encrypted credentials; results are JSON text. Tool errors come "
        "back as isError results with a detail message."
    ),
)


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    user = _current_mcp_user.get()
    if user is None:
        return []
    tools = await asyncio.to_thread(_list_tools_sync, user)
    tools.append(types.Tool(
        name="eepy__status",
        description="Show this user's connected Eepy integrations and tool counts (no upstream call).",
        inputSchema={"type": "object"},
    ))
    return tools


def _result(text: str, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=is_error)


def _error_result(message: str) -> types.CallToolResult:
    return _result(message, is_error=True)


async def _native_call(template: MCPTemplate, user: User, creds: dict[str, str],
                       tool_name: str, params: dict[str, Any]) -> tuple[int, Any]:
    """Native runtime (legacy/reference HappyFox path) - mirrors
    mcp_endpoints._proxy_native with standalone session handling (the ASGI
    middleware path has no FastAPI request-scoped session)."""
    from api.mcp_endpoints import _proxy_native

    # A fresh session, used only by _proxy_native's _mark_used (via to_thread).
    db: Session = SessionLocal()
    try:
        result = await _proxy_native(db, template, user, creds, tool_name, params)
    finally:
        db.close()
    return result.get("status_code", 502), result.get("data")


@server.call_tool(validate_input=False)
async def _call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
    """tools/call -> the same routing as the REST proxy (bridge or native)."""
    user = _current_mcp_user.get()
    if user is None:
        return _error_result("Not authenticated.")

    template_id, sep, tool_name = name.partition("__")
    if not sep or not tool_name:
        return _error_result(f"Invalid tool name '{name}' - expected '<template>__<tool>'.")

    if name == "eepy__status":
        tools = await asyncio.to_thread(_list_tools_sync, user)
        per_template: dict[str, int] = {}
        for t in tools:
            tid = t.name.split("__", 1)[0]
            per_template[tid] = per_template.get(tid, 0) + 1
        summary = {
            "connected_integrations": [
                {"template": k, "tools": v} for k, v in sorted(per_template.items())
            ],
            "total_tools": len(tools),
        }
        if not per_template:
            summary["hint"] = ("No active connections yet. Connect an integration in the Eepy "
                               "dashboard (MCP Servers) and its tools appear here automatically.")
        return _result(json.dumps(summary, indent=2))

    try:
        template, creds = await asyncio.to_thread(_load_template_creds, user, template_id)
    except HTTPException as exc:
        return _error_result(str(exc.detail))

    if template.runtime == "mcp-server":
        known = {t.get("name") for t in (template.discovered_tools or []) if isinstance(t, dict)}
        if known and tool_name not in known:
            allowed = ", ".join(sorted(n for n in known if n))[:500]
            return _error_result(f"Unknown tool '{tool_name}' for {template_id} (allowed: {allowed}).")
        try:
            data, is_error = await mcp_bridge.bridge_call(user, template, creds, tool_name, arguments or {})
        except mcp_bridge.BridgeError as exc:
            logger.warning(f"mcp-stream: {template_id}/{tool_name} bridge error for user {user.username}: {exc}")
            return _error_result(f"Sidecar call failed: {exc}")
        await asyncio.to_thread(_mark_used_sync, user.id, template.id)
        text = data if isinstance(data, str) else json.dumps(data, default=str, indent=2)
        if is_error:
            return _result(text or "(upstream error)", is_error=True)
        return _result(text or "(no output)")

    # native runtime (legacy/reference path)
    try:
        status_code, data = await _native_call(template, user, creds, tool_name, arguments or {})
    except HTTPException as exc:
        return _error_result(str(exc.detail))
    await asyncio.to_thread(_mark_used_sync, user.id, template.id)
    text = data if isinstance(data, str) else json.dumps(data, default=str, indent=2)
    if status_code >= 400:
        return _result(f"HTTP {status_code}: {text[:4000]}", is_error=True)
    return _result(text)


# ---------------------------------------------------------------------------
# Streamable-HTTP session manager (stateless: safe behind any routing layer)
# ---------------------------------------------------------------------------
session_manager = StreamableHTTPSessionManager(
    app=server,
    stateless=True,
    json_response=True,
    # This endpoint authenticates every request with a Bearer token (JWT or
    # Tool API Key) - the same model as the REST proxy - so the SDK's
    # cookie-oriented DNS-rebinding Host/Origin checks are not applicable
    # (and would reject legitimate dials through container IPs/proxies).
    security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ---------------------------------------------------------------------------
# Auth middleware: resolve the caller, then hand the request to the manager
# ---------------------------------------------------------------------------
class MCPStreamAuthMiddleware:
    """Intercepts /api/mcp/mcp before FastAPI routing: authenticates via the
    shared scoped-user resolver (JWT OR eekey_), exposes the user to the MCP
    handlers through a ContextVar, and 401s with a JSON error otherwise.
    Everything else passes through untouched."""

    def __init__(self, app: Any, manager: StreamableHTTPSessionManager):
        self.app = app
        self.manager = manager

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if (
            scope["type"] == "http"
            and scope["path"] == MCP_STREAM_PATH
            and scope["method"] in ("POST", "GET", "DELETE")
        ):
            user, status_code, detail = await asyncio.to_thread(self._resolve_user_sync, scope)
            if user is None:
                await self._send_json(send, status_code, {"detail": detail})
                return
            token = _current_mcp_user.set(user)
            started = False

            async def tracked_send(message: dict) -> None:
                nonlocal started
                if message.get("type") == "http.response.start":
                    started = True
                await send(message)

            try:
                await self.manager.handle_request(scope, receive, tracked_send)
            except Exception:
                # Never let an SDK/transport explosion surface as a bare ASGI
                # crash; if the response has not started, answer with a clean
                # 500 (once streaming started, the only safe exit is this).
                logger.exception(f"mcp-stream: request handling failed for path {MCP_STREAM_PATH}")
                if not started:
                    await self._send_json(send, 500, {"detail": "MCP endpoint internal error."})
            finally:
                _current_mcp_user.reset(token)
            return
        await self.app(scope, receive, send)

    def _resolve_user_sync(self, scope: dict) -> tuple[User | None, int, str]:
        db: Session = SessionLocal()
        try:
            user = _resolve_scoped_user(Request(scope), db)
            # The eekey path COMMITs (last_used_at bump), which EXPIRES the
            # user instance; once we close the session below, any lazy
            # attribute access would raise "not bound to a Session".
            # Materialize all columns now and detach cleanly.
            db.refresh(user)
            db.expunge(user)
            return user, 0, ""
        except HTTPException as exc:
            return None, exc.status_code, str(exc.detail)
        except Exception:
            logger.exception("mcp-stream: auth resolution failed")
            return None, 500, "MCP endpoint internal error."
        finally:
            db.close()

    @staticmethod
    async def _send_json(send: Any, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [[b"content-type", b"application/json"], [b"content-length", str(len(body)).encode()]],
        })
        await send({"type": "http.response.body", "body": body})
