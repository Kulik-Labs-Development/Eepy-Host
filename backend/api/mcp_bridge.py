"""Generic MCP sidecar bridge ("MCP container runtime").

Lets admin-approved templates be served by EXTERNAL MCP servers (from upstream
GitHub repos) instead of per-integration code in this backend. A template row
carries a ``runtime_config`` (image or command + env mapping) and this module:

1. Spawns a short-lived, per-user sidecar (subprocess or Docker container)
   with the user's DECRYPTED credentials injected as environment variables.
   Plaintext credentials exist only in the in-process env of the sidecar
   spawn and the live stdio/http stream -- never written to disk or logs.
   HTTP sidecars may additionally carry per-request headers (runtime_config
   ``headers``, with ``{{ENV_VAR}}`` placeholders resolved from the sidecar's
   env) so an upstream server that gates on a bearer token and/or expects the
   caller's credential as a per-request header (the Portainer MCP server)
   works without storing that secret in runtime_config or the DB. The bridge
   mints fresh random values for each runtime_config ``generated_secrets``
   env var on every spawn (e.g. the per-sidecar gate token).
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
   docker      - run ``image`` as a Docker sidecar (requires the Docker socket
                  + python ``docker`` package). By default (EEPY_MCP_SIDECAR_
                  NETWORK set, as in compose) the sidecar is attached to the
                  backend's own docker network and dialed directly by
                  container IP — no host port published. Without that variable
                  it falls back to publishing on 127.0.0.1 and dialing via
                  EEPY_MCP_DOCKER_HOST (only reliable when the backend runs
                  on the host itself).

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
import re
import secrets
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
# Preferred dialing mode for docker sidecars: the docker network the backend
# is also attached to (compose sets `eepy-sidecars`). When set, a sidecar is
# attached to this network and dialed DIRECTLY by container IP — no host port
# is published at all, so a sidecar (which holds the user's decrypted
# credentials) is unreachable from the host/LAN, and the dial has no
# loopback/host-gateway NAT hop. That hop is what broke production: a port
# published on 127.0.0.1 is NOT reachable via host.docker.internal from a
# sibling container (Linux DNAT scoping), so every handshake failed.
SIDECAR_NETWORK = os.getenv("EEPY_MCP_SIDECAR_NETWORK", "").strip()
# Legacy dial address, only used when SIDECAR_NETWORK is unset. Default
# 127.0.0.1 is correct when the backend runs ON the host (local dev with the
# socket); a containerized backend needs the host-gateway route, so compose
# sets EEPY_MCP_DOCKER_HOST=host.docker.internal.
DOCKER_HOST_URL = os.getenv("EEPY_MCP_DOCKER_HOST", "127.0.0.1")
IDLE_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_IDLE_TIMEOUT", "300"))
STARTUP_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_STARTUP_TIMEOUT", "60"))
CALL_TIMEOUT_S = float(os.getenv("EEPY_MCP_INSTANCE_CALL_TIMEOUT", "60"))
REAPER_INTERVAL_S = float(os.getenv("EEPY_MCP_INSTANCE_REAPER_INTERVAL", "30"))
# How long to wait (after the container reports "running") for the sidecar's
# port to actually accept TCP connections — the app inside can still be
# importing/binding. Without this probe the first MCP dial raced the bind and
# failed with a bare connection error.
SIDECAR_READY_TIMEOUT_S = float(os.getenv("EEPY_MCP_SIDECAR_READY_TIMEOUT", "30"))

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


def _credential_mapping(runtime_cfg: dict[str, Any]) -> dict[str, Any]:
    """The credential-field -> upstream-env-var map for the ACTIVE backend.

    Mirrors ``_static_env``: an upstream server may read the SAME credential
    from different env vars per transport (e.g. the Portainer MCP server
    reads ``PORTAINER_API_KEY`` under stdio but REFUSES to boot under HTTP
    with that var set — each client sends its key as a per-request header
    instead). ``subprocess_env_mapping`` replaces ``env_mapping`` for the
    subprocess backend when present; the docker backend always uses
    ``env_mapping`` (falling back to ``subprocess_env_mapping`` is NOT
    done: a docker backend that only has the subprocess map is a
    misconfiguration, and the missing sidecar env fails loudly at spawn).
    """
    if INSTANCE_BACKEND == "subprocess":
        override = runtime_cfg.get("subprocess_env_mapping")
        if isinstance(override, dict):
            return override
    return runtime_cfg.get("env_mapping") or {}


def map_env(runtime_cfg: dict[str, Any], credentials: dict[str, Any]) -> dict[str, str]:
    """Map user credential fields to the upstream server's environment variables.

    ``env_mapping``: {user-credential-field: upstream-env-var}. Unmapped
    credential fields are never passed to the sidecar. See
    ``_credential_mapping`` for the per-backend override.
    """
    mapping = _credential_mapping(runtime_cfg)
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
    # Bridge-minted per-spawn secrets: the sidecar gets a FRESH random value
    # in each of these env vars (e.g. the Portainer MCP server's HTTP gate
    # token, PORTAINER_MCP_AUTH_TOKEN). Never stored in runtime_config or the
    # DB, never logged (the redaction pass covers them via the env values).
    # A re-spawn after reaping mints a new value; the matching header template
    # (see _sidecar_headers) is resolved from the same env, so they stay in
    # sync by construction.
    for name in runtime_cfg.get("generated_secrets") or []:
        env[str(name)] = secrets.token_hex(32)
    return env


# {{ENV_VAR}} placeholder in a header template, where ENV_VAR is an env var
# name resolvable from the sidecar's final env (static + mapped credentials +
# generated secrets).
_HEADER_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")


def _sidecar_headers(runtime_cfg: dict[str, Any], env: dict[str, str]) -> dict[str, str]:
    """Per-request HTTP headers for an HTTP sidecar (docker/url instance).

    ``headers`` in runtime_config is {header-name: template}; each ``{{NAME}}``
    placeholder is resolved from the sidecar's FINAL env, so user credentials
    (mapped) and bridge-minted secrets (generated_secrets) can ride in
    headers WITHOUT ever being stored in runtime_config. Example (Portainer
    MCP server, HTTP mode):

        "generated_secrets": ["PORTAINER_MCP_AUTH_TOKEN"],
        "headers": {
            "Authorization": "Bearer {{PORTAINER_MCP_AUTH_TOKEN}}",
            "X-Portainer-API-Key": "{{EEPY_PORTAINER_API_KEY}}",
        }

    The subprocess backend speaks stdio (there is no HTTP request to carry
    headers on), so it always gets {} — its env may legitimately lack the
    vars the header templates reference.
    """
    if INSTANCE_BACKEND == "subprocess" and not runtime_cfg.get("url"):
        return {}
    template = runtime_cfg.get("headers") or {}
    if not isinstance(template, dict) or not template:
        return {}
    headers: dict[str, str] = {}
    for header_name, value in template.items():
        if not isinstance(value, str):
            raise BridgeError(f"Template headers[{header_name!r}] must be a string.")

        def _sub(match: re.Match[str], header_name: str = header_name) -> str:
            var = match.group(1)
            if var not in env:
                raise BridgeError(
                    f"Template headers[{header_name!r}] references env var '{var}', "
                    f"which is not set on the sidecar (static env, env_mapping, "
                    f"or generated_secrets)."
                )
            return env[var]

        headers[str(header_name)] = _HEADER_PLACEHOLDER.sub(_sub, value)
    return headers


# ---------------------------------------------------------------------------
# Instance record + registry
# ---------------------------------------------------------------------------
@dataclass
class Instance:
    key: str
    kind: str  # "subprocess" | "docker" | "url"
    template_id: str | None = None
    user_id: int | None = None  # owner of the credentials injected into this sidecar
    command: list[str] | None = None
    image: str | None = None
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    proc: subprocess.Popen | None = None
    container_id: str | None = None
    container_name: str | None = None
    stderr_tail: deque | None = None  # subprocess: bounded stderr for diagnostics
    secrets: tuple[str, ...] = ()  # credential values to redact from any surfaced sidecar output
    headers: dict[str, str] = field(default_factory=dict)  # per-request headers for HTTP sidecars (resolved)
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


def _docker_socket_path() -> str:
    """The unix socket path docker.from_env() would use (DOCKER_HOST or the
    default), for diagnostics."""
    host = os.getenv("DOCKER_HOST", "").strip()
    if host.startswith("unix://"):
        return host[len("unix://"):]
    return host or "/var/run/docker.sock"


def _docker_client():
    try:
        import docker
        import docker.errors
    except ImportError as exc:
        raise BridgeError("Docker SDK is not installed in the backend environment.") from exc
    try:
        return docker.from_env()
    except docker.errors.DockerException as exc:
        first_line = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        detail = f"Cannot reach the Docker daemon ({first_line})."
        sock = _docker_socket_path()
        if not sock.startswith(("//", "tcp://", "http://", "https://", "unix://")) and not os.path.exists(sock):
            # The classic Portainer case: the stack's backend service was
            # created from an older compose without the socket bind mount, so
            # no sidecar can EVER spawn from this container.
            detail += (
                f" The socket file {sock} does not exist inside the eepy-backend container: "
                "the stack must mount the host Docker socket on the BACKEND service "
                "(deploy/docker-compose.yml: volumes: - /var/run/docker.sock:/var/run/docker.sock). "
                "In Portainer: edit the stack, paste the CURRENT deploy/docker-compose.yml, "
                "update & recreate the eepy-backend container, then re-run the connection test."
            )
        raise BridgeError(detail) from exc


def check_docker_daemon() -> tuple[bool, str]:
    """Boot-time probe (see main.py lifespan): when the instance backend is
    docker, verify the daemon is reachable BEFORE any user hits a tool.

    Without this, a missing socket mount only surfaced on the user's first
    'Run live test' click as an opaque 502. Returns (ok, detail); detail
    carries remediation steps when ok is False.
    """
    if INSTANCE_BACKEND != "docker":
        return True, f"instance backend is '{INSTANCE_BACKEND}' - no Docker daemon needed"
    try:
        client = _docker_client()
        client.ping()
        return True, "reachable (sidecar backend ready)"
    except BridgeError as e:
        return False, str(e)
    except Exception as e:
        first = str(e).splitlines()[0] if str(e) else e.__class__.__name__
        return False, f"unexpected probe failure: {e.__class__.__name__}: {first}"


def _resolve_node_id() -> str:
    """Stable identity of THIS backend deployment, recorded on mcp_sidecars
    rows so the boot orphan sweep can tell "leftover from the previous
    incarnation of this same deployment" (force-remove: it still holds a
    user's decrypted credentials in its env) from "a sibling replica that
    may still be serving live users" (never touch).

    1. ``EEPY_NODE_ID`` env, when set (the orchestrator guarantees uniqueness
       per backend process).
    2. This process's own docker container name, discovered through the
       mounted socket: stable across restarts and Portainer redeploys of the
       same service, and distinct per replica in a multi-replica stack.
       Without this, every Portainer redeploy minted a fresh uuid and the
       sweep treated the previous boot's running sidecars as foreign,
       leaving them (and their decrypted credentials) alive forever.
    3. Random uuid (bare-host dev without a usable daemon): every boot looks
       new, so the sweep only reconciles dead foreign sidecars — the safe
       default.
    """
    override = os.getenv("EEPY_NODE_ID", "").strip()
    if override:
        return override
    try:
        import socket
        client = _docker_client()
        own = client.containers.get(socket.gethostname())
        own.reload()
        attrs = own.attrs or {}
        # "Name" is top-level in the inspect JSON ("/eepy-backend"); older
        # API versions nest it under Config.
        name = attrs.get("Name") or (attrs.get("Config") or {}).get("Name") or ""
        if name:
            return "docker:" + name.lstrip("/")
    except Exception:
        pass
    return uuid.uuid4().hex


NODE_ID: str = _resolve_node_id()


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
                          user_id: int | None = None,
                          headers: dict[str, str] | None = None) -> Instance:
    """Spawn a sidecar. ALL blocking work (exec, Docker API, image pulls,
    readiness waits) runs in a worker thread via asyncio.to_thread so the
    event loop is never stalled by a spawn — a first-time docker pull can
    take minutes.

    ``headers`` are the resolved per-request HTTP headers for an HTTP sidecar
    (see _sidecar_headers); stored on the Instance and attached to the
    streamable-HTTP client in open_session. Ignored by the subprocess backend
    (stdio has no HTTP).
    """
    cfg = _runtime_config(template)
    headers = headers or {}

    if cfg.get("url"):
        # Fixed upstream endpoint (no per-user env possible) -- rare, e.g. for
        # discovery probing of public servers.
        endpoint = str(cfg.get("endpoint") or "/mcp")
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        inst = Instance(key=key, kind="url", url=str(cfg["url"]).rstrip("/") + endpoint,
                        headers=headers, ephemeral=ephemeral)
        _REGISTRY[key] = inst
        logger.info(f"mcp-bridge: registered url instance {template.id} key={key[:12]}")
        return inst

    if INSTANCE_BACKEND == "docker" or (cfg.get("image") and not cfg.get("command")):
        return await asyncio.to_thread(_spawn_docker, template, key, env, ephemeral, user_id, headers)

    if not (isinstance(cfg.get("command"), list) and cfg["command"]):
        raise BridgeError("Template runtime_config is missing 'command'.")
    return await asyncio.to_thread(_spawn_subprocess, template, key, env, ephemeral, user_id)


def _spawn_subprocess(template: MCPTemplate, key: str, env: dict[str, str],
                      ephemeral: bool, user_id: int | None = None) -> Instance:
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
    inst = Instance(key=key, kind="subprocess", template_id=template.id, user_id=user_id,
                    command=command, env=env, cwd=cwd, proc=proc, stderr_tail=stderr_tail,
                    secrets=tuple(v for v in env.values() if len(v) >= 8), ephemeral=ephemeral)
    _REGISTRY[key] = inst
    logger.info(f"mcp-bridge: spawned subprocess sidecar for {template.id} key={key[:12]} pid={proc.pid}")
    return inst


def _drain_stderr(proc: subprocess.Popen, tail: deque) -> None:
    assert proc.stderr is not None
    for line in iter(proc.stderr.readline, b""):
        tail.append(line.decode("utf-8", "replace").rstrip()[:500])


def _spawn_error_bridge(exc: Exception, image: str, network: str | None) -> BridgeError:
    """Turn a raw docker-SDK exception from spawn/pull into an operator-facing
    BridgeError. Kept as a pure classifier (no logging/raising here) so the
    message mapping is unit-testable without a daemon."""
    msg = str(exc).lower()
    first_line = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    if "unauthorized" in msg or "authentication required" in msg:
        # GHCR packages default to PRIVATE: the host daemon's anonymous
        # (or stale) pull is rejected. The backend pulls THROUGH the host
        # daemon (mounted socket), so the fix is on the HOST.
        return BridgeError(
            f"Cannot pull sidecar image '{image}': registry access denied "
            f"({first_line}). This image is a private registry package and the "
            "Docker daemon on the host has no valid credentials for it. Fix "
            "either way: (a) make the package public — GitHub → the org that owns "
            "the image → Packages → the eepy-host-* packages → Change visibility → "
            "Public (safe here: all images are built from public repos and carry no "
            "secrets); or (b) ON THE HOST run `docker logout ghcr.io` then "
            "`docker login ghcr.io` with an org-member username and a personal "
            "access token that has the read:packages scope."
        )
    if "not found" in msg and "pull access" in msg:
        return BridgeError(f"Cannot pull sidecar image '{image}' (private registry?).")
    if network and "network" in msg and ("is not found" in msg or "invalid reference" in msg):
        return BridgeError(
            f"Docker network '{network}' not found. The backend and its "
            f"sidecars must share a docker network (compose defines 'eepy-sidecars')."
        )
    # Keep the daemon's own words (first line) in the 502 detail: a bare
    # exception class name ("APIError") tells the operator nothing.
    return BridgeError(f"Failed to start sidecar container: {first_line[:400]}")


def _spawn_docker(template: MCPTemplate, key: str, env: dict[str, str],
                  ephemeral: bool, user_id: int | None = None,
                  headers: dict[str, str] | None = None) -> Instance:
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
    network = _resolve_sidecar_network(client)

    name = f"eepy-mcp-{key[:12]}"
    try:
        for c in list(client.containers.list(all=True, filters={"name": f"/{name}"})):
            c.remove(force=True)

        if not _image_present(client, image):
            logger.info(f"mcp-bridge: pulling sidecar image {image}")
            client.images.pull(image)

        run_kwargs: dict[str, Any] = {
            "image": image,
            "name": name,
            "detach": True,
            "environment": _docker_container_env(env),
            # Labels make sidecars identifiable in Portainer's container list
            # (they are SDK-spawned, so invisible to stack views) and give ops
            # a precise filter for manual cleanup.
            "labels": {
                "eepy-host.sidecar": "true",
                "eepy-host.template": str(template.id),
                "eepy-host.key": key[:12],
            },
            "auto_remove": False,
            "restart_policy": {"Name": "no"},
            **_sidecar_run_kwargs(cfg),
        }
        if network:
            # Attach to the backend's docker network and dial the container
            # directly (IP resolved below). No host port is published: the
            # sidecar — which holds the user's decrypted credentials in its
            # env — is unreachable from the host/LAN, and the dial avoids the
            # 127.0.0.1-publish + host-gateway NAT hop that refused
            # connections when the backend is itself containerized.
            run_kwargs["network"] = network
        else:
            # Legacy fallback: publish on 127.0.0.1 (loopback-only) and dial
            # via DOCKER_HOST_URL. Only reliable when the backend runs on the
            # host itself.
            run_kwargs["ports"] = {f"{port_key}/tcp": ("127.0.0.1", None)}

        logger.info(f"mcp-bridge: starting sidecar container for {template.id} key={key[:12]} image={image}")
        container = client.containers.run(**run_kwargs)
    except Exception as exc:
        logger.error(f"mcp-bridge: failed to start sidecar container for {template.id} key={key[:12]}: {exc}")
        raise _spawn_error_bridge(exc, image, network) from exc

    # Wait until running (blocking sleep is fine: this runs in a worker thread).
    deadline = time.time() + STARTUP_TIMEOUT_S
    while time.time() < deadline:
        container.reload()
        if container.status == "running":
            break
        if container.status in ("exited", "dead", "removed"):
            tail = _sidecar_log_tail(container, env)
            logger.error(f"mcp-bridge: sidecar container for {template.id} key={key[:12]} {container.status} during startup. {tail}")
            with contextlib.suppress(Exception):
                container.remove(force=True)
            raise BridgeError(
                f"MCP sidecar container {container.status} during startup."
                + (f" Sidecar logs: {tail}" if tail else " Check the sidecar image's entrypoint/dependencies.")
            )
        time.sleep(0.5)
    else:
        with contextlib.suppress(Exception):
            container.remove(force=True)
        raise BridgeError("MCP sidecar container did not become ready in time.")

    # Resolve the dial address.
    dial_host: str
    dial_port: str
    mode: str
    if network:
        container_ip = _network_ip(container, network)
        if not container_ip:
            tail = _sidecar_log_tail(container, env)
            with contextlib.suppress(Exception):
                container.remove(force=True)
            raise BridgeError(
                f"Sidecar has no IP on docker network '{network}'. "
                f"Check the network exists and the backend container is attached to it."
            )
        dial_host, dial_port, mode = container_ip, port_key, f"network={network}"
    else:
        try:
            container.reload()
            ports = (container.attrs or {}).get("NetworkSettings", {}).get("Ports") or {}
            info = ports.get(f"{port_key}/tcp") or []
            host_port = info[0].get("HostPort") if info else None
        except Exception:
            host_port = None
        if not host_port:
            with contextlib.suppress(Exception):
                container.remove(force=True)
            raise BridgeError(
                "Sidecar exposes no mapped port. Add a 'port' to runtime_config that the "
                "image actually exposes, or set EEPY_MCP_SIDECAR_NETWORK (recommended)."
            )
        dial_host, dial_port, mode = DOCKER_HOST_URL, host_port, f"port={host_port}"

    dial_url = f"http://{dial_host}:{dial_port}{endpoint}"

    # "running" only means the entrypoint started; the app inside may still be
    # importing/binding. Probe the port until it accepts connections so the
    # first MCP handshake does not race the bind (the old failure mode: one
    # bare connection error, sidecar killed, 502 — retry "fixed" it). The
    # legacy port-publish dial probes at HTTP level: a forwarding layer
    # (Docker Desktop VM) accepts TCP before the app binds, so a TCP connect
    # alone would declare readiness too early (see _wait_port_ready).
    ready, why = _wait_port_ready(dial_host, int(dial_port), container,
                                  http_probe=(not network))
    if not ready:
        tail = _sidecar_log_tail(container, env)
        logger.error(f"mcp-bridge: sidecar for {template.id} key={key[:12]} never became reachable: {why}. {tail}")
        with contextlib.suppress(Exception):
            container.remove(force=True)
        raise BridgeError(
            f"MCP sidecar did not become reachable ({why})."
            + (f" Sidecar logs: {tail}" if tail else "")
        )

    inst = Instance(key=key, kind="docker", template_id=template.id, user_id=user_id, image=image,
                    container_id=container.id, container_name=name, url=dial_url, env=env,
                    secrets=tuple(v for v in env.values() if len(v) >= 8), headers=headers or {},
                    ephemeral=ephemeral)
    _REGISTRY[key] = inst
    if not ephemeral and user_id is not None:
        _track_sidecar(user_id, template.id, inst)  # fail-soft: DB record for the boot sweep
    logger.info(f"mcp-bridge: started sidecar container for {template.id} key={key[:12]} {mode} dial={dial_url}")
    return inst


def _resolve_sidecar_network(client: Any) -> str | None:
    """Resolve the configured EEPY_MCP_SIDECAR_NETWORK to the daemon's actual
    network name (or None when unset).

    Compose/Portainer prefix network names with the project/stack name (e.g.
    `deploy_eepy-sidecars` or `<stackname>_eepy-sidecars`), while the env var
    carries the short name from docker-compose.yml. The backend container is
    itself attached to the sidecars network, so resolve by matching its own
    attached networks: exact name first, then a `<prefix>_<name>` suffix.
    Falls back to the configured value unchanged (a bare setup whose network
    really is named eepy-sidecars, or a misconfig — which then fails at
    container run with the daemon's clear "network not found" error).
    """
    if not SIDECAR_NETWORK:
        return None
    try:
        import socket
        own = client.containers.get(socket.gethostname())
        own.reload()
        nets = list(((own.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {})
        for n in nets:
            if n == SIDECAR_NETWORK:
                return n
        for n in nets:
            if n.endswith("_" + SIDECAR_NETWORK):
                return n
    except Exception:
        pass
    return SIDECAR_NETWORK


def _network_ip(container: Any, network: str) -> str | None:
    """The container's IPv4 on ``network`` (None if detached/missing)."""
    try:
        container.reload()
        nets = ((container.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {}
        return (nets.get(network) or {}).get("IPAddress") or None
    except Exception:
        return None


def _wait_port_ready(host: str, port: int, container: Any,
                     http_probe: bool = False) -> tuple[bool, str]:
    """Poll the sidecar's port until the APP is actually serving (or the
    container dies / the deadline passes). Runs in a worker thread.

    ``http_probe`` (legacy port-publish dial only): a bare TCP connect is
    NOT a reliable readiness signal when the port is published through a
    forwarding layer (Docker Desktop's Mac/Windows VM forwarder accepts the
    TCP connection BEFORE the app inside the container has bound its socket —
    the first MCP handshake then raced the bind and died with a ReadError).
    An HTTP-level probe fixes that: the forwarder passes the request through
    only once the app's HTTP stack is bound, so ANY response (200/404/405/
    421 alike) proves readiness, while a reset/timeout means "not yet".
    The network dial (container IP, production path) has no forwarder, so a
    plain TCP connect there is accurate and stays the default.
    """
    import socket as _socket

    deadline = time.time() + SIDECAR_READY_TIMEOUT_S
    last_err = "unknown"
    while time.time() < deadline:
        try:
            if http_probe:
                import httpx

                httpx.get(f"http://{host}:{port}/", timeout=3)
                return True, ""
            with _socket.create_connection((host, port), timeout=3):
                return True, ""
        except Exception as exc:
            last_err = exc.__class__.__name__
        try:
            container.reload()
            if container.status in ("exited", "dead", "removed"):
                return False, f"container {container.status} during startup"
        except Exception:
            return False, "container gone during startup"
        time.sleep(0.5)
    return False, f"port {port} never became ready in {int(SIDECAR_READY_TIMEOUT_S)}s (last: {last_err})"


def _redact_secrets(text: str, env: dict[str, str]) -> str:
    """Strip the user's credential values (and other long env values) out of
    sidecar output before it reaches logs/errors. Sidecars may echo their env
    on startup; the debug console is superuser-visible, so be strict."""
    for v in env.values():
        if v and len(v) >= 8:
            text = text.replace(v, "[redacted]")
    return text


def _sidecar_log_tail(container: Any, env: dict[str, str], lines: int = 25, cap: int = 800) -> str:
    """Bounded, redacted tail of a docker sidecar's output (for failure
    diagnostics). Returns '' if nothing is readable."""
    try:
        raw = container.logs(tail=lines, timestamps=False)
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            return ""
        return _redact_secrets(text, env)[-cap:]
    except Exception:
        return ""


def _docker_log_tail(inst: Instance) -> str:
    """Redacted log tail for a live (about-to-be-killed) docker sidecar, or
    '' when the container is already gone."""
    if not inst.container_id:
        return ""
    try:
        container = _docker_client().containers.get(inst.container_id)
        return _sidecar_log_tail(container, inst.env)
    except Exception:
        return ""


def _image_present(client: Any, image: str) -> bool:
    try:
        client.images.get(image)
        return True
    except Exception:
        return False


def _docker_container_env(env: dict[str, str]) -> dict[str, str]:
    """The env list handed to ``containers.run`` for a docker sidecar.

    The image's own ENV is the baseline — the Docker API overlays this list
    on top of it — so only the bridge's additions (static template env,
    mapped user credentials, generated secrets) cross the boundary. The
    host-allowlist vars from _sidecar_env are deliberately dropped: notably
    PATH, whose host value would OVERRIDE the image's ENV PATH and break
    entrypoints living in image-local locations (e.g. a uv venv at
    /app/.venv/bin — `exec: "mcp-portainer": executable file not found in
    $PATH`). For the subprocess backend the host allowlist is still required
    (it IS the process's whole environment).
    """
    container_env = {k: v for k, v in env.items() if k not in _MINIMAL_PROC_ENV}
    container_env["PYTHONUNBUFFERED"] = "1"
    return container_env


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


def kill_instances_for_user(user_id: int, template_id: str) -> int:
    """Tear down every live sidecar holding THIS user's credentials for a
    template. Called when the user deletes their config: a running sidecar
    still carries the user's DECRYPTED credentials in its process env, so it
    must not outlive the config (otherwise the idle reaper keeps it — and
    those credentials — up to IDLE_TIMEOUT_S longer).

    Sync on purpose (blocking Docker/proc calls): call it from a sync (thread
    pool) route or via asyncio.to_thread. Returns how many were killed.
    """
    killed = 0
    for key, inst in list(_REGISTRY.items()):
        if inst.user_id == user_id and inst.template_id == template_id:
            with contextlib.suppress(Exception):
                kill_instance(key)
            killed += 1
    if killed:
        logger.info(f"mcp-bridge: killed {killed} sidecar(s) for {template_id} (user config deleted)")
    return killed


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
    headers = _sidecar_headers(cfg, env)
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
        inst = await spawn_instance(template, key, env, user_id=user.id, headers=headers)
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
        # Sidecar died or cannot handshake: capture its own output (docker:
        # container logs BEFORE the kill removes the container; subprocess:
        # stderr tail) so the failure is diagnosable from the 502 detail AND
        # the backend debug log, then drop the sidecar so the next call
        # respawns.
        msg = str(exc) if isinstance(exc, BridgeError) else (
            f"MCP handshake with sidecar failed ({exc.__class__.__name__}).")
        if inst.kind == "docker":
            docker_tail = await asyncio.to_thread(_docker_log_tail, inst)
            if docker_tail:
                msg += f" Sidecar logs: {docker_tail}"
        elif inst.kind == "subprocess" and inst.stderr_tail:
            tail = " | ".join(list(inst.stderr_tail)[-10:])
            if tail:
                msg += f" Sidecar stderr: {tail[:800]}"
        logger.error(
            f"mcp-bridge: {msg} [template={inst.template_id} key={inst.key[:12]} "
            f"url={inst.url} kind={inst.kind}]"
        )
        if not inst.ephemeral:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(kill_instance, inst.key)
        raise BridgeError(msg[:2000]) from exc
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
            http_client = None
            if inst.headers:
                # Per-request headers for this sidecar: e.g. the gate bearer
                # + the caller's own API-key header the Portainer MCP server
                # requires in HTTP mode, or a fixed Host override its
                # DNS-rebinding allowlist (PORTAINER_MCP_ALLOWED_HOSTS)
                # expects. The mcp SDK's streamable_http_client no longer
                # accepts a headers kwarg, so hand it a pre-configured httpx
                # client with the SDK's default timeouts (mirrors
                # mcp.shared._httpx_utils.create_mcp_http_client). httpx
                # honours an explicit Host header over the one it would
                # derive from the dial URL. The SDK does not close a
                # provided client, so it rides on the session for teardown.
                import httpx

                http_client = httpx.AsyncClient(
                    headers=inst.headers,
                    follow_redirects=True,
                    timeout=httpx.Timeout(30.0, read=300.0),
                )
            streams = await stack.enter_async_context(
                streamable_http_client(inst.url, http_client=http_client))
            sess = McpSession(kind="http", url=inst.url, _stack=stack, _client=http_client)
        session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
        await asyncio.wait_for(session.initialize(), timeout=STARTUP_TIMEOUT_S)
        sess.session = session
        return sess
    except BaseException as exc:
        # The SDK's streamable-http client runs a background anyio task group.
        # When the sidecar is dead/unreachable, the background task's error
        # (e.g. ConnectError) aborts the group: the FOREGROUND receives a
        # CancelledError("Cancelled via cancel scope") while the real cause
        # only surfaces from the context teardown (a BaseExceptionGroup /
        # cross-task cancel-scope RuntimeError). Neither is an Exception, so
        # a plain `except Exception` let them escape to the client as a 500.
        # Capture the teardown error for its detail, then convert everything
        # (except a GENUINE task cancellation) into a clean BridgeError so
        # routes 502 with a diagnostic and the failure lands in the log.
        cleanup_exc: BaseException | None = None
        try:
            await stack.aclose()
        except BaseException as cleanup_error:
            cleanup_exc = cleanup_error
        if isinstance(exc, asyncio.CancelledError):
            if "cancel scope" in str(exc):
                cause = _exc_summary(cleanup_exc) if cleanup_exc else "SDK task group aborted"
                raise BridgeError(f"MCP handshake with sidecar failed ({cause}).") from exc
            raise  # genuine cancellation (client disconnect): propagate
        if isinstance(exc, BridgeError):
            raise
        if isinstance(exc, TimeoutError):
            raise BridgeError(
                f"MCP handshake with sidecar timed out after {int(STARTUP_TIMEOUT_S)}s."
            ) from exc
        detail = _exc_summary(exc)
        if cleanup_exc is not None:
            detail = f"{detail}; teardown: {_exc_summary(cleanup_exc)}"
        raise BridgeError(f"MCP handshake with sidecar failed ({detail}).") from exc


def _exc_summary(exc: BaseException) -> str:
    """One-line, user-safe summary of an exception (flattens anyio
    BaseExceptionGroups, which nest the real cause, e.g. RemoteProtocolError)."""
    if isinstance(exc, BaseExceptionGroup):
        subs = list(dict.fromkeys(_exc_summary(e) for e in exc.exceptions))
        return "; ".join(subs)[:200]
    detail = str(exc)
    if not detail:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {detail}"[:200]

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
    headers = _sidecar_headers(cfg, env)
    probe_key = "probe-" + key_for(0, template.id, credentials)[:32]
    try:
        inst = await spawn_instance(template, probe_key, env, ephemeral=True, headers=headers)
    except BridgeError as exc:
        logger.error(f"mcp-bridge: discovery spawn failed for {template.id}: {exc}")
        raise HTTPException(status_code=502, detail=f"Sidecar spawn failed: {exc}") from exc
    try:
        sess = await open_session(inst)
    except Exception as exc:
        tail = await asyncio.to_thread(_docker_log_tail, inst) if inst.kind == "docker" else ""
        await asyncio.to_thread(kill_instance, probe_key)
        logger.error(f"mcp-bridge: discovery handshake failed for {template.id}: {exc} {tail}")
        detail = str(exc) if isinstance(exc, BridgeError) else (
            f"MCP handshake with sidecar failed ({exc.__class__.__name__}).")
        raise HTTPException(status_code=502,
                            detail=(detail + (f" Sidecar logs: {tail}" if tail else ""))[:2000]) from exc
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
