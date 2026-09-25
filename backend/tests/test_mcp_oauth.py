"""Hosted remote MCP: per-user OAuth login class (code + PKCE, Fernet tokens,
auto-refresh). The token endpoint is a fake TLS ASGI server on loopback; the
SSRF guard and httpx.Client are monkeypatched to trust it (same pattern as
test_mcp_bridge_url's url_env fixture)."""

import asyncio
import ipaddress
import json
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException

from api import mcp_oauth
from auth import create_access_token

TEMPLATE_ID = "fake-oauth-test"
PARTIAL_ID = "fake-oauth-partial"
CLIENT_ID = "test-client-1"
GOOD_CODE = "test-code"


# ---------------------------------------------------------------------------
# Local fake OAuth token endpoint (TLS, self-signed)
# ---------------------------------------------------------------------------
REFRESH_STATE = {"count": 0}


def _self_signed_cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("oauth-tls")
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


async def token_app(scope, receive, send):
    if scope["type"] != "http":
        return
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break
    form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
    if form.get("grant_type") == "authorization_code":
        if form.get("code") != GOOD_CODE or not form.get("code_verifier"):
            await send({"type": "http.response.start", "status": 400,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body",
                        "body": json.dumps({"error": "invalid_grant"}).encode()})
            return
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body",
                    "body": json.dumps({"access_token": "tok-1",
                                        "refresh_token": "rtok-1",
                                        "expires_in": 3600}).encode()})
        return
    if form.get("grant_type") == "refresh_token":
        if form.get("refresh_token") != "rtok-1":
            await send({"type": "http.response.start", "status": 400,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body",
                        "body": json.dumps({"error": "invalid_grant",
                                            "error_description": "bad refresh token"}).encode()})
            return
        REFRESH_STATE["count"] += 1
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body",
                    "body": json.dumps({"access_token": f"tok-{REFRESH_STATE['count'] + 1}",
                                        "refresh_token": "rtok-1",
                                        "expires_in": 3600}).encode()})
        return
    await send({"type": "http.response.start", "status": 400,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body",
                "body": json.dumps({"error": "unsupported_grant_type"}).encode()})


@pytest.fixture(scope="module")
def oauth_server(tmp_path_factory):
    """Fake OAuth token endpoint on 127.0.0.1 (self-signed TLS)."""
    import uvicorn

    cert_path, key_path = _self_signed_cert(tmp_path_factory)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(token_app, host="127.0.0.1", port=port,
                            ssl_certfile=str(cert_path), ssl_keyfile=str(key_path),
                            log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("fake oauth server did not start")
        time.sleep(0.05)

    yield {"base": f"https://127.0.0.1:{port}", "cert": cert_path}

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def oauth_template(client):
    """An approved mcp-server template whose runtime_config.oauth points at the
    fake token endpoint."""
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    def _spec(tid, client_id, complete=True):
        return MCPTemplate(
            id=tid,
            name=f"Fake OAuth {tid}",
            description="Test-only OAuth login template.",
            config_schema={},
            runtime="mcp-server",
            runtime_config={
                "url": "https://mcp.fake-oauth.example",
                "endpoint": "/mcp",
                "env_mapping": {"access_token": "FAKE_OAUTH_TOKEN"},
                "headers": {"Authorization": "Bearer {{FAKE_OAUTH_TOKEN}}"},
                "oauth": {
                    "authorize_endpoint": "https://auth.fake-oauth.example/authorize",
                    "token_endpoint": None,  # patched below with the real loopback URL
                    "client_id": client_id,
                    "scopes": "openid offline_access",
                    "auth_label": "FakeOAuth",
                },
            },
            approved_by_admin=True,
            enabled_global=True,
        )

    db = SessionLocal()
    try:
        for tid in (TEMPLATE_ID, PARTIAL_ID):
            existing = db.query(MCPTemplate).filter(MCPTemplate.id == tid).first()
            if existing:
                db.delete(existing)
                db.commit()
        db.add(_spec(TEMPLATE_ID, CLIENT_ID))
        db.add(_spec(PARTIAL_ID, ""))
        db.commit()
    finally:
        db.close()
    return TEMPLATE_ID


@pytest.fixture
def oauth_env(monkeypatch, oauth_server, client, oauth_template):
    """Guard patched to loopback-only + sync httpx.Client trusting the test
    cert + the template's token endpoint pointed at the fake server."""
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    base, cert = oauth_server["base"], oauth_server["cert"]

    def loopback_guard(url):
        if not str(url).lower().startswith("https://"):
            raise HTTPException(status_code=400, detail="Upstream host must use https.")
        host = urlparse(url).hostname or ""
        # loopback = the real token endpoint; fake-oauth.example = the
        # authorize endpoint (never dialed by the backend, browser redirect).
        if host not in ("127.0.0.1", "localhost") and not host.endswith("fake-oauth.example"):
            raise HTTPException(status_code=400, detail="test guard: host not allowed")

    real_client = httpx.Client

    def trusting_client(*args, **kwargs):
        kwargs["verify"] = str(cert)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(mcp_oauth, "assert_public_upstream", loopback_guard)
    monkeypatch.setattr(httpx, "Client", trusting_client)
    mcp_oauth._guarded_endpoints.clear()

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == TEMPLATE_ID).first()
        rc = dict(t.runtime_config)
        rc = {**rc, "oauth": {**rc["oauth"], "token_endpoint": f"{base}/token"}}
        t.runtime_config = rc
        db.commit()
    finally:
        db.close()
    yield {"base": base, "cert": cert, "template_id": TEMPLATE_ID}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_template(tid: str):
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == tid).first()
        db.expunge(t)
        return t
    finally:
        db.close()


