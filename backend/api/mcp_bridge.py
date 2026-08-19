"""Generic MCP sidecar bridge ("MCP container runtime").

Lets admin-approved templates be served by EXTERNAL MCP servers (from upstream
GitHub repos) instead of per-integration code in this backend. A template row
carries a ``runtime_config`` (image or command + env mapping) and this module:

1. Spawns a short-lived, per-user sidecar (subprocess or Docker container)
   with the user's DECRYPTED credentials injected as environment variables.
   Plaintext credentials exist only in the in-process env of the sidecar
   spawn and the live stdio/http stream -- never written to disk or logs.
2. Speaks standard MCP (initialize / tools/list / tools/call) to it.
3. Reaps idle sidecars after ``EEPY_MCP_INSTANCE_IDLE_TIMEOUT`` seconds.

The sidecar lifecycle is local to one backend node. That is intentional:
the control plane (templates, encrypted credentials, tool keys) lives in the
shared PostgreSQL, so any backend node can serve any user -- a sidecar is
simply (re)spawned on the node that receives the request.

Instance backends (``EEPY_MCP_INSTANCE_BACKEND``):
  subprocess  - spawn ``command`` locally (requires the MCP SDK + deps
                installed in this backend's environment). Default.
  docker      - run ``image`` as a Docker sidecar bound to 127.0.0.1 on an
                ephemeral host port (requires the Docker socket + python
                ``docker`` package).

Every function that takes credentials keeps them in memory only.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import User
from models.mcp_models import MCPTemplate
from utils.logging_setup import logger

# ---------------------------------------------------------------------------
# Tunables (env-overridable)
# ---------------------------------------------------------------------------
INSTANCE_BACKEND = os.getenv("EEPY_MCP_INSTANCE_BACKEND", "subprocess").lower()
IDLE_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_IDLE_TIMEOUT", "300"))
STARTUP_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_STARTUP_TIMEOUT", "60"))
CALL_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_CALL_TIMEOUT", "60"))
REAPER_INTERVAL_S = float(os.getenv("EEPY_MCP_INSTANCE_REAPER_INTERVAL", "30"))

# Environment that a sidecar subprocess may inherit. Deliberately minimal:
# the backend's own secrets (SECRET_KEY, DATABASE_URL, MCP_ENCRYPTION_KEY,
# ...) must NOT leak into third-party integration processes. Only the vars
# listed here plus the template's static env + the user's mapped credentials
# are visible to the sidecar.
_MINIMAL_PROC_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "PYTHONUNBUFFERED")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class BridgeError(Exception):
    """Operational failure in sidecar spawn/communication (message is user-safe)."""


# ---------------------------------------------------------------------------
# runtime_config helpers
# ---------------------------------------------------------------------------
def _runtime_config(template: MCPTemplate) -> dict[str, Any]:
    cfg = template.runtime_config or {}
    if not isinstance(cfg, dict):
        raise BridgeError("Template runtime_config is malformed.")
    if INSTANCE_BACKEND == "docker" or cfg.get("image"):
        if not cfg.get("image"):
            raise BridgeError("Template runtime_config is missing 'image'.")
    elif not (isinstance(cfg.get("command"), list) and cfg["command"]):
        raise BridgeError("Template runtime_config is missing 'command'.")
    return cfg


def key_for(user_id: int, template_id: str, credentials: dict[str, Any]) -> str:
    """Stable identity for a (user, template, exact-credentials) sidecar."""
    raw = f"{user_id}|{template_id}|"
    for k in sorted(credentials):
        raw += f"{k}={credentials[k]};"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def map_env(runtime_cfg: dict[str, Any], credentials: dict[str, Any]) -> dict[str, str]:
    """Map user credential fields to the upstream server's environment variables.

    ``env_mapping``: {user-credential-field: upstream-env-var}. Unmapped
    credential fields are never passed to the sidecar.
    """
    mapping = runtime_cfg.get("env_mapping") or {}
    if not isinstance(mapping, dict):
        raise BridgeError("Template env_mapping is malformed.")
    env: dict[str, str] = {}
    for field_name, env_var in mapping.items():
        if field_name in credentials and credentials[field_name] is not None:
            env[str(env_var)] = str(credentials[field_name])
    return env


def _sidecar_env(runtime_cfg: dict[str, Any], mapped: dict[str, str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for k in _MINIMAL_PROC_ENV:
        if os.environ.get(k):
            env[k] = os.environ[k]
    env["PYTHONUNBUFFERED"] = "1"
    static = runtime_cfg.get("env") or {}
    if isinstance(static, dict):
        for k, v in static.items():
            env[str(k)] = str(v)
    env.update(mapped)  # user credentials override static values
    return env


# ---------------------------------------------------------------------------
# Instance record + registry
# ---------------------------------------------------------------------------
@dataclass
class Instance:
    key: str
    kind: str  # "subprocess" | "docker" | "url"
    command: list[str] | None = None
    image: str | None = None
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    proc: subprocess.Popen | None = None
    container_id: str | None = None
    ephemeral: bool = False
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


_REGISTRY: dict[str, Instance] = {}
_REGISTRY_LOCK = asyncio.Lock()
_reaper_task: asyncio.Task | None = None


def _docker_client():
    try:
        import docker
        import docker.errors
    except ImportError as exc:
        raise BridgeError("Docker SDK is not installed in the backend environment.") from exc
    try:
        return docker.from_env()
    except docker.errors.DockerException as exc:
        raise BridgeError("Cannot reach the Docker daemon.") from exc


def _proc_alive(inst: Instance) -> bool:
    if inst.kind == "subprocess":
        if inst.proc is None:
            return False
        return inst.proc.poll() is None
    if inst.kind == "docker":
        if not inst.container_id:
            return False
        try:
            c = _docker_client().containers.get(inst.container_id)
            return c.status == "running"
        except Exception:
            return False
    return True  # "url" instances are externally managed


async def spawn_instance(template: MCPTemplate, key: str,
                          env: dict[str, str],
                          ephemeral: bool = False) -> Instance:
    cfg = _runtime_config(template)

    if cfg.get("url"):
        # Fixed upstream endpoint (no per-user env possible) -- rare, e.g. for
        # discovery probing of public servers.
        endpoint = str(cfg.get("endpoint") or "/mcp")
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        inst = Instance(key=key, kind="url", url=str(cfg["url"]).rstrip("/") + endpoint,
                        ephemeral=ephemeral)
        _REGISTRY[key] = inst
        logger.info(f"mcp-bridge: registered url instance {template.id} key={key[:12]}")
        return inst

    if INSTANCE_BACKEND == "docker" or (cfg.get("image") and not cfg.get("command")):
        return await _spawn_docker(template, key, env, ephemeral)

    if not (isinstance(cfg.get("command"), list) and cfg["command"]):
        raise BridgeError("Template runtime_config is missing 'command'.")
    return await _spawn_subprocess(template, key, env, ephemeral)


async def _spawn_subprocess(template: MCPTemplate, key: str, env: dict[str, str],
                            ephemeral: bool) -> Instance:
    cfg = _runtime_config(template)
    command = [str(c) for c in cfg["command"]]
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # keep the stdio channel pristine
            env=env,
        )
    except OSError as exc:
        raise BridgeError(f"Failed to start MCP server process ({exc.__class__.__name__}).") from exc
    inst = Instance(key=key, kind="subprocess", command=command, env=env, proc=proc,
                    ephemeral=ephemeral)
    _REGISTRY[key] = inst
    logger.info(f"mcp-bridge: spawned subprocess sidecar for {template.id} key={key[:12]} pid={proc.pid}")
    return inst


async def _spawn_docker(template: MCPTemplate, key: str, env: dict[str, str],
                        ephemeral: bool) -> Instance:
    cfg = _runtime_config(template)
    image = str(cfg["image"])
    port_key = str(cfg.get("port") or "8000").split("/")[0]
    endpoint = str(cfg.get("endpoint") or "/mcp")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint

    client = _docker_client()
    import docker.errors  # noqa: F401  (ensures import error was caught above)

    name = f"eepy-mcp-{key[:12]}"
    try:
        for c in list(client.containers.list(all=True, filters={"name": f"/{name}"})):
            c.remove(force=True)

        if not _image_present(client, image):
            logger.info(f"mcp-bridge: pulling sidecar image {image}")
            client.images.pull(image)

        container = client.containers.run(
            image,
            name=name,
            detach=True,
            environment=env,
            ports={f"{port_key}/tcp": ("127.0.0.1", None)},
            auto_remove=False,
            restart_policy={"Name": "no"},
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" in msg and "pull access" in msg:
            raise BridgeError(f"Cannot pull sidecar image '{image}' (private registry?).") from exc
        raise BridgeError(f"Failed to start sidecar container ({exc.__class__.__name__}).") from exc

    # Wait until running.
    deadline = time.time() + STARTUP_TIMEOUT_S
    while time.time() < deadline:
        container.reload()
        if container.status == "running":
            break
        if container.status in ("exited", "dead", "removed"):
            raise BridgeError("MCP sidecar container exited during startup.")
        await asyncio.sleep(0.5)
    else:
        with contextlib.suppress(Exception):
            container.remove(force=True)
        raise BridgeError("MCP sidecar container did not become ready in time.")

    # Resolve the ephemeral localhost port.
    host_port: str | None = None
    try:
        container.reload()
        ports = (container.attrs or {}).get("NetworkSettings", {}).get("Ports") or {}
        info = ports.get(f"{port_key}/tcp") or []
        if info:
            host_port = info[0].get("HostPort")
    except Exception:
        pass
    if not host_port:
        with contextlib.suppress(Exception):
            container.remove(force=True)
        raise BridgeError(
            "Sidecar exposes no mapped port. Add a 'port' to runtime_config that the "
            "image actually exposes, or run the image with --network host."
        )

    inst = Instance(key=key, kind="docker", image=image, container_id=container.id,
                    url=f"http://127.0.0.1:{host_port}{endpoint}", env=env, ephemeral=ephemeral)
    _REGISTRY[key] = inst
    logger.info(f"mcp-bridge: started sidecar container for {template.id} key={key[:12]} port={host_port}")
    return inst


def _image_present(client: Any, image: str) -> bool:
    try:
        client.images.get(image)
        return True
    except Exception:
        return False


def kill_instance(key: str) -> bool:
    """Tear down the sidecar for ``key`` (sync; safe to call from the reaper)."""
    inst = _REGISTRY.pop(key, None)
    if inst is None:
        return False
    if inst.kind == "subprocess" and inst.proc is not None:
        if inst.proc.poll() is None:
            inst.proc.terminate()
            try:
                inst.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                inst.proc.kill()
                with contextlib.suppress(Exception):
                    inst.proc.wait(timeout=5)
    if inst.kind == "docker" and inst.container_id:
        try:
            _docker_client().containers.get(inst.container_id).remove(force=True)
        except Exception:
            pass
    logger.info(f"mcp-bridge: reaped {inst.kind} sidecar key={key[:12]}")
    return True


def reap_idle_instances() -> int:
    now = time.time()
    victims = [k for k, i in _REGISTRY.items()
               if not i.ephemeral and (now - i.last_used) > IDLE_TIMEOUT_S]
    for k in victims:
        with contextlib.suppress(Exception):
            kill_instance(k)
    return len(victims)


async def _reaper_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(reap_idle_instances)
        except Exception:
            logger.exception("mcp-bridge: reaper pass failed")
        await asyncio.sleep(REAPER_INTERVAL_S)


def ensure_reaper_started() -> None:
    """Start the idle-sidecar reaper task once (call at app startup)."""
    global _reaper_task
    if _reaper_task is None or _reaper_task.done():
        with contextlib.suppress(RuntimeError):
            _reaper_task = asyncio.get_running_loop().create_task(_reaper_loop())


def shutdown_all_instances() -> None:
    for key in list(_REGISTRY.keys()):
        with contextlib.suppress(Exception):
            kill_instance(key)


# ---------------------------------------------------------------------------
# Acquire (spawn-or-reuse) + call helper
# ---------------------------------------------------------------------------
async def acquire_instance(user: User, template: MCPTemplate,
                           credentials: dict[str, Any]) -> Instance:
    cfg = _runtime_config(template)
    if template.runtime != "mcp-server":
        raise BridgeError(f"Template '{template.id}' does not use the MCP server runtime.")
    env = _sidecar_env(cfg, map_env(cfg, credentials))
    key = key_for(user.id, template.id, credentials)

    async with _REGISTRY_LOCK:
        existing = _REGISTRY.get(key)
        if existing is not None:
            if not existing.ephemeral and _proc_alive(existing):
                existing.last_used = time.time()
                return existing
            with contextlib.suppress(Exception):
                kill_instance(key)
        inst = await spawn_instance(template, key, env)
        inst.last_used = time.time()
        return inst


def _touch(inst: Instance) -> None:
    if not inst.ephemeral:
        inst.last_used = time.time()


async def bridge_call(user: User, template: MCPTemplate, credentials: dict[str, Any],
                      tool_name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
    """One proxy/test call: acquire sidecar -> open session -> tools/call -> close.

    The sidecar itself stays in the registry for reuse (idle-reaped later); the
    MCP session is short-lived per call. Returns (data, is_error).
    """
    inst = await acquire_instance(user, template, credentials)
    try:
        sess = await open_session(inst)
    except Exception as exc:
        # Sidecar died or cannot handshake: drop it so the next call respawns.
        if not inst.ephemeral:
            with contextlib.suppress(Exception):
                kill_instance(inst.key)
        raise BridgeError(f"MCP handshake with sidecar failed ({exc.__class__.__name__}).") from exc
    try:
        try:
            data, is_error = await call_tool(sess.session, tool_name, arguments)
        except Exception as exc:
            # MCP protocol error from the server (e.g. unknown tool). The
            # message is part of the protocol, not a user secret - safe to pass
            # through. Surface as a BridgeError so the route can 502 cleanly.
            raise BridgeError(f"Tool call rejected by upstream server: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            await sess.close()
    _touch(inst)
    return data, is_error


# ---------------------------------------------------------------------------
# MCP session wrapper (one short-lived session per call)
# ---------------------------------------------------------------------------
@dataclass
class McpSession:
    kind: str
    command: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    _stack: Any = field(default=None, repr=False)
    _client: Any = field(default=None, repr=False)
    session: Any = field(default=None, repr=False)

    async def close(self) -> None:
        if self.session is not None:
            with contextlib.suppress(Exception):
                await self.session.close()
        if self._stack is not None:
            with contextlib.suppress(Exception):
                await self._stack.aclose()
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()


async def open_session(inst: Instance) -> McpSession:
    """Open a fresh MCP session (initialize) against a running sidecar."""
    from contextlib import AsyncExitStack

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    stack = AsyncExitStack()
    try:
        if inst.kind == "subprocess":
            assert inst.command and inst.env
            params = StdioServerParameters(
                command=inst.command[0],
                args=inst.command[1:],
                env=inst.env,
            )
            streams = await stack.enter_async_context(stdio_client(params))
            sess = McpSession(kind="subprocess", command=inst.command, env=inst.env,
                              _stack=stack)
        else:
            assert inst.url
            streams = await stack.enter_async_context(streamable_http_client(inst.url))
            sess = McpSession(kind="http", url=inst.url, _stack=stack)
        session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
        await asyncio.wait_for(session.initialize(), timeout=STARTUP_TIMEOUT_S)
        sess.session = session
        return sess
    except Exception:
        with contextlib.suppress(Exception):
            await stack.aclose()
        raise

async def list_tools(session: Any) -> list[dict[str, Any]]:
    out = await session.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.inputSchema if isinstance(getattr(t, "inputSchema", None), dict) else {},
        }
        for t in out.tools
    ]


async def call_tool(session: Any, tool_name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
    """Returns (data, is_error). ``data`` is the joined text of the result."""
    res = await asyncio.wait_for(session.call_tool(tool_name, arguments or {}),
                                 timeout=CALL_TIMEOUT_S)
    parts: list[str] = []
    for block in res.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
        else:
            dump = getattr(block, "model_dump", None)
            parts.append(str(dump() if callable(dump) else block))
    data = "\n".join(parts) if parts else None
    return data, bool(res.isError)


async def discover_tools_for_template(db: Session, user: User, template: MCPTemplate,
                                      credentials: dict[str, Any]) -> list[dict[str, Any]]:
    """Spawn an ephemeral sidecar, run tools/list, tear the sidecar down.

    The caller stores the result on the template row. Raises HTTPException(502)
    when discovery fails so the superuser sees a clean message; the previous
    (possibly stale) tool list stays in the DB.
    """
    cfg = _runtime_config(template)
    env = _sidecar_env(cfg, map_env(cfg, credentials))
    probe_key = "probe-" + key_for(0, template.id, credentials)[:32]
    try:
        inst = await spawn_instance(template, probe_key, env, ephemeral=True)
    except BridgeError as exc:
        raise HTTPException(status_code=502, detail=f"Sidecar spawn failed: {exc}") from exc
    try:
        sess = await open_session(inst)
    except Exception as exc:
        kill_instance(probe_key)
        raise HTTPException(status_code=502,
                            detail=f"MCP handshake with sidecar failed ({exc.__class__.__name__}).") from exc
    try:
        tools = await list_tools(sess.session)
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"tools/list failed ({exc.__class__.__name__}).") from exc
    finally:
        with contextlib.suppress(Exception):
            await sess.close()
        kill_instance(probe_key)
    if not tools:
        raise HTTPException(status_code=502, detail="Sidecar reported zero tools.")
    return tools
