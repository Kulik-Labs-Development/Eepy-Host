"""End-to-end tests for the modular MCP sidecar bridge.

A fake stdio MCP server (tests/fake_mcp_server.py, pure stdlib) stands in for
an upstream GitHub repo's MCP server. The tests exercise the real path:
user registers encrypted credentials -> proxy spawns/reuses the per-user
sidecar with env-mapped credentials -> MCP tools/call -> result relayed back,
plus connection test, discovery, OpenAPI spec generation, eekey auth, and the
idle reaper.
"""

import os
import shutil
import sys

import pytest

FAKE_CREDS = {"FAKE_DOMAIN_FIELD": "fake.example.com", "FAKE_API_KEY": "fake-key-123", "FAKE_AUTH_CODE": "fake-token-456"}


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


def test_discovery_state_listing_requires_superuser_and_tracks_state(client, auth_user, fake_template_id):
    """The superuser dashboard lists discovery state per approved template.

    A template at tool_count=0 serves name-only UNTYPED tools — the exact
    production incident where Open WebUI presented every tool as
    parameter-less and could not pass arguments upstream. The dashboard
    surfaces this state so discovery is never silently skipped.
    """
    import random

    # A plain (non-superuser) account cannot list discovery state.
    username = f"plainuser{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "plain-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "plain-password-1"})
    plain_token = r.json()["access_token"]

    r = client.get("/superuser/mcp/templates", headers={"Authorization": f"Bearer {plain_token}"})
    assert r.status_code == 403

    # Superuser: fake template present; no schemas discovered yet (this test
    # runs before the discovery tests in this file).
    r = client.get("/superuser/mcp/templates", headers=_h(auth_user["token"]))
    assert r.status_code == 200, r.text
    row = {x["id"]: x for x in r.json()}[fake_template_id]
    assert row["runtime"] == "mcp-server"
    assert row["tool_count"] == 0
    assert row["tools_discovered_at"] is None

    # After discovery the state reflects the stored schemas.
    r = client.post(f"/superuser/mcp/templates/{fake_template_id}/discover", headers=_h(auth_user["token"]))
    assert r.status_code == 200, r.text
    r = client.get("/superuser/mcp/templates", headers=_h(auth_user["token"]))
    row = {x["id"]: x for x in r.json()}[fake_template_id]
    assert row["tool_count"] == 4
    assert row["tools_discovered_at"] is not None


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


def test_discovery_stores_input_schema_and_spec_exposes_properties(client, auth_user, fake_template_id):
    """Production regression: the live spec fell back to name-only, UNTYPED
    tools because admin discovery had never stored schemas (the sidecar path
    was broken first). Open WebUI then presented every tool as
    parameter-less, the model sent {}, and the upstream server answered
    'Field required' for every tool that takes arguments.

    Discovery must store the real inputSchema, and the spec must expose
    properties + required - that is the ONLY way Open WebUI shows the model
    the fields AND passes them through (its middleware drops any model
    argument not present in the spec's properties).
    """
    r = client.post(f"/superuser/mcp/templates/{fake_template_id}/discover",
                    headers={"Authorization": f"Bearer {auth_user['token']}"})
    assert r.status_code == 200, r.text
    assert r.json()["tool_count"] == 4

    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == fake_template_id).first()
        schemas = {x["name"]: x.get("inputSchema") for x in (t.discovered_tools or [])}
    finally:
        db.close()
    create = schemas.get("create_item") or {}
    assert "name" in (create.get("properties") or {}), f"inputSchema lost in discovery: {create}"

    r = client.get("/api/mcp/openapi.json")
    op = r.json()["paths"][f"/proxy/{fake_template_id}/create_item"]["post"]
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert "name" in schema.get("properties", {}), f"spec lacks properties: {schema}"
    assert "name" in schema.get("required", []), f"spec lacks required: {schema}"