def _load_user(username: str):
    from database import SessionLocal, User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        db.expunge(u)
        return u
    finally:
        db.close()


def _config_row(tid: str, username: str):
    from database import SessionLocal, User
    from models.mcp_models import UserMCPConfig

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        row = (db.query(UserMCPConfig)
               .filter(UserMCPConfig.owner_id == user.id,
                       UserMCPConfig.template_name == tid)
               .first())
        if row:
            db.expunge(row)
        return row
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Authorize URL construction (PKCE S256 + state JWT)
# ---------------------------------------------------------------------------
def test_build_authorize_url_pkce_and_state(oauth_env, auth_user):
    import base64
    import hashlib

    template = _load_template(TEMPLATE_ID)
    user = _load_user(auth_user["username"])  # any real user; only the int id matters
    url = mcp_oauth.build_authorize_url(template, user.id, "http://testserver")
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://auth.fake-oauth.example/authorize?")
    assert q["response_type"] == "code"
    assert q["client_id"] == CLIENT_ID
    assert q["redirect_uri"] == "http://testserver/api/mcp/oauth/callback"
    assert q["scope"] == "openid offline_access"
    assert q["code_challenge_method"] == "S256"

    state = mcp_oauth.decode_state(q["state"])
    assert state is not None
    assert state["sub"] == str(user.id)
    assert state["tid"] == TEMPLATE_ID
    verifier = state["cv"]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert q["code_challenge"] == expected


# ---------------------------------------------------------------------------
# 2. Full callback roundtrip (public endpoint, state JWT = the auth)
# ---------------------------------------------------------------------------
def test_callback_roundtrip_stores_fernet_tokens(client, auth_user, oauth_env):
    template = _load_template(TEMPLATE_ID)
    user = _load_user(auth_user["username"])
    url = mcp_oauth.build_authorize_url(template, user.id, "http://testserver")
    state = parse_qs(urlparse(url).query)["state"][0]

    r = client.get(f"/api/mcp/oauth/callback?code={GOOD_CODE}&state={state}")
    assert r.status_code == 200, r.text
    assert "Connected" in r.text

    # The connection shows up in the user's config list.
    r = client.get("/api/mcp/config/list",
                   headers={"Authorization": f"Bearer {auth_user['token']}"})
    assert r.status_code == 200
    row = next((c for c in r.json() if c["template_name"] == TEMPLATE_ID), None)
    assert row is not None and row["is_active"] is True

    # The stored blob is Fernet ciphertext, not plaintext JSON, and decrypts
    # to the exchanged tokens.
    from utils.crypto import decrypt_credentials

    raw = _config_row(TEMPLATE_ID, auth_user["username"])
    assert raw is not None
    assert b'"access_token"' not in raw.credentials_json.encode()
    creds = decrypt_credentials(raw.credentials_json)
    assert creds["access_token"] == "tok-1"
    assert creds["refresh_token"] == "rtok-1"
    assert int(creds["expires_at"]) > time.time()


