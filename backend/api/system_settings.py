"""Superuser system settings: the SINGLE-ROW (id=1) system data source config.

Where the System Usage page reads its container stats from - Portainer (the
current default) or Arcane (the planned successor, same row shape).

Security: API keys are Fernet-encrypted at rest (the *_api_key_enc columns)
and are NEVER returned in any response - only the portainer_api_key_set /
arcane_api_key_set booleans (the truthiness of the stored tokens) surface.
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.system_settings import SystemSettings
from utils.crypto import decrypt_secret, encrypt_secret

TEST_TIMEOUT_SECONDS = 15
_PAGE_SIZE = 50
_MAX_PAGES = 5  # environments are few; a short page stops the loop earlier
_VALID_BACKENDS = {"portainer", "arcane"}


def _row(db: Session) -> SystemSettings | None:
    return db.query(SystemSettings).filter(SystemSettings.id == 1).first()


def get_settings(db: Session) -> dict:
    """The settings row in response shape. API keys are NEVER included -
    only the *_api_key_set booleans (truthiness of the stored tokens)."""
    row = _row(db)
    if row is None:
        return {
            "configured": False,
            "backend": None,
            "portainer_url": None,
            "portainer_api_key_set": False,
            "portainer_tls_verify": True,
            "arcane_url": None,
            "arcane_api_key_set": False,
            "environment_id": None,
        }
    return {
        "configured": True,
        "backend": row.backend,
        "portainer_url": row.portainer_url,
        "portainer_api_key_set": bool(row.portainer_api_key_enc),
        "portainer_tls_verify": bool(row.portainer_tls_verify),
        "arcane_url": row.arcane_url,
        "arcane_api_key_set": bool(row.arcane_api_key_enc),
        "environment_id": row.environment_id,
    }


def put_settings(db: Session, payload: dict) -> dict:
    """Upsert the id=1 row. Blank ("")/None url or key = KEEP the stored
    value; a non-blank key = re-encrypt (Fernet) what was typed; a non-blank
    url = store. After applying, the ACTIVE backend's url AND key (stored or
    just set) must both be non-empty, else 400 naming what is missing."""
    backend = payload.get("backend")
    if backend is not None and backend not in _VALID_BACKENDS:
        raise HTTPException(status_code=400, detail="backend must be 'portainer' or 'arcane'.")

    row = _row(db)
    if row is None:
        row = SystemSettings(id=1)
        db.add(row)

    if backend is not None:
        row.backend = backend
    active = row.backend

    # URLs: blank/None keeps the stored value; non-blank stores.
    if payload.get("portainer_url"):
        row.portainer_url = str(payload["portainer_url"])
    if payload.get("arcane_url"):
        row.arcane_url = str(payload["arcane_url"])

    # API keys: blank/None keeps the stored token; non-blank re-encrypts.
    if payload.get("portainer_api_key"):
        row.portainer_api_key_enc = encrypt_secret(str(payload["portainer_api_key"]))
    if payload.get("arcane_api_key"):
        row.arcane_api_key_enc = encrypt_secret(str(payload["arcane_api_key"]))

    # tls_verify: use the value when provided (including False); otherwise
    # keep the stored one (a fresh row defaults to True).
    tls = payload.get("portainer_tls_verify")
    if tls is not None:
        row.portainer_tls_verify = bool(tls)

    # environment_id: a value (any type) is stored as its string form;
    # blank/None = auto (NULL).
    env = payload.get("environment_id")
    row.environment_id = str(env) if env else None

    # The ACTIVE backend must be complete (stored or just set).
    url = row.portainer_url if active == "portainer" else row.arcane_url
    key_enc = row.portainer_api_key_enc if active == "portainer" else row.arcane_api_key_enc
    missing = []
    if not url:
        missing.append("URL")
    if not key_enc:
        missing.append("API key")
    if missing:
        db.rollback()  # drop the pending write (incl. a just-created row)
        label = "Portainer" if active == "portainer" else "Arcane"
        raise HTTPException(
            status_code=400,
            detail=f"The {label} connection is missing its {' and '.join(missing)}.",
        )

    db.commit()
    return get_settings(db)


def test_settings(db: Session, payload: dict) -> dict:
    """Probe a connection (form values win, else the stored row) and return
    its visible environments. This one call is BOTH the connection test AND
    the source of the environment dropdown options. Always 200 with
    {"ok": ...} - never a 5xx from this route."""
    row = _row(db)
    backend = payload.get("backend") or (row.backend if row is not None else None) or "portainer"
    label = "Portainer" if backend == "portainer" else "Arcane"

    def _stored(url_field: str, key_field: str) -> tuple[str, str]:
        if row is None:
            return "", ""
        url = str(getattr(row, url_field) or "")
        token = getattr(row, key_field)
        key = decrypt_secret(token) if token else ""
        return url, key

    base, key = _stored(
        "portainer_url", "portainer_api_key_enc"
    ) if backend == "portainer" else _stored("arcane_url", "arcane_api_key_enc")
    if payload.get(f"{backend}_url"):
        base = str(payload[f"{backend}_url"])
    if payload.get(f"{backend}_api_key"):
        key = str(payload[f"{backend}_api_key"])

    missing = []
    if not base:
        missing.append("URL")
    if not key:
        missing.append("API key")
    if missing:
        return {"ok": False, "detail": f"The {label} connection is missing its {' and '.join(missing)}."}

    # Portainer: a single /api/endpoints call. verify follows the tls_verify
    # opt-out (form value, else stored, else True) for self-signed Portainer
    # certs; Arcane always verifies.
    if backend == "portainer":
        tls = payload.get("portainer_tls_verify")
        if tls is not None:
            verify = bool(tls)
        elif row is not None and row.portainer_tls_verify is not None:
            verify = bool(row.portainer_tls_verify)
        else:
            verify = True
    else:
        verify = True

    try:
        if backend == "portainer":
            with httpx.Client(base_url=base.rstrip("/"), timeout=TEST_TIMEOUT_SECONDS, verify=verify) as client:
                r = client.get("/api/endpoints", headers={"X-API-KEY": key})
            if r.status_code != 200:
                return {
                    "ok": False,
                    "detail": f"{label} returned HTTP {r.status_code} on "
                              "/api/endpoints - check the URL and API key.",
                }
            environments = [
                {"id": e.get("Id"), "name": e.get("Name")} for e in r.json() if e.get("Id") is not None
            ]
        else:
            # Paged /api/environments: at most 5 pages of 50, stop on a short page.
            environments = []
            start = 0
            with httpx.Client(base_url=base.rstrip("/"), headers={"X-Api-Key": key},
                              timeout=TEST_TIMEOUT_SECONDS, verify=True) as client:
                for _ in range(_MAX_PAGES):
                    r = client.get("/api/environments", params={"start": start, "limit": _PAGE_SIZE})
                    if r.status_code != 200:
                        return {
                            "ok": False,
                            "detail": f"{label} returned HTTP {r.status_code} on "
                                      "/api/environments - check the URL and API key.",
                        }
                    items = (r.json().get("data") or [])
                    for e in items:
                        environments.append(
                            {"id": str(e.get("id")), "name": e.get("name") or str(e.get("id"))}
                        )
                    if len(items) < _PAGE_SIZE:
                        break
                    start += _PAGE_SIZE
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"Could not reach {label} ({exc.__class__.__name__})."}

    return {"ok": True, "environments": environments}