def test_openapi_spec_includes_discovered_tools(client, fake_template_id):
    r = client.get("/api/mcp/openapi.json")
    assert r.status_code == 200, r.text
    spec = r.json()
    op = spec["paths"][f"/proxy/{fake_template_id}/create_item"]["post"]
    props = op["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "name" in props
    assert op["requestBody"]["content"]["application/json"]["schema"]["required"] == ["name"]
    assert f"/proxy/{fake_template_id}/list_items" in spec["paths"]


def test_openapi_spec_paths_and_servers_compose_to_proxy_route(client, fake_template_id):
    """Open WebUI appends spec paths to the pasted base URL and ignores
    servers[].url, so BOTH compositions must yield the real proxy route:
      pasted base (.../api/mcp) + path, and servers[0].url + path."""
    r = client.get("/api/mcp/openapi.json")
    assert r.status_code == 200, r.text
    spec = r.json()
    assert spec["paths"], "expected tool paths in the unified spec"
    for path in spec["paths"]:
        assert path.startswith("/proxy/"), path
    server_url = spec["servers"][0]["url"].rstrip("/")
    assert server_url.endswith("/api/mcp")
    # Open WebUI's composition: pasted base URL (.../api/mcp) + spec path must
    # land on the real proxy route.
    target = f"/proxy/{fake_template_id}/list_items"
    assert any((server_url + p).endswith(f"/api/mcp{target}") for p in spec["paths"])


def test_proxy_alias_route_without_proxy_segment(client, auth_user, fake_template_id):
    """The exact call shape Open WebUI makes with the pre-fix spec:
    base URL (.../api/mcp) + '/{template}/{tool}', no 'proxy' segment."""
    r = client.post(f"/api/mcp/{fake_template_id}/list_items",
                    headers=_h(auth_user["token"]), json={"limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool"] == "list_items"
    assert body["is_error"] is False
    assert "api=fake-key-123" in body["data"]


def test_proxy_alias_works_with_tool_key(client, auth_user, fake_template_id):
    r = client.post(f"/api/mcp/{fake_template_id}/list_items",
                    headers=_h(auth_user["eekey"]), json={"limit": 1})
    assert r.status_code == 200, r.text
    assert "api=fake-key-123" in r.json()["data"]


def test_proxy_alias_does_not_shadow_static_routes(client, auth_user, fake_template_id):
    """The /{template_id}/{tool_name} alias must not swallow the static
    two-segment routes registered before it (/templates/list, /config/list)."""
    r = client.get("/api/mcp/templates/list", headers=_h(auth_user["token"]))
    assert r.status_code == 200, r.text
    ids = [t["id"] for t in r.json()]
    assert fake_template_id in ids

    r = client.get("/api/mcp/config/list", headers=_h(auth_user["token"]))
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

    # Unknown template via the alias degrades to the standard 404.
    r = client.post("/api/mcp/not-a-template/some_tool",
                    headers=_h(auth_user["token"]), json={})
    assert r.status_code == 404


def test_tool_key_still_rejected_on_management_routes(client, auth_user):
    """The alias path-shape must not widen eekey scope: two-segment MCP
    management routes keep rejecting tool keys."""
    r = client.get("/api/mcp/templates/list", headers=_h(auth_user["eekey"]))
    assert r.status_code == 401

    r = client.post("/api/mcp/config/register",
                    headers=_h(auth_user["eekey"]), json={})
    assert r.status_code == 401


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

    # --- boot sweep (node-aware): this node's leftovers are force-removed;
    # another node's RUNNING sidecar is left alone (it may still be serving
    # live users); another node's stale rows (container gone/dead) are
    # reconciled. The fake daemon knows three container states. ---
    def _foreign_row(key: str, container_id: str, node_id: str = "other-node") -> None:
        db = SessionLocal()
        try:
            db.add(MCPSidecar(key=key, owner_id=user_id, template_id=fake_template_id,
                              kind="docker", container_id=container_id,
                              name=f"eepy-mcp-{key[:9]}", node_id=node_id))
            db.commit()
        finally:
            db.close()

    # Row A: ours (node_id=NODE_ID via _track_sidecar) -> force-removed.
    mcp_bridge._track_sidecar(user_id, fake_template_id, inst)
    # Row A2: NULL node_id (pre-node-tracking legacy row) -> treated as ours,
    # force-removed even while running.
    _foreign_row("legacy-null-node-key", "cid-legacy", node_id=None)
    # Row B: foreign, container RUNNING -> must survive untouched.
    _foreign_row("foreign-running-key", "cid-foreign-live")
    # Row C: foreign, container gone (stale row) -> row deleted.
    _foreign_row("foreign-gone-key", "cid-gone")
    # Row D: foreign, container exited -> dead container removed + row deleted.
    _foreign_row("foreign-dead-key", "cid-dead")

    removed: list = []
    container_states = {
        "cid-123": "running",
        "cid-legacy": "running",
        "cid-foreign-live": "running",
        "cid-dead": "exited",
        # "cid-gone" absent from the daemon on purpose
    }

    class _SweepClient:
        class _Containers:
            def get(self, cid):
                state = container_states.get(cid)
                if state is None:
                    raise Exception("no such container")

                class _C:
                    def __init__(self):
                        self.status = state

                    def remove(self, force=False):
                        removed.append((cid, force))
                return _C()

        def __init__(self):
            self.containers = self._Containers()

    with unittest.mock.patch.object(mcp_bridge, "_docker_client", return_value=_SweepClient()):
        mcp_bridge.sweep_orphan_sidecars()

    assert ("cid-123", True) in removed, "sweep must force-remove OUR leftover container"
    assert ("cid-legacy", True) in removed, \
        "sweep must force-remove a legacy (NULL node_id) orphan even while running"
    assert ("cid-dead", True) in removed, "sweep must clean up a foreign node's dead container"
    assert not any(cid == "cid-foreign-live" for cid, _ in removed), \
        "sweep must NEVER remove another node's running sidecar"
    remaining = {r.key: r.container_id for r in _rows()}
    assert remaining == {"foreign-running-key": "cid-foreign-live"}, \
        "only the foreign node's live sidecar row may survive the sweep"

    # A second sweep is a no-op (the surviving row belongs to a live node).
    with unittest.mock.patch.object(mcp_bridge, "_docker_client", return_value=_SweepClient()):
        mcp_bridge.sweep_orphan_sidecars()
    assert len(removed) == 3, "second sweep must not remove anything extra"
    assert {r.key for r in _rows()} == {"foreign-running-key"}


# ---------------------------------------------------------------------------
# Subprocess backend: per-backend env selection (subprocess_env)
#
# The real HappyFox seed configures docker-oriented static env
# (MCP_TRANSPORT=streamable-http, PORT=8000). The subprocess backend speaks
# stdio, so the server must run in stdio mode instead. These tests mirror the
# REAL seed's env shape with the fake server (which, like the real upstream
# server, refuses to serve stdio when an HTTP transport is selected), so a
# bridge regression that passes the docker env to the subprocess backend fails
# loudly instead of hanging for the startup timeout.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def http_env_template_id():
    """Template mirroring the production HappyFox runtime_config env shape."""
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    template_id = "fake-mcp-http-env"
    fake_path = os.path.join(os.path.dirname(__file__), "fake_mcp_server.py")
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="Fake MCP (HTTP env shape)",
            description="Mirrors the real HappyFox runtime_config env/subprocess_env shape.",
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
                # Docker-backend env: would make a stdio sidecar exit instantly.
                "env": {"MCP_TRANSPORT": "streamable-http", "PORT": "8000"},
                # Subprocess-backend override: stdio mode.
                "subprocess_env": {"MCP_TRANSPORT": "stdio"},
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


def test_subprocess_backend_uses_subprocess_env_not_docker_env(client, auth_user, http_env_template_id):
    r = client.post("/api/mcp/config/register",
                    headers=_h(auth_user["token"]),
                    json={"template_id": http_env_template_id, "credentials_json": FAKE_CREDS})
    assert r.status_code == 200, r.text

    r = client.post(f"/api/mcp/proxy/{http_env_template_id}/list_items",
                    headers=_h(auth_user["token"]), json={"limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_error"] is False
    assert "api=fake-key-123" in body["data"]
    assert "token=fake-token-456" in body["data"]


def test_static_env_helper_prefers_subprocess_env_for_subprocess_backend(monkeypatch):
    """_static_env picks subprocess_env over env only for the subprocess backend."""
    from api import mcp_bridge

    cfg = {
        "env": {"MCP_TRANSPORT": "streamable-http", "PORT": "8000"},
        "subprocess_env": {"MCP_TRANSPORT": "stdio"},
    }
    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "subprocess")
    assert mcp_bridge._static_env(cfg) == {"MCP_TRANSPORT": "stdio"}
    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "docker")
    assert mcp_bridge._static_env(cfg) == {"MCP_TRANSPORT": "streamable-http", "PORT": "8000"}
    # Without subprocess_env the subprocess backend falls back to env.
    assert mcp_bridge._static_env({"env": {"A": "1"}}) == {"A": "1"}
    assert mcp_bridge._static_env({}) == {}


# ---------------------------------------------------------------------------
# Real upstream server: pinned happyfox-mcp submodule through the subprocess
# bridge path, with the SAME runtime_config shape as the production seed.
# Proves spawn + stdio handshake + tools/call + admin discovery against the
# actual upstream code so the documented local-dev path cannot silently rot.
# ---------------------------------------------------------------------------
HAPPYFOX_SUBMODULE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "integrations", "happyfox-mcp"))


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(HAPPYFOX_SUBMODULE, "happyfox_mcp.py")),
    reason="integrations/happyfox-mcp submodule is not checked out")