# ---------------------------------------------------------------------------
# 3+4. Bad / expired state -> 400, nothing stored
# ---------------------------------------------------------------------------
def test_callback_bad_state_rejected(client, oauth_env):
    r = client.get("/api/mcp/oauth/callback?code=test-code&state=not-a-token")
    assert r.status_code == 400
    assert "invalid or expired" in r.text.lower()


def test_callback_expired_state_rejected(client, oauth_env):
    bad_state = create_access_token(
        {"sub": "1", "tid": TEMPLATE_ID, "cv": "v"},
        expires_delta=timedelta(seconds=-1),
    )
    r = client.get(f"/api/mcp/oauth/callback?code={GOOD_CODE}&state={bad_state}")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 5-9. ensure_fresh_token: refresh lifecycle
# ---------------------------------------------------------------------------
def _seed_tokens(tid, username, creds: dict) -> None:
    template = _load_template(tid)
    user = _load_user(username)
    mcp_oauth.store_tokens(user.id, template, creds)
def _clear_config(tid, username) -> None:
    """Delete the user's config row (a clean slate for merge-semantics tests)."""
    from database import SessionLocal, User
    from models.mcp_models import UserMCPConfig

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        row = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user.id,
                    UserMCPConfig.template_name == tid)
            .first()
        )
        if row:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def test_ensure_fresh_token_refreshes_and_persists(client, auth_user, oauth_env):
    before = REFRESH_STATE["count"]
    _seed_tokens(TEMPLATE_ID, auth_user["username"], {
        "access_token": "tok-stale",
        "refresh_token": "rtok-1",
        "expires_at": str(int(time.time()) - 10),
    })
    user = _load_user(auth_user["username"])
    template = _load_template(TEMPLATE_ID)
    fresh = asyncio.run(mcp_oauth.ensure_fresh_token(
        user, template, {"access_token": "tok-stale", "expires_at": str(int(time.time()) - 10)}))
    assert fresh is not None
    assert fresh["access_token"] == f"tok-{before + 2}"
    assert REFRESH_STATE["count"] == before + 1
    row = _config_row(TEMPLATE_ID, auth_user["username"])
    from utils.crypto import decrypt_credentials
    assert decrypt_credentials(row.credentials_json)["access_token"] == fresh["access_token"]


def test_ensure_fresh_token_fresh_blob_is_noop(client, auth_user, oauth_env):
    before = REFRESH_STATE["count"]
    _seed_tokens(TEMPLATE_ID, auth_user["username"], {
        "access_token": "tok-1",
        "refresh_token": "rtok-1",
        "expires_at": str(int(time.time()) + 3600),
    })
    user = _load_user(auth_user["username"])
    template = _load_template(TEMPLATE_ID)
    assert asyncio.run(mcp_oauth.ensure_fresh_token(
        user, template, {"access_token": "tok-1", "expires_at": str(int(time.time()) + 3600)})) is None
    assert REFRESH_STATE["count"] == before


def test_ensure_fresh_token_expired_without_refresh_token_409(client, auth_user, oauth_env):
    # Clean state: store_tokens now MERGES into the blob, and an earlier test
    # (the callback roundtrip) left a refresh_token in this user's row.
    _clear_config(TEMPLATE_ID, auth_user["username"])
    _seed_tokens(TEMPLATE_ID, auth_user["username"], {
        "access_token": "tok-stale",
        "expires_at": str(int(time.time()) - 10),
    })
    user = _load_user(auth_user["username"])
    template = _load_template(TEMPLATE_ID)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mcp_oauth.ensure_fresh_token(
            user, template, {"access_token": "tok-stale", "expires_at": str(int(time.time()) - 10)}))
    assert exc.value.status_code == 409


