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
                 installed in this backend's environment). The SDK speaks to
                 sidecars over STDIO, so the upstream server must run in stdio
                 mode: set ``subprocess_env`` in runtime_config when the
                 docker-oriented ``env`` selects an HTTP transport (e.g.
                 MCP_TRANSPORT=stdio vs streamable-http). No ports are bound,
                 so there is nothing to reach except the pipes.
  docker      - run ``image`` as a Docker sidecar bound to 127.0.0.1 on an
                 ephemeral host port (requires the Docker socket + python
                 ``docker`` package).

Sidecar containment: docker sidecars run with CPU/memory limits (env-tunable,
see ``_sidecar_run_kwargs``) and may drop to a non-root user via the
optional runtime_config ``user`` field.

Every function that takes credentials keeps them in memory only.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import User
from models.mcp_models import MCPSidecar, MCPTemplate
from utils.logging_setup import logger

# ---------------------------------------------------------------------------
# Tunables (env-overridable)
# ---------------------------------------------------------------------------
INSTANCE_BACKEND = os.getenv("EEPY_MCP_INSTANCE_BACKEND", "subprocess").lower()
# Address the backend uses to REACH docker sidecars' loopback-bound host
# ports. Default 127.0.0.1 is correct when the backend runs on the host
# (local dev with the socket). When the backend is itself containerized
# (compose/Portainer), dialing the host's loopback requires the host-gateway
# route, so compose sets EEPY_MCP_DOCKER_HOST=host.docker.internal.
DOCKER_HOST_URL = os.getenv("EEPY_MCP_DOCKER_HOST", "127.0.0.1")
IDLE_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_IDLE_TIMEOUT", "300"))
STARTUP_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_STARTUP_TIMEOUT", "60"))
CALL_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_CALL_TIMEOUT", "60"))
REAPER_INTERVAL_S = float(os.getenv("EEPY_MCP_INSTANCE_REAPER_INTERVAL", "30"))

# Identity of THIS backend process, recorded on mcp_sidecars rows so the boot
# orphan sweep only force-removes sidecars IT left behind (not sidecars a
# sibling backend replica on the same host is still serving). Set
# EEPY_NODE_ID only if your orchestrator already guarantees a unique id per
# backend process; otherwise each process gets a unique uuid.
NODE_ID: str = os.getenv("EEPY_NODE_ID") or uuid.uuid4().hex

# Sidecar resource containment. A sidecar runs third-party code holding a
# user's decrypted credentials in its env, so bound its CPU/memory by default.
# Override via env to match the host's budget (docker mem_limit syntax).
SIDECAR_MEM_LIMIT = os.getenv("EEPY_MCP_SIDECAR_MEM_LIMIT", "512m")
SIDECAR_CPU_LIMIT = float(os.getenv("EEPY_MCP_SIDECAR_CPU_LIMIT", "1.0"))

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


def _static_env(runtime_cfg: dict[str, Any]) -> dict[str, Any]:
    """Template static env for the ACTIVE instance backend.

    The two backends need different upstream transports for the same server:
    docker serves it over streamable-HTTP (``env``), while the subprocess
    backend speaks stdio through the SDK. When ``subprocess_env`` is present
    it replaces ``env`` for the subprocess backend, so a single template row
    can configure both backends correctly (e.g. MCP_TRANSPORT=stdio vs
    streamable-http). Without it the subprocess backend falls back to ``env``.
    """
    if INSTANCE_BACKEND == "subprocess":
        override = runtime_cfg.get("subprocess_env")
        if isinstance(override, dict):
            return override
    return runtime_cfg.get("env") or {}


