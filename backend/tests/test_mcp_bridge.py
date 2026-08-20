"""End-to-end tests for the modular MCP sidecar bridge.

A fake stdio MCP server (tests/fake_mcp_server.py, pure stdlib) stands in for
an upstream GitHub repo's MCP server. The tests exercise the real path:
user registers encrypted credentials -> proxy spawns/reuses the per-user
sidecar with env-mapped credentials -> MCP tools/call -> result relayed back,
plus connection test, discovery, OpenAPI spec generation, eekey auth, and the
idle reaper.
"""

import os
import sys

import pytest

FAKE_CREDS = {"FAKE_DOMAIN_FIELD": "fake.example.com", "FAKE_API_KEY": "fake-key-123", "FAKE_AUTH_CODE": "fake-token-456"}


@pytest.fixture(scope="module")
def fake_template_id():
    """Register a fake mcp-server template directly in the DB."""
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    template_id = "fake-mcp-test"
    fake_path = os.path.join(os.path.dirname(__file__), "fake_mcp_server.py")
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="Fake MCP Test",
            description="Test-only template served by the fake stdio MCP server.",
            config_schema={
                "category": "Test",
                "type": "object",
                "properties": {
                    "FAKE_DOMAIN_FIELD": {"type": "string", "label": "Domain", "required": True},
                    "FAKE_API_KEY": {"type": "password", "label": "API Key", "required": True},
                    "FAKE_AUTH_CODE": {"type": "password", "label": "Auth Code", "required": True},
                },
                "required": ["FAKE_DOMAIN_FIELD", "FAKE_API_KEY", "FAKE_AUTH_CODE"],
            },
            runtime="mcp-server",
            runtime_config={
                "command": [sys.executable, fake_path],
                "env": {"PYTHONUNBUFFERED": "1"},
                "env_mapping": {
                    "FAKE_DOMAIN_FIELD": "FAKE_DOMAIN",
                    "FAKE_API_KEY": "FAKE_API_KEY",
                    "FAKE_AUTH_CODE": "FAKE_API_TOKEN",
                },
                "test_tool": {"name": "list_items", "arguments": {"limit": 1}},
            },
            approved_by_admin=True,
            enabled_global=True,
        )
        db.add(t)
        db.commit()
    finally:
        db.close()
    return template_id


@pytest.fixture(scope="module")
def auth_user(client, fake_template_id):
    """A superuser account with the fake template connected (JWT + tool key)."""
    import random

    from database import SessionLocal, User, UserRole

    username = f"bridgetest{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "bridge-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "bridge-password-1"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # Promote to superuser for the discovery tests.
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        u.role = UserRole.SUPERUSER
        db.commit()
    finally:
        db.close()

    r = client.post("/api/mcp/config/register",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"template_id": fake_template_id, "credentials_json": FAKE_CREDS})
    assert r.status_code == 200, r.text

    r = client.post("/api/mcp/api-keys",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": "bridge-test"})
    assert r.status_code == 200, r.text
    eekey = r.json()["key"]

    yield {"token": token, "eekey": eekey, "username": username}

    # Cleanup: kill any leftover sidecars.
    from api import mcp_bridge
    mcp_bridge.shutdown_all_instances()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_proxy_read_tool_maps_credentials(client, auth_user, fake_template_id):
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/list_items",
                    headers=_h(auth_user["token"]), json={"limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool"] == "list_items"
    assert body["is_error"] is False
    data = body["data"]
    # env_mapping must have delivered the user's (decrypted) credentials to the sidecar.
    assert "api=fake-key-123" in data
    assert "token=fake-token-456" in data
    assert "items=item-1,item-2" in data


def test_proxy_write_tool(client, auth_user, fake_template_id):
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/create_item",
                    headers=_h(auth_user["token"]), json={"name": "widget-9000"})
    assert r.status_code == 200, r.text
    assert "created: widget-9000" in r.json()["data"]


def test_proxy_tool_error_is_reported_not_swallowed(client, auth_user, fake_template_id):
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/bad_item",
                    headers=_h(auth_user["token"]), json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_error"] is True
    assert "Error 500" in body["data"]


def test_proxy_unknown_tool(client, auth_user, fake_template_id):
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/nope",
                    headers=_h(auth_user["token"]), json={})
    assert r.status_code == 502, r.text
    assert "rejected" in r.json()["detail"]


def test_proxy_requires_active_connection(client, fake_template_id):
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/list_items",
                    headers={"Authorization": "Bearer not-a-real-jwt"}, json={})
    assert r.status_code == 401