def test_real_happyfox_submodule_subprocess_path(client, auth_user):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    template_id = "happyfox-submodule-test"
    fake_upstream_creds = {
        "HAPPYFOX_DOMAIN": "fake.example.com",
        "HAPPYFOX_API_KEY": "fake-key",
        "HAPPYFOX_AUTH_CODE": "fake-code",
    }
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="HappyFox (submodule e2e test)",
            description="Runs the pinned integrations/happyfox-mcp submodule through the bridge.",
            config_schema={
                "category": "Test",
                "type": "object",
                "properties": {
                    "HAPPYFOX_DOMAIN": {"type": "string", "label": "Domain", "required": True},
                    "HAPPYFOX_API_KEY": {"type": "password", "label": "API Key", "required": True},
                    "HAPPYFOX_AUTH_CODE": {"type": "password", "label": "Auth Code", "required": True},
                },
                "required": ["HAPPYFOX_DOMAIN", "HAPPYFOX_API_KEY", "HAPPYFOX_AUTH_CODE"],
            },
            runtime="mcp-server",
            runtime_config={
                "image": "ghcr.io/kulik-labs-development/eepy-host-happyfox:latest",
                "command": ["python", "happyfox_mcp.py"],
                "cwd": "integrations/happyfox-mcp",
                "env": {"MCP_TRANSPORT": "streamable-http", "PORT": "8000"},
                "subprocess_env": {"MCP_TRANSPORT": "stdio"},
                "endpoint": "/",
                "port": "8000",
                "env_mapping": {
                    "HAPPYFOX_DOMAIN": "HAPPYFOX_DOMAIN",
                    "HAPPYFOX_API_KEY": "HAPPYFOX_API_KEY",
                    "HAPPYFOX_AUTH_CODE": "HAPPYFOX_AUTH_CODE",
                },
                "test_tool": {"name": "list_tickets", "arguments": {"status": "_pending", "size": 1}},
            },
            approved_by_admin=True,
            enabled_global=True,
        )
        db.add(t)
        db.commit()
    finally:
        db.close()

    try:
        r = client.post("/api/mcp/config/register", headers=_h(auth_user["token"]),
                        json={"template_id": template_id, "credentials_json": fake_upstream_creds})
        assert r.status_code == 200, r.text

        # Proxy call against the REAL upstream server with fake credentials:
        # the sidecar must spawn in stdio mode, complete the MCP handshake,
        # and relay the upstream failure as tool text (NOT a handshake error).
        r = client.post(f"/api/mcp/proxy/{template_id}/list_tickets",
                        headers=_h(auth_user["token"]),
                        json={"status": "_pending", "size": 1})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tool"] == "list_tickets"
        assert isinstance(body["data"], str) and body["data"].strip(), "expected tool text, got empty data"
        assert body["is_error"] is True, "fake credentials must produce an upstream tool error"

        # Connection test endpoint (test_tool path) must report a clean
        # credential failure, not a bridge/handshake failure.
        r = client.post(f"/api/mcp/config/{template_id}/test", headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed", r.json()

        # Admin discovery against the real server: the pinned submodule commit
        # (91906dc) exposes exactly the 16 tools listed in the production seed.
        r = client.post(f"/superuser/mcp/templates/{template_id}/discover",
                        headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["tool_count"] == 16, r.json()
        assert "download_attachment" in r.json()["tools"]
    finally:
        from api import mcp_bridge
        mcp_bridge.shutdown_all_instances()


# ---------------------------------------------------------------------------
# Sidecar containment: resource limits + non-root user opt-in
# ---------------------------------------------------------------------------
def test_sidecar_run_kwargs_default_limits(monkeypatch):
    from api import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "SIDECAR_MEM_LIMIT", "512m")
    monkeypatch.setattr(mcp_bridge, "SIDECAR_CPU_LIMIT", 1.0)
    kwargs = mcp_bridge._sidecar_run_kwargs({})
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["cpu_period"] == 100000
    assert kwargs["cpu_quota"] == 100000
    assert "user" not in kwargs, "no user override -> image default"


def test_sidecar_run_kwargs_user_and_env_overrides(monkeypatch):
    from api import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "SIDECAR_MEM_LIMIT", "1g")
    monkeypatch.setattr(mcp_bridge, "SIDECAR_CPU_LIMIT", 2.5)
    kwargs = mcp_bridge._sidecar_run_kwargs({"user": "1000:1000"})
    assert kwargs["mem_limit"] == "1g"
    assert kwargs["cpu_quota"] == 250000
    assert kwargs["user"] == "1000:1000"


# ---------------------------------------------------------------------------
# Seeded eBay template (template #2): the seed in main.py must carry a valid
# mcp-server sidecar spec for BOTH instance backends.
# ---------------------------------------------------------------------------
def test_seeded_ebay_template_shape(client):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == "ebay").first()
    finally:
        db.close()
    assert t is not None, "ebay template was not seeded"
    assert t.approved_by_admin and t.enabled_global
    assert t.runtime == "mcp-server"
    assert t.image_tag == "ghcr.io/kulik-labs-development/eepy-host-ebay"

    cfg = t.runtime_config
    # Subprocess backend (local dev): stdio entrypoint of the pinned submodule.
    assert cfg["command"] == ["node", "build/index.js"]
    assert cfg["cwd"] == "integrations/ebay-mcp"
    assert cfg["subprocess_env"] == {}, "stdio entrypoint needs none of the HTTP transport vars"
    # Docker backend (production): streamable-HTTP sidecar image.
    assert cfg["image"] == "ghcr.io/kulik-labs-development/eepy-host-ebay:latest"
    assert cfg["port"] == "3000"
    assert cfg["endpoint"] == "/"
    env = cfg["env"]
    assert env["OAUTH_ENABLED"] == "false", "upstream bearer middleware must be off (proxy is the auth layer)"
    assert env["MCP_HOST"] == "0.0.0.0", "upstream binds localhost without an explicit MCP_HOST"
    assert env["MCP_PORT"] == "3000"
    # Every config_schema credential field maps 1:1 to the upstream env var.
    mapping = cfg["env_mapping"]
    for field in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENVIRONMENT",
                  "EBAY_REDIRECT_URI", "EBAY_MARKETPLACE_ID", "EBAY_USER_REFRESH_TOKEN"):
        assert mapping.get(field) == field, f"env_mapping must pass '{field}' through unchanged"
    # Read-only probe for the connection test + non-empty spec seed.
    assert cfg["test_tool"] == {"name": "ebay_get_rate_limits", "arguments": {}}
    assert cfg["tool_names"] and all(n.startswith("ebay_") for n in cfg["tool_names"])
    # The upstream server exits at startup without client id/secret: those two
    # (plus environment) are the required wizard fields.
    assert t.config_schema["required"] == ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENVIRONMENT"]