def _sidecar_env(runtime_cfg: dict[str, Any], mapped: dict[str, str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for k in _MINIMAL_PROC_ENV:
        if os.environ.get(k):
            env[k] = os.environ[k]
    env["PYTHONUNBUFFERED"] = "1"
    static = _static_env(runtime_cfg)
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
    template_id: str | None = None
    command: list[str] | None = None
    image: str | None = None
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    proc: subprocess.Popen | None = None
    container_id: str | None = None
    container_name: str | None = None
    stderr_tail: deque | None = None  # subprocess: bounded stderr for diagnostics
    ephemeral: bool = False
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


_REGISTRY: dict[str, Instance] = {}
# Per-key locks: two requests for the SAME sidecar key must not double-spawn,
# but different keys (different users/templates/credentials) must be able to
# spawn CONCURRENTLY. A single global lock held across a spawn would serialize
# every user's first call behind one docker image pull (minutes). The lock
# table is tiny and bounded by users x templates x credential generations.
_KEY_LOCKS: dict[str, asyncio.Lock] = {}


def _key_lock(key: str) -> asyncio.Lock:
    lock = _KEY_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _KEY_LOCKS[key] = lock
    return lock


# ---------------------------------------------------------------------------
# Durable sidecar tracking (mcp_sidecars table)
#
# The _REGISTRY above is in-memory and dies with the process. The table is
# what survives restarts so the boot sweep (sweep_orphan_sidecars) can tell
# "still-running container I own" from "orphan from a crashed backend". It
# stores the (secret-free) bridge key and container identifiers only — never
# credentials or the sidecar env.
# ---------------------------------------------------------------------------
def _track_sidecar(user_id: int, template_id: str, inst: Instance) -> None:
    """Persist (or update) the mcp_sidecars row for a long-lived sidecar.

    Fail-soft: tracking is an ops convenience, a DB hiccup must not break a
    working tool call.
    """
    if inst.ephemeral or inst.kind != "docker" or not inst.container_id:
        return
    from database import SessionLocal
    db = SessionLocal()
    try:
        row = db.get(MCPSidecar, inst.key)
        if row is None:
            row = MCPSidecar(key=inst.key)
            db.add(row)
        row.owner_id = int(user_id)
        row.template_id = template_id
        row.kind = inst.kind
        row.container_id = inst.container_id
        row.image = inst.image
        row.name = inst.container_name
        row.node_id = NODE_ID
        row.last_used_at = _utcnow()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("mcp-bridge: failed to track sidecar in DB")
    finally:
        db.close()


def _untrack_sidecar(key: str) -> None:
    """Remove the mcp_sidecars row when its sidecar is torn down (fail-soft)."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        row = db.get(MCPSidecar, key)
        if row is not None:
            db.delete(row)
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("mcp-bridge: failed to untrack sidecar in DB")
    finally:
        db.close()


def _utcnow():
    from datetime import UTC, datetime
    return datetime.now(UTC)  # same UTC convention as the rest of the models


def sweep_orphan_sidecars() -> None:
    """Boot-time reconciliation of the mcp_sidecars table against the daemon.

    Called once at startup (see main.py lifespan). This process has NO
    in-memory handle to any previously-spawned sidecar, so:

    - rows recorded by THIS node (node_id == NODE_ID, or NULL from before
      node tracking existed) are definitive leftovers holding a user's
      decrypted credentials in their env: force-remove the container and
      delete the row (next request re-spawns a fresh sidecar).
    - rows recorded by ANOTHER node (a sibling backend replica on the same
      host/daemon) may still be serving live users: never touch a container
      that is running. Only reconcile stale rows whose container is already
      gone or dead (delete the row, clean up the dead container if present).

    Covers OOM-killed backends, docker kill -9, host reboots, daemon
    restarts, and Portainer "Remove" actions that skip the graceful hook.
    Fail-soft per row; the reaper + _spawn_docker's stale-name cleanup are
    the safety net for anything the sweep misses.

    Topology note: this is single-host by design — sidecars dial out through
    EEPY_MCP_DOCKER_HOST (this host's loopback/host-gateway), so a sidecar
    spawned on another host would be unreachable anyway.
    """
    from database import SessionLocal
    db = SessionLocal()
    try:
        rows = db.query(MCPSidecar).all()
    except Exception:
        db.close()
        logger.exception("mcp-bridge: orphan sweep could not read mcp_sidecars")
        return
    client = None
    try:
        client = _docker_client()
    except BridgeError:
        # Subprocess backend / no daemon: nothing to reconcile on the daemon.
        # Our own rows are still definitive leftovers; foreign rows are left
        # for the owning node to reconcile.
        logger.info("mcp-bridge: orphan sweep - docker backend unavailable")

    def _container_state(cid: str) -> str:
        """'running' | 'dead' | 'gone' (or 'unknown' without a daemon)."""
        if client is None or not cid:
            return "unknown"
        try:
            return client.containers.get(cid).status
        except Exception:
            return "gone"

    for row in rows:
        try:
            if row.node_id is not None and row.node_id != NODE_ID:
                # Another node's sidecar. Only reconcile if its container is
                # not running on the shared daemon (exited/dead/gone -> stale
                # row). Never touch a running foreign container.
                # (NULL node_id rows are from before node tracking: treated
                # as ours. Only risk is a rolling upgrade where a sibling
                # replica still runs pre-upgrade code — worst case one of its
                # live sidecars is killed, which the next request respawns.)
                state = _container_state(row.container_id)
                if state == "running" or state == "unknown":
                    continue
                with contextlib.suppress(Exception):
                    client.containers.get(row.container_id).remove(force=True)
                db.delete(row)
                db.commit()
                logger.info(f"mcp-bridge: sweep reconciled stale foreign row key={row.key[:16]}... (container {state})")
                continue

            # Our own leftover: force-remove + delete row.
            if row.container_id:
                with contextlib.suppress(Exception):
                    client.containers.get(row.container_id).remove(force=True)
                    logger.info(f"mcp-bridge: swept leftover sidecar {row.name or str(row.container_id)[:12]} key={row.key[:16]}...")
            db.delete(row)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(f"mcp-bridge: orphan sweep failed for key={row.key[:16]}")
    db.close()


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
                          ephemeral: bool = False,
                          user_id: int | None = None) -> Instance:
    """Spawn a sidecar. ALL blocking work (exec, Docker API, image pulls,
    readiness waits) runs in a worker thread via asyncio.to_thread so the
    event loop is never stalled by a spawn — a first-time docker pull can
    take minutes.
    """
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
        return await asyncio.to_thread(_spawn_docker, template, key, env, ephemeral, user_id)

    if not (isinstance(cfg.get("command"), list) and cfg["command"]):
        raise BridgeError("Template runtime_config is missing 'command'.")
    return await asyncio.to_thread(_spawn_subprocess, template, key, env, ephemeral)


def _spawn_subprocess(template: MCPTemplate, key: str, env: dict[str, str],
                      ephemeral: bool) -> Instance:
    cfg = _runtime_config(template)
    command = [str(c) for c in cfg["command"]]
    # Optional working directory: relative paths resolve against the repo root
    # (backend/api -> parents[2]). Lets the subprocess backend run integration
    # code that lives in this repo (e.g. the integrations/happyfox-mcp
    # submodule); the docker backend remains the production path. Relative
    # command args are resolved to ABSOLUTE paths here, because the SDK's
    # stdio_client (used per call in open_session) cannot take a cwd — the
    # command must work from any cwd the backend process happens to have.
    cwd: str | None = None
    if cfg.get("cwd"):
        from pathlib import Path
        p = Path(str(cfg["cwd"]))
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        cwd = str(p)
        command = [str(c) for c in command]
        # Resolve only tokens that LOOK like relative paths (./ or ../);
        # a bare first token like "python" is an interpreter resolved via PATH.
        command = [c if os.path.isabs(c) or not (c.startswith("./") or c.startswith("../"))
                   else str(p / c) for c in command]
    # Put the backend's interpreter first on PATH so a bare "python" command
    # resolves to it (the sidecar's deps, e.g. mcp SDK + requests, are then
    # importable) while still honoring the minimal allowlist env.
    import sys as _sys
    env = dict(env)
    env["PATH"] = f"{os.path.dirname(_sys.executable)}{os.pathsep}{env.get('PATH', '')}"
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  # captured (bounded) for failure diagnostics
            env=env,
            cwd=cwd,
        )
    except OSError as exc:
        raise BridgeError(f"Failed to start MCP server process ({exc.__class__.__name__}).") from exc
    # Keep only the tail of the sidecar's stderr (a daemon thread drains the
    # pipe so the server never blocks on a full buffer). Surfaced in the
    # BridgeError when the MCP handshake fails — a sidecar that prints its
    # own env would self-expose only to the owner of those credentials, and
    # nothing is persisted.
    stderr_tail: deque = deque(maxlen=50)
    threading.Thread(target=_drain_stderr, args=(proc, stderr_tail), daemon=True).start()
    inst = Instance(key=key, kind="subprocess", command=command, env=env, cwd=cwd,
                    proc=proc, stderr_tail=stderr_tail, ephemeral=ephemeral)
    _REGISTRY[key] = inst
    logger.info(f"mcp-bridge: spawned subprocess sidecar for {template.id} key={key[:12]} pid={proc.pid}")
    return inst


def _drain_stderr(proc: subprocess.Popen, tail: deque) -> None:
    assert proc.stderr is not None
    for line in iter(proc.stderr.readline, b""):
        tail.append(line.decode("utf-8", "replace").rstrip()[:500])


def _spawn_docker(template: MCPTemplate, key: str, env: dict[str, str],
                  ephemeral: bool, user_id: int | None = None) -> Instance:
    # Runs in a worker thread (see spawn_instance): every call here — daemon
    # list/pull/run/reload — is a blocking Docker API call and must not touch
    # the event loop.
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

        # Bind to 127.0.0.1 on the host: the sidecar's port stays
        # loopback-only so a buggy sidecar (holding a user's decrypted
        # credentials) can't be reached from the LAN. The backend reaches it
        # via DOCKER_HOST_URL: directly on the host, or via the host-gateway
        # route when the backend is itself containerized (compose).
        # Labels make sidecars identifiable in Portainer's container list
        # (they are SDK-spawned, so invisible to stack views) and give ops
        # a precise filter for manual cleanup.
        container = client.containers.run(
            image,
            name=name,
            detach=True,
            environment=env,
            ports={f"{port_key}/tcp": ("127.0.0.1", None)},
            labels={
                "eepy-host.sidecar": "true",
                "eepy-host.template": str(template.id),
                "eepy-host.key": key[:12],
            },
            auto_remove=False,
            restart_policy={"Name": "no"},
            **_sidecar_run_kwargs(cfg),
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" in msg and "pull access" in msg:
            raise BridgeError(f"Cannot pull sidecar image '{image}' (private registry?).") from exc
        raise BridgeError(f"Failed to start sidecar container ({exc.__class__.__name__}).") from exc

    # Wait until running (blocking sleep is fine: this runs in a worker thread).
    deadline = time.time() + STARTUP_TIMEOUT_S
    while time.time() < deadline:
        container.reload()
        if container.status == "running":
            break
        if container.status in ("exited", "dead", "removed"):
            raise BridgeError("MCP sidecar container exited during startup.")
        time.sleep(0.5)
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

    inst = Instance(key=key, kind="docker", template_id=template.id, image=image,
                    container_id=container.id, container_name=name,
                    url=f"http://{DOCKER_HOST_URL}:{host_port}{endpoint}", env=env, ephemeral=ephemeral)
    _REGISTRY[key] = inst
    if not ephemeral and user_id is not None:
        _track_sidecar(user_id, template.id, inst)  # fail-soft: DB record for the boot sweep
    logger.info(f"mcp-bridge: started sidecar container for {template.id} key={key[:12]} port={host_port}")
    return inst


def _image_present(client: Any, image: str) -> bool:
    try:
        client.images.get(image)
        return True
    except Exception:
        return False


def _sidecar_run_kwargs(runtime_cfg: dict[str, Any]) -> dict[str, Any]:
    """Containment kwargs for sidecar containers.

    A sidecar runs third-party code holding a user's decrypted credentials in
    its env: bound its CPU/memory by default (env-tunable) and drop it to a
    non-root uid when the template opts in via runtime_config ``user``
    (e.g. "1000:1000" — the image must contain that uid).
    """
    kwargs: dict[str, Any] = {
        "mem_limit": str(SIDECAR_MEM_LIMIT),
        "cpu_period": 100000,
        "cpu_quota": int(SIDECAR_CPU_LIMIT * 100000),
    }
    if runtime_cfg.get("user"):
        kwargs["user"] = str(runtime_cfg["user"])
    return kwargs


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
    with contextlib.suppress(Exception):
        _untrack_sidecar(key)  # drop the durable record (no-op if absent)
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

    # Per-key lock: only same-sidecar requests serialize (prevents
    # double-spawn); other users' first calls proceed concurrently. The
    # liveness check and teardown are blocking (Docker API / proc.wait), so
    # they run in worker threads.
    async with _key_lock(key):
        existing = _REGISTRY.get(key)
        if existing is not None:
            if not existing.ephemeral and await asyncio.to_thread(_proc_alive, existing):
                existing.last_used = time.time()
                return existing
            await asyncio.to_thread(kill_instance, key)
        inst = await spawn_instance(template, key, env, user_id=user.id)
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
                await asyncio.to_thread(kill_instance, inst.key)
        msg = f"MCP handshake with sidecar failed ({exc.__class__.__name__})."
        if inst.kind == "subprocess" and inst.stderr_tail:
            tail = " | ".join(list(inst.stderr_tail)[-10:])
            if tail:
                msg += f" Sidecar stderr: {tail[:800]}"
        raise BridgeError(msg) from exc
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
                cwd=inst.cwd,
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
        await asyncio.to_thread(kill_instance, probe_key)
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
        await asyncio.to_thread(kill_instance, probe_key)
    if not tools:
        raise HTTPException(status_code=502, detail="Sidecar reported zero tools.")
    return tools
