"""Eepy Host -> MCP bridge for local dev tooling (e.g. opencode).

Eepy Host's public surface is an OpenAPI REST proxy, not an MCP endpoint:
  - GET  {base}/api/mcp/openapi.json          (public unified tool spec)
  - POST {base}/api/mcp/proxy/{tpl}/{tool}    (Bearer eekey_... Tool API Key)

This script is a tiny stdio MCP server (mcp SDK, FastMCP) that opencode (or any
MCP client) can spawn as a `type: local` server. At startup it fetches the
unified spec and registers one MCP tool per Eepy tool; each tools/call is a
straight POST through the Eepy proxy, which decrypts the user's stored
credentials server-side and forwards to the upstream integration.

Config (process env first, then KEY=VALUE lines in tools/.eepy_env next to
this file — the file is git-ignored and must contain the eekey_ tool key):
  EEPY_BASE_URL    e.g. https://eepy.example.com   (required)
  EEPY_TOOL_KEY    eekey_...                        (required for calls)
  EEPY_TEMPLATES   comma list to expose only some integrations (default: all)

Usage:
  python eepy_mcp_shim.py            # stdio MCP server (what opencode spawns)
  python eepy_mcp_shim.py --list     # print the tools it would register, exit
"""

import json
import keyword
import os
import re
import sys
import warnings
from pathlib import Path

import httpx

# pydantic-settings (via the mcp SDK) emits a harmless import-time warning;
# keep stdio servers' stderr clean of it. Must run before `mcp` is imported.
warnings.filterwarnings("ignore", message=".*has an incomplete definition.*")

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".eepy_env"
SPECPATH = "/api/mcp/openapi.json"
SPEC_TIMEOUT = 15.0
CALL_TIMEOUT = 240.0  # first call may spawn + pull a sidecar image
MAX_NAME = 64


