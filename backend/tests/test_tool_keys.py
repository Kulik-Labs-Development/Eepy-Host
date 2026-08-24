"""Tool API Key lifecycle: add (never replace), list (no plaintext),
password-gated re-view (reveal), soft revoke vs hard delete."""

import hashlib
import random

import pytest

PASSWORD = "keylifecycle-1"


def _mk_user(client, prefix: str) -> tuple[str, str]:
    """Sign up + log in a fresh user; returns (username, jwt)."""
    username = f"{prefix}{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return username, r.json()["access_token"]


@pytest.fixture()
def key_user(client, fake_template_id):
    """A user with an active integration config (required before key creation)."""
    username, token = _mk_user(client, "keylc")
    r = client.post("/api/mcp/config/register",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"template_id": fake_template_id,
                          "credentials_json": {"FAKE_DOMAIN_FIELD": "fake.example.com",
                                               "FAKE_API_KEY": "fake-key-123",
                                               "FAKE_AUTH_CODE": "fake-token-456"}})
    assert r.status_code == 200, r.text
    yield {"username": username, "token": token, "template": fake_template_id}
    from api import mcp_bridge
    mcp_bridge.shutdown_all_instances()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_key(client, token: str, name: str = "test key") -> dict:
    r = client.post("/api/mcp/api-keys", headers=_auth(token), json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def test_created_key_returned_once_and_stored_encrypted(client, key_user):
    from database import SessionLocal
    from models.mcp_models import MCPUserToolKey

    created = _create_key(client, key_user["token"])
    assert created["key"].startswith("eekey_")
    assert created["is_active"] is True

    # The list endpoint never carries plaintext.
    r = client.get("/api/mcp/api-keys", headers=_auth(key_user["token"]))
    assert r.status_code == 200
    listed = [k for k in r.json() if k["id"] == created["id"]]
    assert len(listed) == 1
    assert "key" not in listed[0]
    assert listed[0]["key_prefix"] == created["key"][:8]
    assert listed[0]["can_reveal"] is True

    # At rest: hash drives auth, Fernet copy enables re-view. Never plaintext.
    db = SessionLocal()
    try:
        row = db.query(MCPUserToolKey).filter(MCPUserToolKey.id == created["id"]).first()
        assert row is not None
        assert row.key_hash == hashlib.sha256(created["key"].encode("utf-8")).hexdigest()
        assert row.key_encrypted
        assert created["key"] not in row.key_encrypted
    finally:
        db.close()


def test_adding_a_second_key_does_not_revoke_the_first(client, key_user):
    first = _create_key(client, key_user["token"], name="first")
    second = _create_key(client, key_user["token"], name="second")
    r = client.get("/api/mcp/api-keys", headers=_auth(key_user["token"]))
    states = {k["id"]: k["is_active"] for k in r.json()}
    assert states[first["id"]] is True
    assert states[second["id"]] is True


def test_reveal_requires_password_and_returns_key(client, key_user):
    created = _create_key(client, key_user["token"])

    r = client.post(f"/api/mcp/api-keys/{created['id']}/reveal",
                    headers=_auth(key_user["token"]), json={"password": "wrong-password-1"})
    assert r.status_code == 401

    r = client.post(f"/api/mcp/api-keys/{created['id']}/reveal",
                    headers=_auth(key_user["token"]), json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["key"] == created["key"]


def test_reveal_other_users_key_is_forbidden(client, key_user, fake_template_id):
    other_username, other_token = _mk_user(client, "keylc-other")
    r = client.post("/api/mcp/config/register",
                    headers=_auth(other_token),
                    json={"template_id": fake_template_id,
                          "credentials_json": {"FAKE_DOMAIN_FIELD": "fake.example.com",
                                               "FAKE_API_KEY": "fake-key-123",
                                               "FAKE_AUTH_CODE": "fake-token-456"}})
    assert r.status_code == 200, r.text

    created = _create_key(client, key_user["token"])
    # Even with the correct password for their OWN account, another user's
    # key id is not theirs to reveal.
    r = client.post(f"/api/mcp/api-keys/{created['id']}/reveal",
                    headers=_auth(other_token), json={"password": PASSWORD})
    assert r.status_code == 404


def test_reveal_legacy_key_without_encrypted_copy_410(client, key_user):
    from database import SessionLocal
    from models.mcp_models import MCPUserToolKey

    created = _create_key(client, key_user["token"])
    db = SessionLocal()
    try:
        row = db.query(MCPUserToolKey).filter(MCPUserToolKey.id == created["id"]).first()
        row.key_encrypted = None  # simulate a pre-feature row
        db.commit()
    finally:
        db.close()

    r = client.post(f"/api/mcp/api-keys/{created['id']}/reveal",
                    headers=_auth(key_user["token"]), json={"password": PASSWORD})
    assert r.status_code == 410


def test_soft_revoke_keeps_entry_hard_delete_removes_it(client, key_user):
    created = _create_key(client, key_user["token"])

    # Soft revoke (default): entry stays, key stops working.
    r = client.delete(f"/api/mcp/api-keys/{created['id']}", headers=_auth(key_user["token"]))
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"
    r = client.get("/api/mcp/api-keys", headers=_auth(key_user["token"]))
    entry = [k for k in r.json() if k["id"] == created["id"]]
    assert len(entry) == 1
    assert entry[0]["is_active"] is False

    # A revoked key no longer authenticates the proxy.
    r = client.post(f"/api/mcp/proxy/{key_user['template']}/list_items",
                    headers=_auth(created["key"]), json={"limit": 1})
    assert r.status_code == 401

    # Hard delete: the entry is gone for good.
    r = client.delete(f"/api/mcp/api-keys/{created['id']}?hard=true", headers=_auth(key_user["token"]))
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    r = client.get("/api/mcp/api-keys", headers=_auth(key_user["token"]))
    assert all(k["id"] != created["id"] for k in r.json())