# ---------------------------------------------------------------------------
# Real upstream server: pinned ebay-mcp submodule through the subprocess
# bridge path, with the SAME runtime_config shape as the production seed.
# Proves spawn + stdio handshake + tools/call + admin discovery against the
# actual upstream code so the documented local-dev path cannot silently rot.
# Needs a one-time `pnpm install && pnpm run build` in the submodule.
# ---------------------------------------------------------------------------
EBAY_SUBMODULE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "integrations", "ebay-mcp"))


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(EBAY_SUBMODULE, "build", "index.js")),
    reason="integrations/ebay-mcp submodule is not built (run: pnpm install --ignore-scripts && pnpm run build)")
def test_real_ebay_submodule_subprocess_path(client, auth_user):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    template_id = "ebay-submodule-test"
    fake_upstream_creds = {
        "EBAY_CLIENT_ID": "fake-client-id",
        "EBAY_CLIENT_SECRET": "fake-client-secret",
        "EBAY_ENVIRONMENT": "sandbox",
    }
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="eBay (submodule e2e test)",
            description="Runs the pinned integrations/ebay-mcp submodule through the bridge.",
            config_schema={
                "category": "Test",
                "type": "object",
                "properties": {
                    "EBAY_CLIENT_ID": {"type": "string", "label": "Client ID", "required": True},
                    "EBAY_CLIENT_SECRET": {"type": "password", "label": "Client Secret", "required": True},
                    "EBAY_ENVIRONMENT": {"type": "string", "label": "Environment", "required": True},
                },
                "required": ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENVIRONMENT"],
            },
            runtime="mcp-server",
            runtime_config={
                "image": "ghcr.io/kulik-labs-development/eepy-host-ebay:latest",
                "command": ["node", "build/index.js"],
                "cwd": "integrations/ebay-mcp",
                "env": {"OAUTH_ENABLED": "false", "MCP_HOST": "0.0.0.0", "MCP_PORT": "3000"},
                "subprocess_env": {},
                "endpoint": "/",
                "port": "3000",
                "env_mapping": {
                    "EBAY_CLIENT_ID": "EBAY_CLIENT_ID",
                    "EBAY_CLIENT_SECRET": "EBAY_CLIENT_SECRET",
                    "EBAY_ENVIRONMENT": "EBAY_ENVIRONMENT",
                },
                "test_tool": {"name": "ebay_get_rate_limits", "arguments": {}},
            },
            approved_by_admin=True,
            enabled_global=True,
        )
        db.add(t)
        db.commit()
    finally:
        db.close()

    try:
        r = client.post("/api/mcp/config/register", headers=_h(auth_user["token"]),
                        json={"template_id": template_id, "credentials_json": fake_upstream_creds})
        assert r.status_code == 200, r.text

        # Proxy call against the REAL upstream server with fake credentials:
        # the sidecar must spawn in stdio mode, complete the MCP handshake,
        # and relay the upstream auth failure as tool text (NOT a handshake
        # error). No refresh token is set, so startup performs no network I/O.
        r = client.post(f"/api/mcp/proxy/{template_id}/ebay_get_rate_limits",
                        headers=_h(auth_user["token"]), json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tool"] == "ebay_get_rate_limits"
        assert isinstance(body["data"], str) and body["data"].strip(), "expected tool text, got empty data"
        assert body["is_error"] is True, "fake credentials must produce an upstream tool error"

        # Connection test endpoint (test_tool path) must report a clean
        # credential failure, not a bridge/handshake failure.
        r = client.post(f"/api/mcp/config/{template_id}/test", headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed", r.json()

        # Admin discovery against the real server: the pinned submodule commit
        # (a241405) advertises the full Sell API catalogue.
        r = client.post(f"/superuser/mcp/templates/{template_id}/discover",
                        headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["tool_count"] == 299, r.json()
        assert "ebay_get_inventory_items" in r.json()["tools"]
    finally:
        from api import mcp_bridge
        mcp_bridge.shutdown_all_instances()


# ---------------------------------------------------------------------------
# Per-request headers for HTTP sidecars (the Portainer MCP server contract):
#   - generated_secrets: the bridge mints a fresh random value per spawn
#   - headers: {{ENV}} placeholders resolved from the sidecar's final env
#   - subprocess_env_mapping: stdio reads PORTAINER_API_KEY from env while
#     HTTP mode must NOT have it set (the key rides a per-request header)
#   - fixed Host header: the upstream 421-rejects Hosts outside its
#     PORTAINER_MCP_ALLOWED_HOSTS allowlist, and the sidecar's container IP
#     is only known after spawn
# ---------------------------------------------------------------------------
def test_credential_mapping_prefers_subprocess_env_mapping_for_subprocess_backend(monkeypatch):
    from api import mcp_bridge

    cfg = {
        "env_mapping": {"FIELD": "DOCKER_NAME"},
        "subprocess_env_mapping": {"FIELD": "STDIO_NAME"},
    }
    creds = {"FIELD": "value-1234567890"}
    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "subprocess")
    assert mcp_bridge.map_env(cfg, creds) == {"STDIO_NAME": "value-1234567890"}
    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "docker")
    assert mcp_bridge.map_env(cfg, creds) == {"DOCKER_NAME": "value-1234567890"}
    # Subprocess backend without an override falls back to env_mapping.
    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "subprocess")
    assert mcp_bridge.map_env({"env_mapping": {"FIELD": "ONLY"}}, creds) == {
        "ONLY": "value-1234567890"}


