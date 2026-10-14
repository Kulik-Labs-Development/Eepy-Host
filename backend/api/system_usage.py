"""Superuser system usage: CPU / RAM / network for the platform containers
and every user's spawned MCP sidecars.

Data source = the system_settings row (System Settings > "System data
source") FIRST - Portainer today, Arcane as the second driver behind the
same row shape - FALLBACK to the superuser's existing Portainer MCP config
(the same credentials the Portainer MCP template uses: PORTAINER_URL +
PORTAINER_API_KEY), which keeps live setups working through the transition.
The endpoint lists the environment's containers, then takes a one-shot stats
sample per relevant container (Portainer: Docker /stats stream=false - the
daemon double-samples, so the CPU delta is valid; Arcane: the ResourceSample
attached to resource-sorted container list items). Network bandwidth on the
page = the delta between two client polls (the page refreshes every 10s).

Classification:
- sidecars: exact, from the mcp_sidecars table (the spawn ledger - name,
  owner, template);
- platform: the eepy-* name prefix (the stack's own containers).
  ponytail: ceiling - a tenancy that renames its stack containers away from
  the eepy- prefix would need EEPY_NAME_PREFIX adjusted here.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.mcp_models import MCPSidecar, UserMCPConfig
from models.system_settings import SystemSettings
from utils.crypto import decrypt_credentials, decrypt_secret

STATS_TIMEOUT_SECONDS = 15
STATS_WORKERS = 8
EEPY_NAME_PREFIX = "eepy-"
# Arcane pages: at most 5 pages of 50, stop early on a short page.
ARCANE_PAGE_SIZE = 50
ARCANE_MAX_PAGES = 5


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_cpu_percent(stats: dict) -> float | None:
    """CPU% from a one-shot /stats payload (stream=false: the daemon double-
    samples, so precpu_stats is valid). None when the sample is degenerate
    (missing precpu_stats, no CPU delta, or no system-CPU delta to divide
    by)."""
    cpu_stats = stats.get("cpu_stats") or {}
    pre_stats = stats.get("precpu_stats") or {}
    if not pre_stats:
        return None  # one-shot payload without a prior sample: no valid delta
    cpu_delta = _num((cpu_stats.get("cpu_usage") or {}).get("total_usage")) - _num(
        (pre_stats.get("cpu_usage") or {}).get("total_usage"))
    system_delta = _num(cpu_stats.get("system_cpu_usage")) - _num(
        pre_stats.get("system_cpu_usage"))
    if cpu_delta <= 0 or system_delta <= 0:
        return None
    online = int(_num(cpu_stats.get("online_cpus"))) or 1
    return round(100.0 * cpu_delta / system_delta * online, 2)


def compute_memory(stats: dict) -> dict:
    """usage / working set (usage - page cache) / limit, in bytes."""
    mem = stats.get("memory_stats") or {}
    usage = int(_num(mem.get("usage")))
    cache = int(_num((mem.get("stats") or {}).get("cache")))
    return {
        "usage_bytes": usage,
        "working_set_bytes": max(usage - cache, 0) if cache else usage,
        "limit_bytes": int(_num(mem.get("limit"))),
    }


def compute_network(stats: dict) -> dict:
    """Cumulative rx/tx bytes summed across every interface."""
    rx = tx = 0
    for iface in (stats.get("networks") or {}).values():
        rx += _num(iface.get("rx_bytes"))
        tx += _num(iface.get("tx_bytes"))
    return {"rx_bytes": int(rx), "tx_bytes": int(tx)}


def classify_containers(containers: list[dict], sidecar_names: set[str]) -> tuple[list[dict], list[dict]]:
    """Split the environment's containers into (platform, sidecars). Sidecars
    are matched by exact name against the mcp_sidecars ledger; platform = the
    eepy- name prefix minus sidecars. Everything else (other stacks on the
    same host) is eepy's business not to report."""
    platform: list[dict] = []
    sidecars: list[dict] = []
    for c in containers:
        if c["name"] in sidecar_names:
            sidecars.append(c)
        elif c["name"].startswith(EEPY_NAME_PREFIX):
            platform.append(c)
    return platform, sidecars