def test_connection_test_endpoint(client, auth_user, fake_template_id):
    r = client.post(f"/api/mcp/config/{fake_template_id}/test",
                    headers=_h(auth_user["token"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


def test_discovery_populates_tools(client, auth_user, fake_template_id):
    r = client.post(f"/superuser/mcp/templates/{fake_template_id}/discover",
                    headers=_h(auth_user["token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool_count"] == 4
    assert set(body["tools"]) == {"list_items", "create_item", "bad_item", "check_env"}

    # Discovery sidecar must have been torn down.
    from api import mcp_bridge
    probe_keys = [k for k in mcp_bridge._REGISTRY if k.startswith("probe-")]
    assert probe_keys == []


def test_openapi_spec_includes_discovered_tools(client, fake_template_id):
    r = client.get("/api/mcp/openapi.json")
    assert r.status_code == 200, r.text
    spec = r.json()
    op = spec["paths"][f"/{fake_template_id}/create_item"]["post"]
    props = op["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "name" in props
    assert op["requestBody"]["content"]["application/json"]["schema"]["required"] == ["name"]
    assert f"/{fake_template_id}/list_items" in spec["paths"]


def test_tool_key_works_on_proxy(client, auth_user, fake_template_id):
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/list_items",
                    headers=_h(auth_user["eekey"]), json={"limit": 1})
    assert r.status_code == 200, r.text
    assert "api=fake-key-123" in r.json()["data"]


def test_sidecar_env_is_minimal_no_backend_secret_leak(client, auth_user, fake_template_id):
    """The sidecar must only see PATH-ish vars, template static env, and the
    mapped user credentials - never the backend's own secrets."""
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/check_env",
                    headers=_h(auth_user["token"]), json={})
    assert r.status_code == 200, r.text
    env_keys = set(r.json()["data"].split())
    assert "FAKE_API_KEY" in env_keys
    assert "FAKE_DOMAIN" in env_keys
    for secret in ("SECRET_KEY", "DATABASE_URL", "MCP_ENCRYPTION_KEY", "POSTGRES_PASSWORD"):
        assert secret not in env_keys


def test_idle_reaper_kills_and_proxy_respawns(client, auth_user, fake_template_id):
    from api import mcp_bridge

    # Make a call so at least one sidecar is live.
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/list_items",
                    headers=_h(auth_user["token"]), json={"limit": 1})
    assert r.status_code == 200, r.text
    live = [k for k, i in mcp_bridge._REGISTRY.items() if not i.ephemeral]
    assert live, "expected a live sidecar after a proxy call"

    old_timeout = mcp_bridge.IDLE_TIMEOUT_S
    try:
        mcp_bridge.IDLE_TIMEOUT_S = 0.0
        reaped = mcp_bridge.reap_idle_instances()
    finally:
        mcp_bridge.IDLE_TIMEOUT_S = old_timeout
    assert reaped >= len(live)
    assert [k for k, i in mcp_bridge._REGISTRY.items() if not i.ephemeral] == []

    # Next call must transparently respawn a fresh sidecar and still work.
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/list_items",
                    headers=_h(auth_user["token"]), json={"limit": 1})
    assert r.status_code == 200, r.text
    assert "api=fake-key-123" in r.json()["data"]


def test_sidecar_tracking_and_orphan_sweep(client, fake_template_id):
    """Durable sidecar tracking (mcp_sidecars): spawn-time track -> row present;
    teardown untrack -> row gone; boot sweep -> leftover container force-removed
    and table cleared. The key must never contain credential material."""
    import unittest.mock

    from api import mcp_bridge
    from database import SessionLocal
    from models.mcp_models import MCPSidecar

    user_id = 1  # arbitrary: SQLite does not enforce FKs without a pragma
    key = mcp_bridge.key_for(user_id, fake_template_id, FAKE_CREDS)
    # The key must NOT contain any credential material.
    assert "fake-key-123" not in key and "fake-token-456" not in key

    def _rows() -> list:
        db = SessionLocal()
        try:
            return db.query(MCPSidecar).all()
        finally:
            db.close()

    inst = mcp_bridge.Instance(key=key, kind="docker", template_id=fake_template_id,
                               image="ghcr.io/test/sidecar:latest",
                               container_id="cid-123", container_name="eepy-mcp-abc")

    # --- track: a long-lived docker instance is recorded ---
    mcp_bridge._track_sidecar(user_id, fake_template_id, inst)
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].owner_id == user_id
    assert rows[0].template_id == fake_template_id
    assert rows[0].container_id == "cid-123"

    # Ephemeral instances (discovery probes) are never tracked.
    ep = mcp_bridge.Instance(key=key + "|ep", kind="docker", template_id=fake_template_id,
                             container_id="cid-ep", ephemeral=True)
    mcp_bridge._track_sidecar(user_id, fake_template_id, ep)
    assert len(_rows()) == 1

    # --- untrack: teardown removes the row ---
    mcp_bridge._untrack_sidecar(key)
    assert len(_rows()) == 0

    # --- boot sweep: rows left by a "crashed" backend are reconciled against
    # the (fake) daemon: container force-removed, row deleted. ---
    mcp_bridge._track_sidecar(user_id, fake_template_id, inst)
    removed: list = []

    class _SweepClient:
        class _Containers:
            @staticmethod
            def get(cid):
                if cid != "cid-123":
                    raise Exception("no such container")

                class _C:
                    def remove(self, force=False):
                        removed.append(force)
                return _C()

        def __init__(self):
            self.containers = self._Containers()

    with unittest.mock.patch.object(mcp_bridge, "_docker_client", return_value=_SweepClient()):
        mcp_bridge.sweep_orphan_sidecars()

    assert removed == [True], "sweep must force-remove the leftover container"
    assert len(_rows()) == 0, "sweep must clear the tracking table"

    # An empty table is a no-op and must not raise.
    with unittest.mock.patch.object(mcp_bridge, "_docker_client", return_value=_SweepClient()):
        mcp_bridge.sweep_orphan_sidecars()
    assert len(removed) == 1  # nothing extra removed
