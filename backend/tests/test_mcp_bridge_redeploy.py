"""Tests for the redeploy/sidecar-dialing hardening added to mcp_bridge:

- node identity is stable across redeploys (own container name via the
  mounted docker socket) so the boot sweep recognizes its own leftovers;
- EEPY_NODE_ID override and the no-daemon uuid fallback still work;
- the configured sidecar network short name resolves to the daemon's
  project-prefixed name (compose/Portainer), with safe fallbacks;
- sidecar log output is redacted of the user's credential values before it
  reaches errors/logs;
- anyio BaseExceptionGroup explosions from the MCP SDK are flattened into a
  clean, one-line summary and converted to BridgeError (never a 500);
- deleting a user's config tears down that user's live sidecars immediately;
- the boot-time Docker daemon probe surfaces a missing socket mount (the
  classic stale-Portainer-stack failure) with an actionable fix instead of an
  opaque "Cannot reach the Docker daemon" on the user's first tool call;
- spawn/pull failures carry the daemon's own words in the 502 detail, and a
  private-registry (GHCR "unauthorized") pull yields the two host-side fixes
  instead of a bare "(APIError)".
"""

import unittest.mock

import pytest


@pytest.fixture()
def bridge():
    from api import mcp_bridge
    return mcp_bridge


# ---------------------------------------------------------------------------
# Node identity
# ---------------------------------------------------------------------------
def test_node_id_env_override(bridge, monkeypatch):
    monkeypatch.setenv("EEPY_NODE_ID", "orchestrator-node-42")
    assert bridge._resolve_node_id() == "orchestrator-node-42"


def test_node_id_from_own_container_name(bridge, monkeypatch):
    """A containerized backend self-identifies by its (stable) container name
    so the boot sweep sees its previous incarnation's sidecars as its own."""
    monkeypatch.delenv("EEPY_NODE_ID", raising=False)

    class _Own:
        attrs = {"Name": "/eepy-backend"}

        def reload(self):
            pass

    class _Client:
        class _Containers:
            def get(self, hostname):
                assert hostname == "fake-hostname"
                return _Own()

        def __init__(self):
            self.containers = self._Containers()

    monkeypatch.setattr("socket.gethostname", lambda: "fake-hostname")
    with unittest.mock.patch.object(bridge, "_docker_client", return_value=_Client()):
        assert bridge._resolve_node_id() == "docker:eepy-backend"


def test_node_id_falls_back_to_uuid_without_daemon(bridge, monkeypatch):
    monkeypatch.delenv("EEPY_NODE_ID", raising=False)

    def _no_daemon():
        raise bridge.BridgeError("Cannot reach the Docker daemon.")

    with unittest.mock.patch.object(bridge, "_docker_client", side_effect=_no_daemon):
        node = bridge._resolve_node_id()
    assert node != "" and not node.startswith("docker:")


# ---------------------------------------------------------------------------
# Sidecar network resolution (compose/Portainer project prefix)
# ---------------------------------------------------------------------------
def _client_with_own_networks(*nets):
    class _Own:
        attrs = {"NetworkSettings": {"Networks": {n: {} for n in nets}}}

        def reload(self):
            pass

    class _Client:
        class _Containers:
            def get(self, hostname):
                return _Own()

        def __init__(self):
            self.containers = self._Containers()

    return _Client()


@pytest.mark.parametrize("own,configured,expected", [
    # exact name (bare setup or Portainer without prefix)
    (["eepy-sidecars"], "eepy-sidecars", "eepy-sidecars"),
    # compose/Portainer project prefix (directory/stack name)
    (["deploy_eepy-sidecars"], "eepy-sidecars", "deploy_eepy-sidecars"),
    (["my_stack_eepy-sidecars"], "eepy-sidecars", "my_stack_eepy-sidecars"),
    # configured network is NOT one the backend is attached to: pass through
    # unchanged so the daemon produces a clear "network not found" error.
    (["other-net"], "eepy-sidecars", "eepy-sidecars"),
])
def test_resolve_sidecar_network(bridge, monkeypatch, own, configured, expected):
    monkeypatch.setattr(bridge, "SIDECAR_NETWORK", configured)
    client = _client_with_own_networks(*own)
    assert bridge._resolve_sidecar_network(client) == expected


