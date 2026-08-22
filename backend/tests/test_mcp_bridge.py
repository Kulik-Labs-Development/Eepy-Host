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