def test_sidecar_env_mints_fresh_generated_secrets_per_spawn():
    from api import mcp_bridge

    cfg = {"env": {"STATIC_VAR": "1"}, "generated_secrets": ["GATE_TOKEN"]}
    env1 = mcp_bridge._sidecar_env(cfg, {})
    env2 = mcp_bridge._sidecar_env(cfg, {})
    assert env1["GATE_TOKEN"] != env2["GATE_TOKEN"], "each spawn must mint a fresh secret"
    assert len(env1["GATE_TOKEN"]) == 64, "token_hex(32) -> 64 hex chars"
    assert all(c in "0123456789abcdef" for c in env1["GATE_TOKEN"])
    # Static env and (mapped) credentials are untouched by the minting pass.
    assert env1["STATIC_VAR"] == "1"


def test_sidecar_headers_substitutes_placeholders_from_env(monkeypatch):
    from api import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "docker")
    cfg = {"headers": {
        "Authorization": "Bearer {{GATE_TOKEN}}",
        "X-Portainer-API-Key": "{{EEPY_KEY}}",
        "X-Static": "plain-value",
    }}
    env = {"GATE_TOKEN": "gate-0123456789abcdef", "EEPY_KEY": "ptr_userkey123"}
    assert mcp_bridge._sidecar_headers(cfg, env) == {
        "Authorization": "Bearer gate-0123456789abcdef",
        "X-Portainer-API-Key": "ptr_userkey123",
        "X-Static": "plain-value",
    }
    # No headers configured -> {} (the existing happyfox/ebay templates).
    assert mcp_bridge._sidecar_headers({"env": {"A": "1"}}, {"A": "1"}) == {}


def test_sidecar_headers_missing_env_var_raises(monkeypatch):
    from api import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "docker")
    cfg = {"headers": {"Authorization": "Bearer {{NOT_SET_TOKEN}}"}}
    try:
        mcp_bridge._sidecar_headers(cfg, {})
        raise AssertionError("expected BridgeError for an unresolvable placeholder")
    except mcp_bridge.BridgeError as e:
        assert "NOT_SET_TOKEN" in str(e), f"error must name the missing var: {e}"


def test_docker_container_env_drops_host_allowlist_vars():
    """Docker sidecars must NOT inherit the host's allowlist env (notably
    PATH): the container env is the image's ENV plus the bridge's additions,
    and a host PATH would override the image's ENV PATH, breaking entrypoints
    in image-local locations (uv venv at /app/.venv/bin)."""
    from api import mcp_bridge

    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/someone",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "TZ": "UTC",
        "PYTHONUNBUFFERED": "1",
        "PORTAINER_MCP_TRANSPORT": "http",   # static template env
        "EEPY_PORTAINER_API_KEY": "ptr_user_key_value",  # mapped credential
        "PORTAINER_MCP_AUTH_TOKEN": "a" * 64,  # generated secret
    }
    out = mcp_bridge._docker_container_env(env)
    for host_var in ("PATH", "HOME", "LANG", "LC_ALL", "TZ"):
        assert host_var not in out, f"{host_var} must not cross into the container"
    assert out["PORTAINER_MCP_TRANSPORT"] == "http"
    assert out["EEPY_PORTAINER_API_KEY"] == "ptr_user_key_value"
    assert out["PORTAINER_MCP_AUTH_TOKEN"] == "a" * 64
    assert out["PYTHONUNBUFFERED"] == "1"


def test_sidecar_headers_skipped_for_subprocess_backend(monkeypatch):
    """Stdio has no HTTP request to carry headers on; the subprocess env may
    legitimately lack the vars the header templates reference (the Portainer
    docker env parks the key in EEPY_PORTAINER_API_KEY while stdio maps it to
    PORTAINER_API_KEY)."""
    from api import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "subprocess")
    cfg = {"headers": {"Authorization": "Bearer {{GATE_TOKEN}}"}}
    assert mcp_bridge._sidecar_headers(cfg, {}) == {}