def _portainer_config(db: Session, user_id: int) -> dict:
    cfg = (
        db.query(UserMCPConfig)
        .filter(
            UserMCPConfig.owner_id == user_id,
            UserMCPConfig.template_name == "portainer",
            UserMCPConfig.is_active.is_(True),
        )
        .first()
    )
    if cfg is None:
        raise HTTPException(
            status_code=400,
            detail="No active Portainer connection. Connect the Portainer "
                   "template first (its URL + API key are the data source "
                   "for this page).",
        )
    creds = decrypt_credentials(cfg.credentials_json)
    base = str(creds.get("PORTAINER_URL") or "").rstrip("/")
    api_key = str(creds.get("PORTAINER_API_KEY") or "")
    if not base or not api_key:
        raise HTTPException(
            status_code=400,
            detail="The Portainer connection is missing its URL or API key.",
        )
    verify = str(creds.get("PORTAINER_TLS_VERIFY", "1")) != "0"
    return {"base": base, "api_key": api_key, "verify": verify}


def _resolve_config(db: Session, user_id: int) -> dict:
    """Data source for the page: the system_settings row FIRST (the active
    backend must have a url + stored key), FALLBACK to the superuser's
    Portainer MCP config (keeps live setups working through the transition).
    Raises 400 {"error": "not_configured"} when neither is usable - the
    page renders the "open System Settings" prompt on that body."""
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    if row is not None:
        if row.backend == "arcane":
            url, key_enc = row.arcane_url, row.arcane_api_key_enc
            if url and key_enc:
                return {
                    "backend": "arcane",
                    "base": str(url).rstrip("/"),
                    "api_key": decrypt_secret(key_enc),
                    "verify": True,
                }
        elif row.portainer_url and row.portainer_api_key_enc:
            return {
                "backend": "portainer",
                "base": str(row.portainer_url).rstrip("/"),
                "api_key": decrypt_secret(row.portainer_api_key_enc),
                "verify": bool(row.portainer_tls_verify),
            }
    try:
        cfg = _portainer_config(db, user_id)
    except HTTPException:
        raise HTTPException(
            status_code=400,
            detail={"error": "not_configured",
                    "detail": "No system data source configured. Set Portainer or Arcane in System Settings."},
        ) from None
    return {**cfg, "backend": "portainer"}


def _resolve_environment(environments: list[dict], wanted: str | None) -> tuple[int, dict]:
    """Pick the target environment from the visible list. `wanted` is the
    settings row's environment_id (stringified - Portainer ints arrive
    stringified in some paths, Arcane ids are "0"/"1"); ids are compared
    stringified.

    - wanted set + present -> that env;
    - wanted None + 0 envs -> 404; None + 1 -> auto-pick; None + >1 -> 409
      (the page prompts the admin to pin one in System Settings);
    - wanted set + absent -> the old placeholder env (the admin pinned an
      env the token can no longer see: surface it, let the containers call
      fail loudly)."""
    if wanted is not None:
        env = next((e for e in environments if str(e["id"]) == str(wanted)), None)
        if env is not None:
            return int(wanted), env
        return int(wanted), {"id": int(wanted), "name": f"environment {wanted}"}
    if not environments:
        raise HTTPException(
            status_code=404,
            detail="No environments are visible to this Portainer token.",
        )
    if len(environments) > 1:
        raise HTTPException(
            status_code=409,
            detail={"error": "multiple_environments", "environments": environments},
        )
    return int(environments[0]["id"]), environments[0]