def test_resolve_sidecar_network_unset(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SIDECAR_NETWORK", "")
    assert bridge._resolve_sidecar_network(_client_with_own_networks("eepy-sidecars")) is None


# ---------------------------------------------------------------------------
# Credential redaction of sidecar output
# ---------------------------------------------------------------------------
def test_redact_secrets_strips_credential_values(bridge):
    env = {
        "HAPPYFOX_API_KEY": "supersecret-api-key-123",
        "HAPPYFOX_AUTH_CODE": "authcode-secret-456",
        "MCP_TRANSPORT": "streamable-http",
        "PORT": "8000",  # short: not redacted
    }
    out = bridge._redact_secrets(
        "started with api key supersecret-api-key-123 and code authcode-secret-456 "
        "on streamable-http port 8000",
        env,
    )
    assert "supersecret-api-key-123" not in out
    assert "authcode-secret-456" not in out
    assert "[redacted]" in out
    assert "8000" in out  # short values (ports, flags) stay readable


# ---------------------------------------------------------------------------
# Exception summary + handshake error containment
# ---------------------------------------------------------------------------
def test_exc_summary_flattens_exception_group(bridge):
    group = BaseExceptionGroup(
        "unhandled errors in a TaskGroup (2 sub-exceptions)",
        [
            ConnectionRefusedError("[Errno 61] Connection refused"),
            RuntimeError("Attempted to exit cancel scope in a different task"),
        ],
    )
    summary = bridge._exc_summary(group)
    assert "ConnectionRefusedError" in summary
    assert "cancel scope" in summary
    assert isinstance(summary, str) and "\n" not in summary


def test_exc_summary_plain(bridge):
    assert bridge._exc_summary(ValueError("boom")) == "ValueError: boom"


def test_open_session_dead_sidecar_raises_bridgeerror_not_group(bridge):
    """A sidecar whose port is closed must surface as a BridgeError (502-able),
    never as an anyio BaseExceptionGroup (which escaped to a 500 before)."""
    import asyncio

    async def _drive():
        inst = bridge.Instance(key="dead-test", kind="docker", template_id="x",
                               container_id="cid-x", url="http://127.0.0.1:1/mcp")
        # port 1 is never listening: connect refused on the first attempt
        await bridge.open_session(inst)

    with pytest.raises(bridge.BridgeError):
        asyncio.run(asyncio.wait_for(_drive(), timeout=30))


# ---------------------------------------------------------------------------
# Config deletion tears down the user's live sidecars
# ---------------------------------------------------------------------------
def test_kill_instances_for_user_only_kills_owners(bridge):
    other = bridge.Instance(key="k-other", kind="subprocess", template_id="happyfox", user_id=999)
    mine = bridge.Instance(key="k-mine", kind="subprocess", template_id="happyfox", user_id=7)
    mine_other_tpl = bridge.Instance(key="k-tpl", kind="subprocess", template_id="ebay", user_id=7)
    bridge._REGISTRY.update({other.key: other, mine.key: mine, mine_other_tpl.key: mine_other_tpl})
    try:
        killed = bridge.kill_instances_for_user(7, "happyfox")
        assert killed == 1
        assert "k-mine" not in bridge._REGISTRY
        assert "k-other" in bridge._REGISTRY
        assert "k-tpl" in bridge._REGISTRY
    finally:
        for k in ("k-other", "k-mine", "k-tpl"):
            bridge._REGISTRY.pop(k, None)


def test_delete_config_kills_live_sidecar(client, fake_template_id, auth_user):
    from api import mcp_bridge
    from database import SessionLocal, User

    # Ensure a live sidecar exists for the user, then tag it with the owner id
    # the way acquire_instance does, so the delete route can find it.
    r = client.post(f"/api/mcp/proxy/{fake_template_id}/list_items",
                    headers={"Authorization": f"Bearer {auth_user['token']}"}, json={"limit": 1})
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        user_id = db.query(User).filter(User.username == auth_user["username"]).first().id
    finally:
        db.close()
    for inst in mcp_bridge._REGISTRY.values():
        if not inst.ephemeral and inst.template_id == fake_template_id:
            inst.user_id = user_id

    live_before = [k for k, i in mcp_bridge._REGISTRY.items()
                   if i.template_id == fake_template_id and not i.ephemeral]
    assert live_before

    r = client.delete(f"/api/mcp/config/{fake_template_id}",
                      headers={"Authorization": f"Bearer {auth_user['token']}"})
    assert r.status_code == 200, r.text
    live_after = [k for k, i in mcp_bridge._REGISTRY.items()
                  if i.template_id == fake_template_id and not i.ephemeral]
    assert live_after == [], "deleting the config must kill its sidecar immediately"


# ---------------------------------------------------------------------------
# Docker daemon reachability (Portainer socket-mount diagnostics)
# ---------------------------------------------------------------------------
def test_check_docker_daemon_subprocess_backend_short_circuits(bridge, monkeypatch):
    """The daemon probe must not require a daemon when the instance backend
    is subprocess (local dev runs without Docker)."""
    monkeypatch.setattr(bridge, "INSTANCE_BACKEND", "subprocess")
    ok, detail = bridge.check_docker_daemon()
    assert ok is True
    assert "no Docker daemon needed" in detail


def test_check_docker_daemon_reports_missing_socket_with_fix(bridge, monkeypatch):
    """No socket inside the container (a Portainer stack built from an older
    compose) must surface an ACTIONABLE message naming the missing socket and
    the fix, not an opaque 'Cannot reach the Docker daemon'."""
    monkeypatch.setattr(bridge, "INSTANCE_BACKEND", "docker")
    monkeypatch.setenv("DOCKER_HOST", "unix:///nonexistent/ee-docker-test.sock")
    ok, detail = bridge.check_docker_daemon()
    assert ok is False
    assert "/nonexistent/ee-docker-test.sock" in detail
    assert "Portainer" in detail
    assert "/var/run/docker.sock" in detail


def test_docker_socket_path_helper(bridge, monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    assert bridge._docker_socket_path() == "/var/run/docker.sock"
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    assert bridge._docker_socket_path() == "/var/run/docker.sock"
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")
    assert bridge._docker_socket_path() == "tcp://127.0.0.1:2375"


# ---------------------------------------------------------------------------
# Spawn/pull error classification (private-GHCR diagnostics)
# ---------------------------------------------------------------------------
def test_spawn_error_unauthorized_pull_is_actionable(bridge):
    """The production failure: host daemon has no GHCR credentials for a
    private package. The 502 detail must carry the registry's own words AND
    the two fixes (make package public / docker login on the host)."""
    exc = Exception(
        '500 Server Error for http+docker://localhost/v1.54/images/create'
        '?tag=latest&fromImage=ghcr.io%2Fkulik-labs-development%2Feepy-host-happyfox: '
        'Internal Server Error ("error from registry: unauthorized unauthorized")'
    )
    err = bridge._spawn_error_bridge(exc, "ghcr.io/kulik-labs-development/eepy-host-happyfox:latest", "deploy_eepy-sidecars")
    assert "unauthorized" in str(err)
    assert "private registry package" in str(err)
    assert "docker login ghcr.io" in str(err)
    assert "read:packages" in str(err)
    assert "Change visibility" in str(err)


def test_spawn_error_generic_keeps_daemon_message(bridge):
    """A non-registry failure must surface the daemon's first line, not just
    the exception class name (the old '(APIError)' dead end)."""
    exc = Exception("409 Conflict: port is already allocated")
    err = bridge._spawn_error_bridge(exc, "img:latest", None)
    assert "409 Conflict" in str(err)
    assert "APIError" not in str(err)


def test_spawn_error_network_not_found(bridge):
    exc = Exception('network "deploy_eepy-sidecars" not found')
    err = bridge._spawn_error_bridge(exc, "img:latest", "deploy_eepy-sidecars")
    assert "eepy-sidecars" in str(err)
    assert "not found" in str(err)