def test_ensure_fresh_token_bad_refresh_token_409(client, auth_user, oauth_env):
    _seed_tokens(TEMPLATE_ID, auth_user["username"], {
        "access_token": "tok-stale",
        "refresh_token": "rtok-wrong",
        "expires_at": str(int(time.time()) - 10),
    })
    user = _load_user(auth_user["username"])
    template = _load_template(TEMPLATE_ID)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mcp_oauth.ensure_fresh_token(
            user, template, {"access_token": "tok-stale",
                             "refresh_token": "rtok-wrong",
                             "expires_at": str(int(time.time()) - 10)}))
    assert exc.value.status_code == 409


def test_ensure_fresh_token_non_oauth_template_is_noop(client, auth_user):
    from conftest import FAKE_CREDS

    user = _load_user(auth_user["username"])
    template = _load_template("fake-mcp-test")
    assert asyncio.run(mcp_oauth.ensure_fresh_token(
        user, template, dict(FAKE_CREDS))) is None


# ---------------------------------------------------------------------------
# 10. Seed shape: Uber + Uber Eats templates (client_id from env, absent here)
# ---------------------------------------------------------------------------
def test_seeded_uber_templates_shape():
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    db = SessionLocal()
    try:
        rows = {t.id: t for t in db.query(MCPTemplate).filter(
            MCPTemplate.id.in_(["uber", "ubereats"])).all()}
    finally:
        db.close()

    assert set(rows) == {"uber", "ubereats"}
    for tid in rows:
        t = rows[tid]
        # No UBER_MCP_CLIENT_ID in the test env -> seeded but not approved.
        assert t.approved_by_admin is False
        assert t.enabled_global is True
        assert t.runtime == "mcp-server"
        rc = t.runtime_config
        assert rc["env_mapping"] == {"access_token": "UBER_ACCESS_TOKEN"}
        assert rc["headers"] == {"Authorization": "Bearer {{UBER_ACCESS_TOKEN}}"}
        assert rc["oauth"]["authorize_endpoint"] == "https://auth.uber.com/oauth/v2/universal/authorize"
        assert rc["oauth"]["token_endpoint"] == "https://auth.uber.com/oauth/v2/token"
        assert rc["oauth"]["client_id"] == ""
    assert rows["uber"].runtime_config["url"] == "https://mcp.uber.com"
    assert rows["uber"].runtime_config["endpoint"] == "/claude/rides-3p/mcp"
    assert rows["uber"].runtime_config["oauth"]["scopes"] == \
        "openid offline_access profile email 3p.rides.mcp"
    assert rows["ubereats"].runtime_config["url"] == "https://mcp.ubereats.com"
    assert rows["ubereats"].runtime_config["endpoint"] == "/eats-claude/mcp"
    assert rows["ubereats"].runtime_config["oauth"]["scopes"] == \
        "openid offline_access profile email eats.3p.mcp"


# ---------------------------------------------------------------------------
# 11. Authorize route: 400 not-an-oauth / 503 missing client_id / 200 url
# ---------------------------------------------------------------------------
def test_oauth_authorize_route(client, auth_user, oauth_env):
    h = {"Authorization": f"Bearer {auth_user['token']}"}

    # A template with no oauth section at all -> 400.
    r = client.post("/api/mcp/config/fake-mcp-test/oauth/authorize", headers=h)
    assert r.status_code == 400

    # An oauth section without a client_id -> 503 (not fully configured).
    r = client.post(f"/api/mcp/config/{PARTIAL_ID}/oauth/authorize", headers=h)
    assert r.status_code == 503

    # Unknown template -> 404.
    r = client.post("/api/mcp/config/nope/oauth/authorize", headers=h)
    assert r.status_code == 404

    # Complete config -> 200 with the provider URL (client_id + state present).
    r = client.post(f"/api/mcp/config/{TEMPLATE_ID}/oauth/authorize", headers=h)
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert CLIENT_ID in url
    assert "state=" in url
    assert url.startswith("https://auth.fake-oauth.example/authorize?")
