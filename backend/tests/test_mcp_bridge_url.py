"""Tests for url-instance support (hosted remote MCP upstreams).

Url templates (the Cloudflare MCP seeds) carry no sidecar image or command:
the bridge registers the admin-registered URL and dials it with the user's
per-request headers. The SSRF guard itself is covered in
test_security_audit.py; the transport tests below patch it to allow loopback
only and run a local fake streamable-HTTP MCP server (TLS, self-signed — the
bridge requires https://).
"""

import asyncio
import ipaddress
import json
import logging
import socket
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

FAKE_URL_TOKEN = "fake-url-token-0987654321"


def _url_template(runtime_config, template_id="fake-url-mcp"):
    from models.mcp_models import MCPTemplate

    return MCPTemplate(
        id=template_id,
        name="Fake URL MCP",
        description="Test-only url template (hosted upstream, no sidecar).",
        runtime="mcp-server",
        runtime_config=runtime_config,
        approved_by_admin=True,
        enabled_global=True,
    )


# ---------------------------------------------------------------------------
# _runtime_config url branch + the registration guard (no server needed)
# ---------------------------------------------------------------------------
def test_runtime_config_url_branch_accepts_https_without_image_or_command():
    from api import mcp_bridge

    cfg = {"url": "https://example.com", "endpoint": "/mcp"}
    assert mcp_bridge._runtime_config(_url_template(cfg)) == cfg


def test_runtime_config_url_branch_rejects_plain_http():
    from api import mcp_bridge

    with pytest.raises(mcp_bridge.BridgeError) as exc:
        mcp_bridge._runtime_config(_url_template({"url": "http://example.com/mcp"}))
    assert "https" in str(exc.value)


def test_runtime_config_non_dict_still_rejected():
    from api import mcp_bridge

    with pytest.raises(mcp_bridge.BridgeError):
        mcp_bridge._runtime_config(_url_template("not-a-dict"))


def test_spawn_url_instance_rejects_non_public_upstream():
    """The full guard runs once per registration. IP literals are
    range-checked without DNS, so these are deterministic and network-free."""
    from api import mcp_bridge

    for bad in ("https://127.0.0.1:8443", "https://10.1.2.3",
                "https://169.254.169.254", "https://[::1]:8000"):
        with pytest.raises(mcp_bridge.BridgeError) as exc:
            asyncio.run(mcp_bridge.spawn_instance(
                _url_template({"url": bad, "endpoint": "/mcp"}), "key-" + bad, {}))
        assert "Template upstream rejected" in str(exc.value)
        assert "non-public" in str(exc.value)

    # The cheap scheme check fires in _runtime_config, before the guard.
    with pytest.raises(mcp_bridge.BridgeError) as exc:
        asyncio.run(mcp_bridge.spawn_instance(
            _url_template({"url": "http://93.184.216.34/mcp"}), "key-http", {}))
    assert "must use https" in str(exc.value)