def env_or_file(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return ""


def base_url() -> str:
    return env_or_file("EEPY_BASE_URL").rstrip("/")


def tool_key() -> str:
    return env_or_file("EEPY_TOOL_KEY")


def template_filter() -> set[str] | None:
    raw = env_or_file("EEPY_TEMPLATES").strip()
    if not raw:
        return None
    return {t.strip() for t in raw.split(",") if t.strip()}


def fetch_spec(base: str) -> dict:
    r = httpx.get(base + SPECPATH, timeout=SPEC_TIMEOUT)
    r.raise_for_status()
    return r.json()


def sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _ident(name: str) -> str:
    n = sanitize(name)
    if not n or n[0].isdigit() or keyword.iskeyword(n):
        n = "p_" + n
    return n


TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def _py_type(prop: dict) -> str:
    return TYPE_MAP.get(str(prop.get("type", "string")), "str")


def extract_params(operation: dict) -> list[tuple[str, str, bool, str]]:
    """Return [(original_name, py_type, required, description), ...]."""
    params: list[tuple[str, str, bool, str]] = []
    body = operation.get("requestBody") or {}
    schema = (((body.get("content") or {}).get("application/json") or {}).get("schema")) or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    for pname, prop in props.items():
        if not isinstance(prop, dict):
            prop = {"type": "string"}
        params.append((pname, _py_type(prop), pname in required, str(prop.get("description", "") or "")))
    for p in operation.get("parameters") or []:
        if (p.get("name"), _py_type(p.get("schema") or {}), p.get("required", False), "") in params:
            continue
        params.append((
            p["name"],
            _py_type(p.get("schema") or {}),
            bool(p.get("required", False)),
            str(p.get("description", "") or ""),
        ))
    return params


def _make_caller(base: str, template: str, tool: str, key: str,
                 params: list[tuple[str, str, bool, str]]):
    sig = []
    assigns = []
    for pname, ptype, req, _desc in params:
        arg = _ident(pname)
        if req:
            sig.append(f"{arg}: {ptype}")
        else:
            sig.append(f"{arg}: {ptype} | None = None")
        assigns.append(f'    payload["{pname}"] = {arg}')
    body_src = "\n".join(assigns) or "    pass"
    src = f"""
async def _eepy_tool({", ".join(sig) if sig else "**_unused"}) -> str:
    payload = {{}}
{body_src}
    return await _call_eepy(_base, _template, _tool, _key, payload)
"""
    ns: dict = {
        "_call_eepy": _call_eepy,
        "_base": base,
        "_template": template,
        "_tool": tool,
        "_key": key,
    }
    exec(compile(src, "<eepy-shim-tool>", "exec"), ns)
    fn = ns["_eepy_tool"]
    fn.__name__ = f"eepy_{template}_{tool}"
    return fn


async def _call_eepy(base: str, template: str, tool: str, key: str,
                     payload: dict) -> str:
    payload = {k: v for k, v in payload.items() if v is not None}
    url = f"{base}/api/mcp/proxy/{template}/{tool}"
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as client:
            r = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        return f"ERROR: network failure calling Eepy ({exc.__class__.__name__}: {exc}). " \
               f"Is EEPY_BASE_URL reachable?"
    try:
        body = r.json()
    except Exception:
        body = r.text
    if not isinstance(body, dict):
        return body if r.status_code == 200 else f"ERROR (HTTP {r.status_code}): {body[:4000]}"
    if r.status_code != 200 or body.get("is_error"):
        detail = body.get("detail") or body.get("data") or body
        return f"ERROR (HTTP {r.status_code}, is_error={body.get('is_error')}): " \
               f"{json.dumps(detail, default=str)[:4000]}"
    data = body.get("data")
    if isinstance(data, str):
        return data
    return json.dumps(data, default=str, indent=2)


def build_server():
    from mcp.server.fastmcp import FastMCP

    base = base_url()
    key = tool_key()
    flt = template_filter()
    tool_names: list[str] = []
    mcp = FastMCP(
        "eepy",
        instructions="Eepy Host managed integration tools. Tool names are "
                     "{template}__{tool}; calls go through the Eepy proxy "
                     "(credentials stay server-side). Results are JSON text.",
    )

    @mcp.tool()
    async def eepy_health() -> str:
        """Check Eepy Host backend reachability (GET /health)."""
        if not base:
            return "ERROR: EEPY_BASE_URL not set (env or tools/.eepy_env)."
        try:
            r = httpx.get(base + "/health", timeout=SPEC_TIMEOUT)
            return f"HTTP {r.status_code}: {r.text[:500]}"
        except httpx.HTTPError as exc:
            return f"ERROR: cannot reach {base} ({exc.__class__.__name__}: {exc})"

    warnings: list[str] = []
    if not base:
        warnings.append("EEPY_BASE_URL not set (env or tools/.eepy_env) — no tools registered.")
        return mcp, warnings, tool_names
    if not key:
        warnings.append("EEPY_TOOL_KEY (eekey_...) not set — tool calls will 401. "
                        "Create a Tool API Key in the Eepy dashboard.")

    try:
        spec = fetch_spec(base)
    except Exception as exc:
        warnings.append(f"Could not fetch {base}{SPECPATH} ({exc.__class__.__name__}: {exc}) — "
                        "no tools registered.")
        return mcp, warnings, tool_names

    names: set[str] = set()
    count = 0
    for path, methods in (spec.get("paths") or {}).items():
        m = re.fullmatch(r"/proxy/([^/]+)/([^/]+)", path)
        if not m:
            continue
        template, tool = m.group(1), m.group(2)
        if flt is not None and template not in flt:
            continue
        operation = (methods.get("post") or methods.get("get") or methods.get("put") or {})
        raw_name = f"{template}__{tool}"
        name = sanitize(raw_name)[:MAX_NAME]
        while name in names:
            name = name[:-4] + "_x"
        names.add(name)
        fn = _make_caller(base, template, tool, key, extract_params(operation))
        desc = operation.get("description") or operation.get("summary") \
            or f"Eepy tool {raw_name}"
        mcp.add_tool(fn, name=name, description=desc)
        tool_names.append(name)
        count += 1
    if count == 0:
        tag_names = sorted(t.get("name") for t in (spec.get("tags") or []) if t.get("name"))
        shown = [t for t in tag_names if flt is None or t in flt]
        warnings.append(f"Spec at {base}{SPECPATH} had no /proxy/* tools for the current "
                        f"filter (spec templates: {shown or tag_names}).")
    return mcp, warnings, tool_names


def main() -> None:
    if "--list" in sys.argv:
        _, warnings, tools = build_server()
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)
        print(f"{len(tools)} tools (base={base_url() or '(unset)'}):")
        for t in tools:
            print(f"  {t}")
        return
    mcp, warnings, _tools = build_server()
    for w in warnings:
        print(f"eepy-shim WARN: {w}", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