def test_http_sidecar_headers_reach_the_upstream_server():
    """Full plumbing: Instance.headers -> pre-configured httpx client -> wire.

    A real streamable-HTTP MCP server (mcp SDK, same 1.x line as the bridge)
    runs on 127.0.0.1 behind a DNS-rebinding-style guard that 421-rejects
    any Host outside an `eepy-sidecar:*` allowlist — the exact contract of
    the Portainer MCP server (http_security.DNSRebindingMiddleware + the MCP
    SDK's wildcard-port Host matching). If the bridge failed to send the
    fixed Host / gate bearer / per-user key headers, the handshake would be
    421-rejected (or the server would observe wrong values) and this test
    fails.
    """
    import asyncio
    import socket as socket_mod
    import threading
    import time as time_mod

    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from starlette.responses import Response

    from api import mcp_bridge

    seen: list[dict[str, str]] = []

    server = FastMCP("fake-http-mcp")

    @server.tool()
    def ping() -> str:
        return "pong"

    # Mirror the Portainer build: its fastmcp 3.x does NOT plumb the MCP SDK's
    # built-in Host/Origin validation through (it ships with the localhost
    # defaults), and instead installs its OWN allowlist middleware fed by
    # PORTAINER_MCP_ALLOWED_HOSTS — which the guard below emulates, including
    # the SDK's wildcard-port (`base:*`) matching semantics.
    from mcp.server.transport_security import TransportSecuritySettings
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False)

    app = server.streamable_http_app()

    async def guard(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        seen.append(headers)
        allowed_hosts = ["eepy-sidecar:*"]
        host = headers.get("host", "")
        allowed = (host in allowed_hosts
                   or any(host.startswith(p[:-2] + ":") for p in allowed_hosts if p.endswith(":*")))
        if not allowed:
            await Response("Invalid Host header", status_code=421)(scope, receive, send)
            return
        await app(scope, receive, send)

    probe = socket_mod.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    # loop="asyncio" on purpose: the default "auto" installs uvloop GLOBALLY
    # (uvloop.install() replaces the process-wide asyncio event loop policy,
    # never restoring it). uvloop's policy has no child watcher, so any LATER
    # subprocess spawn on a plain-asyncio loop (the suite's persistent test
    # portal) dies with NotImplementedError deep in anyio.open_process.
    uv_srv = uvicorn.Server(uvicorn.Config(
        guard, host="127.0.0.1", port=port, log_level="error", loop="asyncio"))
    thread = threading.Thread(target=uv_srv.run, daemon=True)
    thread.start()
    deadline = time_mod.time() + 10
    while not uv_srv.started and time_mod.time() < deadline:
        time_mod.sleep(0.05)
    assert uv_srv.started, "fake HTTP MCP server did not start"

    try:
        gate_token = "a" * 64
        inst = mcp_bridge.Instance(
            key="header-e2e", kind="url",
            url=f"http://127.0.0.1:{port}/mcp",
            headers={
                "Host": "eepy-sidecar:17717",
                "Authorization": f"Bearer {gate_token}",
                "X-Portainer-API-Key": "ptr_fake_user_key",
            },
        )

        async def _drive():
            sess = await mcp_bridge.open_session(inst)
            try:
                return await mcp_bridge.list_tools(sess.session)
            finally:
                await sess.close()

        loop = asyncio.new_event_loop()
        try:
            tools = loop.run_until_complete(_drive())
        finally:
            loop.close()

        assert any(t["name"] == "ping" for t in tools), f"tools/list failed: {tools}"
        assert seen, "the guard observed no requests at all"
        first = seen[0]
        # The dial URL is 127.0.0.1:<port>; the explicit Host header must win.
        assert first["host"] == "eepy-sidecar:17717", \
            f"explicit Host header must override the dial URL, got {first['host']!r}"
        assert first["authorization"] == f"Bearer {gate_token}"
        assert first["x-portainer-api-key"] == "ptr_fake_user_key"
    finally:
        uv_srv.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Seeded Portainer template (template #3): the seed in main.py must carry a
# valid mcp-server sidecar spec for BOTH instance backends, including the
# header/gate-token contract the upstream HTTP mode requires.
# ---------------------------------------------------------------------------
def test_seeded_portainer_template_shape(client):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == "portainer").first()
    finally:
        db.close()
    assert t is not None, "portainer template was not seeded"
    assert t.approved_by_admin and t.enabled_global
    assert t.runtime == "mcp-server"
    assert t.image_tag == "ghcr.io/kulik-labs-development/eepy-host-portainer"

    cfg = t.runtime_config
    # Subprocess backend (local dev): stdio entrypoint of the pinned submodule.
    assert cfg["command"] == ["uv", "run", "mcp-portainer"]
    assert cfg["cwd"] == "integrations/portainer-mcp"
    assert cfg["subprocess_env"]["PORTAINER_MCP_TRANSPORT"] == "stdio"
    # Docker backend (production): streamable-HTTP sidecar image on :17717 /mcp.
    assert cfg["image"] == "ghcr.io/kulik-labs-development/eepy-host-portainer:latest"
    assert cfg["port"] == "17717"
    assert cfg["endpoint"] == "/mcp"
    env = cfg["env"]
    assert env["PORTAINER_MCP_DANGEROUSLY_ALLOW_PLAINTEXT_HTTP"] == "1", \
        "sidecar is unreachable outside the internal eepy-sidecars network"
    assert env["PORTAINER_MCP_ALLOWED_HOSTS"] == "eepy-sidecar:*"
    # The in-band guidance gate must be off on BOTH backends: sidecars are
    # idle-reaped at 300s but the gate's window is 1800s, so a respawned
    # sidecar would bounce the user's first call after any 5-minute pause.
    assert env["PORTAINER_MCP_DISABLE_GUIDANCE_GATE"] == "1"
    assert cfg["subprocess_env"]["PORTAINER_MCP_DISABLE_GUIDANCE_GATE"] == "1"
    # HTTP mode refuses to boot with PORTAINER_API_KEY set, so the docker
    # mapping parks the user's key under an upstream-ignorable name for the
    # header template; stdio mode reads the upstream var name directly.
    assert cfg["env_mapping"]["PORTAINER_API_KEY"] == "EEPY_PORTAINER_API_KEY"
    assert cfg["subprocess_env_mapping"]["PORTAINER_API_KEY"] == "PORTAINER_API_KEY"
    # Per-sidecar gate token: minted by the bridge on every spawn, never
    # stored in runtime_config or the DB.
    assert cfg["generated_secrets"] == ["PORTAINER_MCP_AUTH_TOKEN"]
    headers = cfg["headers"]
    assert headers["Host"] == "eepy-sidecar:17717"
    assert headers["Authorization"] == "Bearer {{PORTAINER_MCP_AUTH_TOKEN}}"
    assert headers["X-Portainer-API-Key"] == "{{EEPY_PORTAINER_API_KEY}}"
    # Read-only probe for the connection test + non-empty spec seed.
    assert cfg["test_tool"] == {"name": "systemVersion", "arguments": {}}
    assert cfg["tool_names"] and "systemVersion" in cfg["tool_names"]
    # The wizard's required fields: URL + access token.
    assert t.config_schema["required"] == ["PORTAINER_URL", "PORTAINER_API_KEY"]


# ---------------------------------------------------------------------------
# Real upstream server: pinned portainer-mcp submodule through the subprocess
# bridge path, with the SAME runtime_config shape as the production seed
# (stdio transport). Proves spawn + stdio handshake + tools/call + admin
# discovery against the actual upstream code so the documented local-dev path
# cannot silently rot. Needs `uv` on PATH (one-time dep sync in the submodule).
# ---------------------------------------------------------------------------
PORTAINER_SUBMODULE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "integrations", "portainer-mcp"))


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(PORTAINER_SUBMODULE, "pyproject.toml")),
    reason="integrations/portainer-mcp submodule is not checked out")
@pytest.mark.skipif(
    not shutil.which("uv"),
    reason="uv is required for the portainer subprocess dev path (uv run)")