# ---------------------------------------------------------------------------
# Local fake streamable-HTTP MCP server (TLS, self-signed)
# ---------------------------------------------------------------------------
def _self_signed_cert(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    d = tmp_path_factory.mktemp("url-tls")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = d / "cert.pem"
    key_path = d / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    return cert_path, key_path


class _AuthGate:
    """Records the Authorization header and 401s anything that does not carry
    the expected bearer — the fake upstream's whole auth model."""

    def __init__(self, app, expected_auth):
        self.app = app
        self.expected_auth = expected_auth
        self.seen_auth = []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        auth = None
        for k, v in scope["headers"]:
            if k == b"authorization":
                auth = v.decode()
        self.seen_auth.append(auth)
        if auth != self.expected_auth:
            body = json.dumps({"error": "unauthorized"}).encode()
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


@pytest.fixture(scope="module")
def fake_url_server(tmp_path_factory):
    """Fake streamable-HTTP MCP server on 127.0.0.1 (self-signed TLS).

    Yields (base_url, cert_path, gate).
    """
    import uvicorn
    from mcp.server.fastmcp import FastMCP

    cert_path, key_path = _self_signed_cert(tmp_path_factory)

    mcp = FastMCP("fake-url-mcp", streamable_http_path="/mcp")

    @mcp.tool()
    def list_items(limit: int = 3) -> str:
        return "items=" + ",".join(f"item-{i}" for i in range(1, limit + 1))

    @mcp.tool()
    def bad_item() -> str:
        raise RuntimeError("upstream exploded")

    gate = _AuthGate(mcp.streamable_http_app(), f"Bearer {FAKE_URL_TOKEN}")

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    # loop="asyncio" on purpose (same reason as test_mcp_bridge's http-server
    # test): the default "auto" installs uvloop's policy GLOBALLY and never
    # restores it; uvloop's policy has no child watcher, so any LATER
    # subprocess spawn on the suite's plain-asyncio portal loop dies with
    # NotImplementedError deep in anyio.open_process.
    config = uvicorn.Config(gate, host="127.0.0.1", port=port,
                            ssl_certfile=str(cert_path), ssl_keyfile=str(key_path),
                            log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("fake url server did not start")
        time.sleep(0.05)

    yield f"https://127.0.0.1:{port}", cert_path, gate

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def url_env(monkeypatch, fake_url_server):
    """Guard patched to loopback-only + httpx trusting the test cert, and a
    url template shaped like the Cloudflare seeds."""
    from urllib.parse import urlparse

    import httpx
    from fastapi import HTTPException

    from api import mcp_bridge

    base_url, cert_path, gate = fake_url_server

    def loopback_guard(url):
        if not str(url).lower().startswith("https://"):
            raise HTTPException(status_code=400, detail="Upstream host must use https.")
        host = urlparse(url).hostname or ""
        if host not in ("127.0.0.1", "localhost"):
            raise HTTPException(status_code=400, detail="test guard: non-loopback not allowed")

    real_async_client = httpx.AsyncClient

    def trusting_client(*args, **kwargs):
        kwargs["verify"] = str(cert_path)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(mcp_bridge, "assert_public_upstream", loopback_guard)
    monkeypatch.setattr(httpx, "AsyncClient", trusting_client)

    template = _url_template({
        "url": base_url,
        "endpoint": "/mcp",
        "env_mapping": {"FAKE_URL_TOKEN": "CF_API_TOKEN"},
        "headers": {"Authorization": "Bearer {{CF_API_TOKEN}}"},
    })
    return {"template": template, "base_url": base_url, "gate": gate}


# ---------------------------------------------------------------------------
# Transport: register -> tools/call through the bridge -> kill
# ---------------------------------------------------------------------------
def test_url_instance_lifecycle_roundtrip(url_env):
    from api import mcp_bridge
    from database import User

    template = url_env["template"]
    gate = url_env["gate"]
    creds = {"FAKE_URL_TOKEN": FAKE_URL_TOKEN}
    user = User(id=987654, username="url-lifecycle-test",
                email="url-lifecycle-test@example.com")
    cfg = mcp_bridge._runtime_config(template)
    env = mcp_bridge._sidecar_env(cfg, mcp_bridge.map_env(cfg, creds))
    headers = mcp_bridge._sidecar_headers(cfg, env)
    key = mcp_bridge.key_for(user.id, template.id, creds)

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Capture()
    mcp_bridge.logger.addHandler(handler)

    async def run():
        # Register: a url instance records the URL; nothing is spawned.
        inst = await mcp_bridge.spawn_instance(template, key, env, headers=headers)
        assert inst.kind == "url"
        assert inst.url == url_env["base_url"] + "/mcp"
        assert inst.headers == {"Authorization": f"Bearer {FAKE_URL_TOKEN}"}
        assert mcp_bridge._REGISTRY[key] is inst

        # tools/call through the bridge (acquire reuses the live instance).
        data, is_error = await mcp_bridge.bridge_call(
            user, template, creds, "list_items", {"limit": 2})
        assert is_error is False
        assert data == "items=item-1,item-2"
        # The user's own token reached the upstream as the bearer header.
        assert f"Bearer {FAKE_URL_TOKEN}" in gate.seen_auth

        # Upstream errors surface as isError, not as raised exceptions.
        data, is_error = await mcp_bridge.bridge_call(user, template, creds, "bad_item", {})
        assert is_error is True
        assert "upstream exploded" in data

        # Kill pops the registry without side effects.
        mcp_bridge.kill_instance(key)
        assert key not in mcp_bridge._REGISTRY

    try:
        asyncio.run(run())
    finally:
        mcp_bridge.logger.removeHandler(handler)

    # The user's token must never appear in the bridge logs.
    assert all(FAKE_URL_TOKEN not in r for r in records)


def test_url_instance_endpoint_query_is_preserved(url_env):
    """?codemode=false (the cloudflare-full seed) must survive the
    base+endpoint concat."""
    from api import mcp_bridge

    template = _url_template({
        "url": url_env["base_url"],
        "endpoint": "/mcp?codemode=false",
        "env_mapping": {"FAKE_URL_TOKEN": "CF_API_TOKEN"},
        "headers": {"Authorization": "Bearer {{CF_API_TOKEN}}"},
    })
    creds = {"FAKE_URL_TOKEN": FAKE_URL_TOKEN}

    async def run():
        cfg = mcp_bridge._runtime_config(template)
        env = mcp_bridge._sidecar_env(cfg, mcp_bridge.map_env(cfg, creds))
        headers = mcp_bridge._sidecar_headers(cfg, env)
        inst = await mcp_bridge.spawn_instance(template, "key-query", env, headers=headers)
        try:
            assert inst.url == url_env["base_url"] + "/mcp?codemode=false"
        finally:
            mcp_bridge.kill_instance("key-query")

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Seed shape + the connection-test route fallback (full app, throwaway SQLite)
# ---------------------------------------------------------------------------
def test_seeded_cloudflare_templates_shape(client):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == "cloudflare").first()
        f = db.query(MCPTemplate).filter(MCPTemplate.id == "cloudflare-full").first()
    finally:
        db.close()
    assert t is not None and f is not None, "cloudflare templates were not seeded"
    for x in (t, f):
        assert x.approved_by_admin and x.enabled_global
        assert x.runtime == "mcp-server"
        assert x.image_tag is None, "url templates have no sidecar image"
        assert x.repo_url == "https://github.com/cloudflare/mcp"
        assert x.config_schema["required"] == ["CLOUDFLARE_API_TOKEN"]
        cfg = x.runtime_config
        assert cfg["url"] == "https://mcp.cloudflare.com"
        assert cfg["env_mapping"] == {"CLOUDFLARE_API_TOKEN": "CF_API_TOKEN"}
        assert cfg["headers"] == {"Authorization": "Bearer {{CF_API_TOKEN}}"}
        assert "image" not in cfg and "command" not in cfg
        assert "test_tool" not in cfg, "the test route falls back to tools/list"
    assert t.runtime_config["endpoint"] == "/mcp"
    assert t.runtime_config["tool_names"] == ["search", "execute"]
    assert f.runtime_config["endpoint"] == "/mcp?codemode=false"
    assert "tool_names" not in f.runtime_config, "2,594 tools: admin discovery populates them"


def test_cloudflare_header_resolves_the_users_token(client):
    from api import mcp_bridge
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == "cloudflare").first()
    finally:
        db.close()
    cfg = mcp_bridge._runtime_config(t)
    env = mcp_bridge.map_env(cfg, {"CLOUDFLARE_API_TOKEN": "sekrit-token-123"})
    assert mcp_bridge._sidecar_headers(cfg, env) == {"Authorization": "Bearer sekrit-token-123"}


