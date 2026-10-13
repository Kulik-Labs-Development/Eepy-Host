"""Superuser system usage: CPU / RAM / network for the platform containers
and every user's spawned MCP sidecars.

Data source = the SUPERUSER'S OWN Portainer connection (the same credentials
the Portainer MCP template uses: PORTAINER_URL + PORTAINER_API_KEY). The
endpoint lists the environment's containers, then takes a one-shot Docker
stats sample per relevant container (stream=false - the daemon double-
samples, so the CPU delta is valid). Network bandwidth on the page = the
delta between two client polls (the page refreshes every 10s).

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
from utils.crypto import decrypt_credentials

STATS_TIMEOUT_SECONDS = 15
STATS_WORKERS = 8
EEPY_NAME_PREFIX = "eepy-"


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


def fetch_usage(db: Session, user, environment_id: int | None) -> dict:
    """The /superuser/system-usage payload (see the module docstring)."""
    cfg = _portainer_config(db, user.id)
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    try:
        with httpx.Client(base_url=cfg["base"], headers=headers,
                          verify=cfg["verify"], timeout=STATS_TIMEOUT_SECONDS) as client:
            # Environments: doubles as the token sanity check and feeds the
            # page's selector when the tenancy has more than one.
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
            if environment_id is None:
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
                environment_id = environments[0]["id"]
            env = next((e for e in environments if e["id"] == environment_id),
                       {"id": environment_id, "name": f"environment {environment_id}"})

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

    def row(c: dict) -> dict:
        stats = stats_by_id.get(c["id"])
        return {
            "name": c["name"],
            "id": c["id"],
            "state": c["state"],
            "status": c["status"],
            "created": c["created"],
            "cpu_percent": compute_cpu_percent(stats) if stats else None,
            "ram": compute_memory(stats) if stats else None,
            "net": compute_network(stats) if stats else None,
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