def test_real_portainer_submodule_subprocess_path(client, auth_user):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    template_id = "portainer-submodule-test"
    fake_upstream_creds = {
        "PORTAINER_URL": "https://nonexistent-eepy-portainer.invalid",
        "PORTAINER_API_KEY": "ptr_fake_key_for_bridge_test",
    }
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="Portainer (submodule e2e test)",
            description="Runs the pinned integrations/portainer-mcp submodule through the bridge.",
            config_schema={
                "category": "Test",
                "type": "object",
                "properties": {
                    "PORTAINER_URL": {"type": "string", "label": "URL", "required": True},
                    "PORTAINER_API_KEY": {"type": "password", "label": "API Key", "required": True},
                },
                "required": ["PORTAINER_URL", "PORTAINER_API_KEY"],
            },
            runtime="mcp-server",
            runtime_config={
                "command": ["uv", "run", "mcp-portainer"],
                "cwd": "integrations/portainer-mcp",
                "subprocess_env": {
                    "PORTAINER_MCP_TRANSPORT": "stdio",
                    "PORTAINER_MCP_DISABLE_GUIDANCE_GATE": "1",
                },
                "env_mapping": {
                    "PORTAINER_URL": "PORTAINER_URL",
                    "PORTAINER_API_KEY": "PORTAINER_API_KEY",
                },
                "test_tool": {"name": "systemVersion", "arguments": {}},
            },
            approved_by_admin=True,
            enabled_global=True,
        )
        db.add(t)
        db.commit()
    finally:
        db.close()

    try:
        r = client.post("/api/mcp/config/register", headers=_h(auth_user["token"]),
                        json={"template_id": template_id, "credentials_json": fake_upstream_creds})
        assert r.status_code == 200, r.text

        # Local tool (serves the bundled guide, no upstream call): the sidecar
        # must spawn in stdio mode and complete the MCP handshake + tools/call
        # even with fake credentials.
        r = client.post(f"/api/mcp/proxy/{template_id}/get_guidance",
                        headers=_h(auth_user["token"]), json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tool"] == "get_guidance"
        assert body["is_error"] is False, f"get_guidance is local: {body['data'][:300]}"
        assert isinstance(body["data"], str) and "Portainer" in body["data"]

        # Upstream-bound tool with fake credentials: the failure must be
        # relayed as upstream tool text (the sidecar's httpx call to the
        # unreachable instance), NOT a bridge/handshake error.
        r = client.post(f"/api/mcp/proxy/{template_id}/systemVersion",
                        headers=_h(auth_user["token"]), json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tool"] == "systemVersion"
        assert body["is_error"] is True, "unreachable upstream must produce a tool error"

        # Connection test endpoint (test_tool path) must report a clean
        # credential failure, not a bridge/handshake failure.
        r = client.post(f"/api/mcp/config/{template_id}/test", headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed", r.json()

        # Admin discovery against the real server: the pinned submodule commit
        # (79ce50b, 2.44.0+1) advertises the full default-profile catalogue.
        r = client.post(f"/superuser/mcp/templates/{template_id}/discover",
                        headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["tool_count"] == 211, r.json()
        assert "systemVersion" in r.json()["tools"]
    finally:
        from api import mcp_bridge
        mcp_bridge.shutdown_all_instances()


# ---------------------------------------------------------------------------
# Seeded Warden template (template #4): the seed in main.py must carry a valid
# mcp-server sidecar spec for BOTH instance backends, including the
# per-request X-BW-* header contract the upstream HTTP mode requires.
# ---------------------------------------------------------------------------
def test_seeded_warden_template_shape(client):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == "warden").first()
    finally:
        db.close()
    assert t is not None, "warden template was not seeded"
    assert t.approved_by_admin and t.enabled_global
    assert t.runtime == "mcp-server"
    assert t.image_tag == "ghcr.io/kulik-labs-development/eepy-host-warden"

    cfg = t.runtime_config
    # Subprocess backend (local dev): stdio entrypoint of the pinned submodule.
    assert cfg["command"] == ["node", "bin/warden-mcp.js", "--stdio"]
    assert cfg["cwd"] == "integrations/warden-mcp"
    # Docker backend (production): streamable-HTTP sidecar image on :3005 /sse.
    assert cfg["image"] == "ghcr.io/kulik-labs-development/eepy-host-warden:latest"
    assert cfg["port"] == "3005"
    assert cfg["endpoint"] == "/sse"
    # The env-fallback escape hatch must stay OFF: a headerless request must
    # never inherit the sidecar's vault identity.
    assert cfg["env"].get("KEYCHAIN_ALLOW_ENV_FALLBACK") != "true"
    assert cfg["subprocess_env"].get("KEYCHAIN_ALLOW_ENV_FALLBACK") != "true"
    # Optional-login static defaults keep the header placeholders resolvable
    # (the bridge hard-fails on a missing referenced env var); mapped
    # credentials override these at spawn.
    for backend_env in (cfg["env"], cfg["subprocess_env"]):
        assert backend_env["BW_CLIENTID"] == ""
        assert backend_env["BW_CLIENTSECRET"] == ""
        assert backend_env["BW_USER"] == ""
    # User fields ride the upstream env names the header templates resolve.
    assert cfg["env_mapping"] == {
        "VAULT_HOST": "BW_HOST",
        "MASTER_PASSWORD": "BW_PASSWORD",
        "API_CLIENT_ID": "BW_CLIENTID",
        "API_CLIENT_SECRET": "BW_CLIENTSECRET",
        "LOGIN_USERNAME": "BW_USER",
    }
    headers = cfg["headers"]
    assert headers["X-BW-Host"] == "{{BW_HOST}}"
    assert headers["X-BW-Password"] == "{{BW_PASSWORD}}"
    assert headers["X-BW-ClientId"] == "{{BW_CLIENTID}}"
    assert headers["X-BW-ClientSecret"] == "{{BW_CLIENTSECRET}}"
    assert headers["X-BW-User"] == "{{BW_USER}}"
    # The connection-test probe must FORCE the vault unlock (keychain_status
    # is a lazy check that reports "not ready" without validating credentials).
    assert cfg["test_tool"] == {"name": "keychain_list_folders", "arguments": {}}
    assert cfg["tool_names"] and cfg["test_tool"]["name"] in cfg["tool_names"]
    # The wizard's required fields: host + master password. The login method
    # (API key pair vs email) is user choice, validated by the upstream.
    assert t.config_schema["required"] == ["VAULT_HOST", "MASTER_PASSWORD"]


def test_seeded_warden_header_resolution_with_optional_logins(client, monkeypatch):
    """The dual-login contract: all five X-BW-* headers are sent on every
    request; upstream treats empty values as absent, so the user's chosen
    login method wins. The seed's static empty defaults keep every
    placeholder resolvable regardless of which optional fields the user left
    blank (untouched wizard fields are ABSENT from the stored credentials)."""
    import api.mcp_bridge as mcp_bridge
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == "warden").first()
    finally:
        db.close()
    assert t is not None, "warden template was not seeded"
    cfg = t.runtime_config
    monkeypatch.setattr(mcp_bridge, "INSTANCE_BACKEND", "docker")

    def resolve(creds: dict) -> dict:
        env = mcp_bridge._sidecar_env(cfg, mcp_bridge.map_env(cfg, creds))
        return mcp_bridge._sidecar_headers(cfg, env)

    # API key login: the pair is carried, the email header is empty (absent).
    h = resolve({
        "VAULT_HOST": "https://vault.example.com",
        "MASTER_PASSWORD": "mp-123",
        "API_CLIENT_ID": "user.abc123",
        "API_CLIENT_SECRET": "s3cret",
    })
    assert h["X-BW-Host"] == "https://vault.example.com"
    assert h["X-BW-Password"] == "mp-123"
    assert h["X-BW-ClientId"] == "user.abc123"
    assert h["X-BW-ClientSecret"] == "s3cret"
    assert h["X-BW-User"] == ""

    # Email login: the pair headers are empty (absent), the email is carried.
    h = resolve({
        "VAULT_HOST": "https://vault.example.com",
        "MASTER_PASSWORD": "mp-123",
        "LOGIN_USERNAME": "alice@example.com",
    })
    assert h["X-BW-ClientId"] == ""
    assert h["X-BW-ClientSecret"] == ""
    assert h["X-BW-User"] == "alice@example.com"


# ---------------------------------------------------------------------------
# Real upstream server: pinned warden-mcp submodule through the subprocess
# bridge path, with the SAME runtime_config shape as the production seed
# (stdio transport). The upstream stdio transport authenticates LAZILY: the
# MCP handshake succeeds with fake credentials, keychain_status reports
# "not ready" without unlocking, and the first vault tool (keychain_list_folders)
# triggers the real bw login + unlock and fails against the fake host. So
# with fake credentials this test proves: spawn + stdio handshake + tools/call
# against the actual upstream code, upstream error relay as a tool error (not
# a bridge failure), a clean credential failure from the connection-test
# route, and admin discovery of the full tool catalogue.
# Needs Node 24+ on PATH; performs the runbook's one-time
# `npm install && npm run build` inside the submodule if dist/ is missing.
# ---------------------------------------------------------------------------
WARDEN_SUBMODULE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "integrations", "warden-mcp"))