def test_connection_test_fallback_discovers_tools(client, auth_user, url_env):
    """POST /config/cloudflare/test with no test_tool falls back to a
    handshake + tools/list. Point the seeded template at the local fake for
    the duration of the test, then restore it."""
    from api import mcp_bridge
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    token = auth_user["token"]
    gate = url_env["gate"]

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == "cloudflare").first()
        original = dict(t.runtime_config)
        t.runtime_config = {**original, "url": url_env["base_url"]}
        db.commit()
    finally:
        db.close()

    try:
        r = client.post("/api/mcp/config/register",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"template_id": "cloudflare",
                              "credentials_json": {"CLOUDFLARE_API_TOKEN": FAKE_URL_TOKEN}})
        assert r.status_code == 200, r.text

        r = client.post("/api/mcp/config/cloudflare/test",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert "tools discovered" in body["detail"]
        assert f"Bearer {FAKE_URL_TOKEN}" in gate.seen_auth

        # A bad token 401s at the upstream's gate -> failed, not a 5xx.
        r = client.post("/api/mcp/config/register",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"template_id": "cloudflare",
                              "credentials_json": {"CLOUDFLARE_API_TOKEN": "wrong-token"}})
        assert r.status_code == 200, r.text
        r = client.post("/api/mcp/config/cloudflare/test",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"
    finally:
        db = SessionLocal()
        try:
            t = db.query(MCPTemplate).filter(MCPTemplate.id == "cloudflare").first()
            t.runtime_config = original
            db.commit()
        finally:
            db.close()
        mcp_bridge.shutdown_all_instances()