def fetch_usage(db: Session, user) -> dict:
    """The /superuser/system-usage payload (see the module docstring)."""
    cfg = _resolve_config(db, user.id)
    # The wanted environment now comes from the settings row (str or None);
    # a missing row / missing value = auto.
    row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
    wanted_env: str | None = row.environment_id if row is not None else None

    if cfg["backend"] == "portainer":
        headers = {"X-API-KEY": cfg["api_key"]}
        try:
            with httpx.Client(base_url=cfg["base"], headers=headers,
                              verify=cfg["verify"], timeout=STATS_TIMEOUT_SECONDS) as client:
                # Environments: doubles as the token sanity check.
                r = client.get("/api/endpoints")
                if r.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Portainer returned HTTP {r.status_code} on "
                               "/api/endpoints - check the URL and API key.",
                    )
                environments = [
                    {"id": e.get("Id"), "name": e.get("Name")} for e in r.json() if e.get("Id")
                ]
                environment_id, env = _resolve_environment(environments, wanted_env)

                r = client.get(
                    f"/api/endpoints/{environment_id}/docker/containers/json", params={"all": "1"})
                if r.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Portainer returned HTTP {r.status_code} listing containers "
                               f"for environment {environment_id}.",
                    )
                containers = []
                for raw in r.json():
                    name = (raw.get("Names") or [""])[0].lstrip("/")
                    if not name:
                        continue
                    containers.append({
                        "id": raw.get("Id"),
                        "name": name,
                        "state": raw.get("State"),
                        "status": raw.get("Status"),
                        "created": raw.get("Created"),
                    })
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach Portainer ({exc.__class__.__name__}).",
            ) from exc
        metrics_by_id: dict = {}  # filled after the live-set below (one-shot /stats)
    else:
        # Arcane: same httpx shape as the Portainer branch. Environments are
        # paged (at most 5 pages of 50, stop on a short page) and double as
        # the token sanity check.
        headers = {"X-Api-Key": cfg["api_key"]}
        try:
            with httpx.Client(base_url=cfg["base"], headers=headers,
                              verify=cfg["verify"], timeout=STATS_TIMEOUT_SECONDS) as client:
                environments = []
                start = 0
                for _ in range(ARCANE_MAX_PAGES):
                    r = client.get("/api/environments",
                                   params={"start": start, "limit": ARCANE_PAGE_SIZE})
                    if r.status_code != 200:
                        raise HTTPException(
                            status_code=502,
                            detail=f"Arcane returned HTTP {r.status_code} on "
                                   "/api/environments - check the URL and API key.",
                        )
                    items = (r.json().get("data") or [])
                    for e in items:
                        environments.append(
                            {"id": str(e.get("id")), "name": e.get("name") or str(e.get("id"))}
                        )
                    if len(items) < ARCANE_PAGE_SIZE:
                        break
                    start += ARCANE_PAGE_SIZE
                environment_id, env = _resolve_environment(environments, wanted_env)

                # CRITICAL: sort=cpuUsage is REQUIRED - Arcane only attaches
                # ResourceSample on resource-sorted list requests (verified
                # in its source); without it every row's cpu/ram would be
                # null. Paged like /api/environments (stop on a short page).
                containers = []
                metrics_by_id = {}
                start = 0
                for _ in range(ARCANE_MAX_PAGES):
                    r = client.get(
                        f"/api/environments/{environment_id}/containers",
                        params={"sort": "cpuUsage", "order": "asc",
                                "start": start, "limit": ARCANE_PAGE_SIZE},
                    )
                    if r.status_code != 200:
                        raise HTTPException(
                            status_code=502,
                            detail=f"Arcane returned HTTP {r.status_code} listing containers "
                                   f"for environment {environment_id}.",
                        )
                    items = (r.json().get("data") or [])
                    for c in items:
                        name = (c.get("names") or [""])[0].lstrip("/")
                        if not name:
                            continue
                        cid = c.get("id")
                        containers.append({
                            "id": cid,
                            "name": name,
                            "state": c.get("state"),
                            "status": c.get("status"),
                            "created": c.get("created"),  # int64 in their API; tolerate None
                        })
                        sample = c.get("resourceSample")
                        if sample:
                            metrics_by_id[cid] = {
                                "cpu_percent": sample.get("cpuPercent"),
                                "ram": {
                                    "usage_bytes": int(sample.get("memoryUsageBytes") or 0),
                                    "working_set_bytes": int(sample.get("memoryUsageBytes") or 0),
                                    "limit_bytes": int(sample.get("memoryLimitBytes") or 0),
                                },
                                "net": None,
                            }
                    if len(items) < ARCANE_PAGE_SIZE:
                        break
                    start += ARCANE_PAGE_SIZE
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach Arcane ({exc.__class__.__name__}).",
            ) from exc

    sidecar_rows = (
        db.query(MCPSidecar)
        .filter(MCPSidecar.name.is_not(None))
        .all()
    )
    from database import User as _User  # local import: database pulls the whole app model set
    owner_ids = {row.owner_id for row in sidecar_rows}
    users = ({u.id: u.username for u in db.query(_User).filter(_User.id.in_(owner_ids)).all()}
             if owner_ids else {})
    sidecar_meta = {
        row.name: {"owner": users.get(row.owner_id, f"user #{row.owner_id}"),
                   "template": row.template_id}
        for row in sidecar_rows
    }

    platform, live_sidecars = classify_containers(containers, set(sidecar_meta))
    live_ids = {c["id"] for c in containers if c["state"] == "running"}
    targets = [c for c in platform + live_sidecars if c["id"] in live_ids]

    if cfg["backend"] == "portainer":
        def one_sample(cid: str) -> tuple[str, dict | None]:
            try:
                with httpx.Client(base_url=cfg["base"], headers=headers,
                                  verify=cfg["verify"], timeout=STATS_TIMEOUT_SECONDS) as c:
                    r = c.get(f"/api/endpoints/{environment_id}/docker/containers/{cid}/stats",
                              params={"stream": "false"})
                if r.status_code != 200:
                    return cid, None
                return cid, r.json()
            except httpx.HTTPError:
                return cid, None

        stats_by_id: dict[str, dict] = {}
        if targets:
            with concurrent.futures.ThreadPoolExecutor(max_workers=STATS_WORKERS) as pool:
                for cid, payload in pool.map(one_sample, [t["id"] for t in targets]):
                    if payload is not None:
                        stats_by_id[cid] = payload
        # Same metrics-entry shape as the Arcane branch: the shared row()
        # below reads all three fields either way.
        metrics_by_id = {
            cid: {
                "cpu_percent": compute_cpu_percent(p),
                "ram": compute_memory(p),
                "net": compute_network(p),
            }
            for cid, p in stats_by_id.items()
        }

    def row(c: dict) -> dict:
        metrics = metrics_by_id.get(c["id"])
        return {
            "name": c["name"],
            "id": c["id"],
            "state": c["state"],
            "status": c["status"],
            "created": c["created"],
            "cpu_percent": metrics["cpu_percent"] if metrics else None,
            "ram": metrics["ram"] if metrics else None,
            "net": metrics["net"] if metrics else None,
        }

    sidecar_rows_out = [
        {**row(c), "owner": sidecar_meta[c["name"]]["owner"],
         "template": sidecar_meta[c["name"]]["template"]}
        for c in live_sidecars
    ]
    # Ledger rows with no live container (removed/stopped out from under us)
    # still show up so the admin sees the spawn history.
    live_names = {c["name"] for c in containers}
    for row_name, meta in sidecar_meta.items():
        if row_name not in live_names:
            sidecar_rows_out.append({
                "name": row_name, "id": None, "state": "gone", "status": "no live container",
                "created": None, "cpu_percent": None, "ram": None, "net": None,
                "owner": meta["owner"], "template": meta["template"],
            })

    return {
        "generated_at": time.time(),
        "environment": env,
        "environments": environments,
        "platform": [row(c) for c in platform],
        "sidecars": sidecar_rows_out,
    }