def _node_major() -> int | None:
    """Major version of the host `node`, or None when missing (the upstream
    requires Node 24+; an older host node would fail opaquely at runtime)."""
    if not shutil.which("node"):
        return None
    import subprocess as sp
    try:
        out = sp.run(["node", "--version"], capture_output=True, text=True,
                     timeout=10).stdout.strip()  # e.g. v26.7.0
        return int(out.lstrip("v").split(".")[0])
    except (ValueError, IndexError, OSError):
        return None


_NODE_MAJOR = _node_major()


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(WARDEN_SUBMODULE, "package.json")),
    reason="integrations/warden-mcp submodule is not checked out")
@pytest.mark.skipif(
    _NODE_MAJOR is None or _NODE_MAJOR < 24,
    reason=f"node 24+ is required for the warden subprocess dev path (found: {_NODE_MAJOR or 'none'})")
def test_real_warden_submodule_subprocess_path(client, auth_user):
    import subprocess as sp

    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    # One-time build (cached: dist/server.js existing means already built).
    if not os.path.isfile(os.path.join(WARDEN_SUBMODULE, "dist", "server.js")):
        sp.run(["npm", "install"], cwd=WARDEN_SUBMODULE, check=True,
               stdout=sp.PIPE, stderr=sp.STDOUT, timeout=600)
        sp.run(["npm", "run", "build"], cwd=WARDEN_SUBMODULE, check=True,
               stdout=sp.PIPE, stderr=sp.STDOUT, timeout=300)

    template_id = "warden-submodule-test"
    fake_creds = {
        "VAULT_HOST": "https://nonexistent-eepy-warden.invalid",
        "MASTER_PASSWORD": "fake-master-password",
        "API_CLIENT_ID": "user.fake",
        "API_CLIENT_SECRET": "fake-secret",
    }
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="Warden (submodule e2e test)",
            description="Runs the pinned integrations/warden-mcp submodule through the bridge.",
            config_schema={
                "category": "Test",
                "type": "object",
                "properties": {
                    "VAULT_HOST": {"type": "string", "label": "Vault Host", "required": True},
                    "MASTER_PASSWORD": {"type": "password", "label": "Master Password", "required": True},
                },
                "required": ["VAULT_HOST", "MASTER_PASSWORD"],
            },
            runtime="mcp-server",
            runtime_config={
                "command": ["node", "bin/warden-mcp.js", "--stdio"],
                "cwd": "integrations/warden-mcp",
                "subprocess_env": {
                    "BW_CLIENTID": "",
                    "BW_CLIENTSECRET": "",
                    "BW_USER": "",
                },
                "env_mapping": {
                    "VAULT_HOST": "BW_HOST",
                    "MASTER_PASSWORD": "BW_PASSWORD",
                    "API_CLIENT_ID": "BW_CLIENTID",
                    "API_CLIENT_SECRET": "BW_CLIENTSECRET",
                    "LOGIN_USERNAME": "BW_USER",
                },
                "test_tool": {"name": "keychain_list_folders", "arguments": {}},
            },
            approved_by_admin=True,
            enabled_global=True,
        )
        db.add(t)
        db.commit()
    finally:
        db.close()

    try:
        r = client.post("/api/mcp/config/register", headers=_h(auth_user["token"]),
                        json={"template_id": template_id, "credentials_json": fake_creds})
        assert r.status_code == 200, r.text

        # Lazy tool: the sidecar must spawn with the env-mapped credentials
        # and complete the MCP handshake + tools/call even with fake
        # credentials (keychain_status reports "not ready" without unlocking).
        r = client.post(f"/api/mcp/proxy/{template_id}/keychain_status",
                        headers=_h(auth_user["token"]), json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tool"] == "keychain_status"
        assert body["is_error"] is False, f"keychain_status is lazy: {body['data'][:300]}"

        # Vault tool with fake credentials: the sidecar triggers the real bw
        # login + unlock against the unreachable host, and the failure must be
        # relayed as an upstream TOOL error (is_error), NOT a bridge/handshake
        # error — proving the env-mapped credentials reached the subprocess.
        r = client.post(f"/api/mcp/proxy/{template_id}/keychain_list_folders",
                        headers=_h(auth_user["token"]), json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tool"] == "keychain_list_folders"
        assert body["is_error"] is True, \
            f"unreachable vault must produce a tool error, got: {body['data'][:300]}"

        # Connection test endpoint (test_tool path) must report a clean
        # credential failure, not a bridge/handshake failure.
        r = client.post(f"/api/mcp/config/{template_id}/test", headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed", r.json()

        # Admin discovery against the real server: the pinned submodule
        # advertises its full default tool catalogue (no vault access needed).
        r = client.post(f"/superuser/mcp/templates/{template_id}/discover",
                        headers=_h(auth_user["token"]))
        assert r.status_code == 200, r.text
        disc = r.json()
        assert disc["tool_count"] > 0, disc
        assert "keychain_status" in disc["tools"]
        assert "keychain_list_folders" in disc["tools"]
    finally:
        from api import mcp_bridge
        mcp_bridge.shutdown_all_instances()
