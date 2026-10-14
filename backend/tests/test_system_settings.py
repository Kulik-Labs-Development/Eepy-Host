"""Superuser system settings: the SINGLE-ROW (id=1) system data source config
(Portainer / Arcane) behind /superuser/system-settings.

Locks: the no-row response shape (and that API keys are NEVER returned), the
encrypt-at-rest roundtrip (stored token decrypts back to the typed key), the
blank-means-keep upsert semantics, the 400s (bad backend, incomplete active
backend), the test route's missing-config 200 {"ok": false}, and the
system-usage 400 not_configured body. No network: the test route is only
exercised with nothing stored, so its httpx probe never runs.
"""

import random

import pytest

from database import SessionLocal, User, UserRole
from models.system_settings import SystemSettings
from utils.crypto import decrypt_secret


@pytest.fixture(scope="module")
def superuser_token(client):
    """A fresh superuser account (JWT) - same shape as conftest's auth_user."""
    username = f"settingstest{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "settings-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "settings-password-1"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # Promote to superuser (the endpoint enforces the role server-side).
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        u.role = UserRole.SUPERUSER
        db.commit()
    finally:
        db.close()
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _delete_row() -> None:
    """Drop the id=1 row so each test starts from a clean slate."""
    db = SessionLocal()
    try:
        db.query(SystemSettings).filter(SystemSettings.id == 1).delete()
        db.commit()
    finally:
        db.close()


def test_get_no_row_returns_unconfigured_shape(client, superuser_token):
    _delete_row()
    r = client.get("/superuser/system-settings", headers=_auth(superuser_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is False
    assert body["backend"] is None
    assert body["portainer_url"] is None
    assert body["portainer_tls_verify"] is True
    assert body["portainer_api_key_set"] is False
    assert body["arcane_url"] is None
    assert body["arcane_api_key_set"] is False
    assert body["environment_id"] is None


def test_put_roundtrip_encrypts_and_never_echoes_key(client, superuser_token):
    _delete_row()
    r = client.put("/superuser/system-settings", headers=_auth(superuser_token), json={
        "backend": "portainer",
        "portainer_url": "https://pt.example",
        "portainer_api_key": "sekrit-key",
        "environment_id": "7",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["backend"] == "portainer"
    assert body["portainer_url"] == "https://pt.example"
    assert body["portainer_api_key_set"] is True
    assert body["environment_id"] == "7"
    # The plaintext key is NOWHERE in the response (raw text, every field).
    assert "sekrit-key" not in r.text

    # Direct DB assert: the stored token decrypts back to the typed key
    # (proves the Fernet roundtrip) and the plaintext was not stored.
    db = SessionLocal()
    try:
        row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
        assert row is not None
        assert row.portainer_api_key_enc
        assert "sekrit-key" not in row.portainer_api_key_enc
        assert decrypt_secret(row.portainer_api_key_enc) == "sekrit-key"
        assert row.environment_id == "7"
        assert row.portainer_tls_verify is True
    finally:
        db.close()


def test_put_blank_keeps_stored_values(client, superuser_token):
    _delete_row()
    r = client.put("/superuser/system-settings", headers=_auth(superuser_token), json={
        "backend": "portainer",
        "portainer_url": "https://pt.example",
        "portainer_api_key": "keep-me-123",
    })
    assert r.status_code == 200, r.text

    # Blank url/key = keep the stored values.
    r = client.put("/superuser/system-settings", headers=_auth(superuser_token), json={
        "portainer_url": "",
        "portainer_api_key": "",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["portainer_url"] == "https://pt.example"
    assert body["portainer_api_key_set"] is True

    db = SessionLocal()
    try:
        row = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
        assert decrypt_secret(row.portainer_api_key_enc) == "keep-me-123"  # unchanged
    finally:
        db.close()


def test_put_invalid_backend_rejected(client, superuser_token):
    _delete_row()
    r = client.put("/superuser/system-settings", headers=_auth(superuser_token), json={
        "backend": "docker",
    })
    assert r.status_code == 400, r.text
    db = SessionLocal()
    try:
        assert db.query(SystemSettings).filter(SystemSettings.id == 1).first() is None
    finally:
        db.close()


def test_put_arcane_without_key_rejected(client, superuser_token):
    _delete_row()
    # No key anywhere (not in the payload, not stored): the active backend
    # (arcane) must end up with BOTH url and key, else 400.
    r = client.put("/superuser/system-settings", headers=_auth(superuser_token), json={
        "backend": "arcane",
        "arcane_url": "https://arc.example",
    })
    assert r.status_code == 400, r.text
    # The incomplete row must not have been persisted.
    db = SessionLocal()
    try:
        assert db.query(SystemSettings).filter(SystemSettings.id == 1).first() is None
    finally:
        db.close()


def test_test_route_no_config_reports_missing(client, superuser_token):
    _delete_row()
    # Nothing stored, nothing in the body: 200 {"ok": false} naming what is
    # missing (never a 5xx from this route, no network call made).
    r = client.post("/superuser/system-settings/test", headers=_auth(superuser_token), json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "URL" in body["detail"]
    assert "API key" in body["detail"]


def test_system_usage_not_configured_400(client, superuser_token):
    # No settings row AND no Portainer MCP config for this superuser.
    _delete_row()
    r = client.get("/superuser/system-usage", headers=_auth(superuser_token))
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error"] == "not_configured"
