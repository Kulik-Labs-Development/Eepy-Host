"""Microsoft 365 (work/school): Microsoft's hosted MCP Server for Enterprise.

Per-tenant public (PKCE) client: the tenant's IT admin registers one app and
every user pastes its client ID (CLIENT_ID). The token flow resolves the
client_id from the user's stored config (client_id_field), and the callback
MERGES the tokens into the same blob so CLIENT_ID survives. The refresh path
resolves the client_id from the blob too. The token endpoint is a fake TLS
server on loopback (same pattern as test_mcp_oauth)."""

import asyncio
import base64
import hashlib
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
from utils.crypto import decrypt_credentials

TEMPLATE_ID = "microsoft-365"
CLIENT_ID = "tenant-app-1"
GOOD_CODE = "msft-code"
TOKEN_SCOPE = "api://e8c77dc2-69b3-43f4-bc51-3213c9d915b4/.default"

TOKEN_STATE = {"last_client_id": None, "refresh_count": 0}


def _self_signed_cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("m365-tls")
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
    TOKEN_STATE["last_client_id"] = form.get("client_id")
    if form.get("grant_type") == "authorization_code":
        if form.get("code") != GOOD_CODE or not form.get("code_verifier") \
                or form.get("client_id") != CLIENT_ID:
            await send({"type": "http.response.start", "status": 400,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body",
                        "body": json.dumps({"error": "invalid_grant"}).encode()})
            return
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body",
                    "body": json.dumps({"access_token": "msft-1",
                                        "refresh_token": "msft-rt",
                                        "expires_in": 3600,
                                        "scope": TOKEN_SCOPE}).encode()})
        return
    if form.get("grant_type") == "refresh_token":
        if form.get("refresh_token") != "msft-rt" or form.get("client_id") != CLIENT_ID:
            await send({"type": "http.response.start", "status": 400,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body",
                        "body": json.dumps({"error": "invalid_grant",
                                            "error_description": "bad client"}).encode()})
            return
        TOKEN_STATE["refresh_count"] += 1
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body",
                    "body": json.dumps({"access_token": f"msft-{TOKEN_STATE['refresh_count'] + 1}",
                                        "refresh_token": "msft-rt",
                                        "expires_in": 3600}).encode()})
        return
    await send({"type": "http.response.start", "status": 400,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body",
                "body": json.dumps({"error": "unsupported_grant_type"}).encode()})


@pytest.fixture(scope="module")
def oauth_server(tmp_path_factory):
    """Fake token endpoint on 127.0.0.1 (self-signed TLS)."""
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
            raise RuntimeError("fake m365 oauth server did not start")
        time.sleep(0.05)

    yield {"base": f"https://127.0.0.1:{port}", "cert": cert_path}

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def m365_env(monkeypatch, oauth_server):
    """Guard patched to loopback + login.microsoftonline.com (the authorize
    endpoint is never dialed by the backend), httpx trusting the test cert,
    and the seeded template's token endpoint pointed at the fake server."""
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    base, cert = oauth_server["base"], oauth_server["cert"]

    def guard(url):
        if not str(url).lower().startswith("https://"):
            raise HTTPException(status_code=400, detail="Upstream host must use https.")
        host = urlparse(url).hostname or ""
        if host not in ("127.0.0.1", "localhost") and host != "login.microsoftonline.com":
            raise HTTPException(status_code=400, detail="test guard: host not allowed")

    real_client = httpx.Client

    def trusting_client(*args, **kwargs):
        kwargs["verify"] = str(cert)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(mcp_oauth, "assert_public_upstream", guard)
    monkeypatch.setattr(httpx, "Client", trusting_client)
    mcp_oauth._guarded_endpoints.clear()

    db = SessionLocal()
    try:
        t = db.query(MCPTemplate).filter(MCPTemplate.id == TEMPLATE_ID).first()
        assert t is not None, "microsoft-365 template was not seeded"
        rc = dict(t.runtime_config)
        rc = {**rc, "oauth": {**rc["oauth"], "token_endpoint": f"{base}/token"}}
        t.runtime_config = rc
        db.commit()
    finally:
        db.close()
    yield {"base": base, "cert": cert}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user(client):
    """A fresh signed-in user (the rate limiter resets per test)."""
    import random

    username = f"m365test{random.randint(100000, 999999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "m365-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "m365-password-1"})
    assert r.status_code == 200, r.text
    return {"token": r.json()["access_token"], "username": username}


def _register(client, token, creds):
    return client.post(
        "/api/mcp/config/register",
        headers={"Authorization": f"Bearer {token}"},
        json={"template_id": TEMPLATE_ID, "credentials_json": creds},
    )


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


def _blob(username: str):
    from database import SessionLocal, User
    from models.mcp_models import UserMCPConfig

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        row = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user.id, UserMCPConfig.template_name == TEMPLATE_ID)
            .first()
        )
        if row:
            db.expunge(row)
        return row
    finally:
        db.close()


def _creds(username: str) -> dict:
    row = _blob(username)
    assert row is not None
    return decrypt_credentials(row.credentials_json)


# ---------------------------------------------------------------------------
# 1. Seed shape: per-tenant public PKCE client, no client_secret
# ---------------------------------------------------------------------------
def test_seeded_template_shape(client):
    t = _load_template(TEMPLATE_ID)
    assert t is not None, "microsoft-365 template was not seeded"
    assert t.approved_by_admin is True
    assert t.enabled_global is True
    assert t.runtime == "mcp-server"
    rc = t.runtime_config
    assert rc["url"] == "https://mcp.svc.cloud.microsoft"
    assert rc["endpoint"] == "/enterprise"
    assert rc["env_mapping"] == {"access_token": "M365_ACCESS_TOKEN"}
    assert rc["headers"] == {"Authorization": "Bearer {{M365_ACCESS_TOKEN}}"}
    o = rc["oauth"]
    assert o["authorize_endpoint"] == \
        "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
    assert o["token_endpoint"].endswith("/organizations/oauth2/v2.0/token")
    assert o["client_id"] == ""
    assert o["client_id_field"] == "CLIENT_ID"
    assert o["scopes"] == TOKEN_SCOPE
    assert "client_secret" not in o
    schema = t.config_schema
    assert schema["properties"]["CLIENT_ID"]["type"] == "string"
    assert schema["required"] == ["CLIENT_ID"]
    assert t.repo_url == "https://github.com/microsoft/enterprisemcp"


def test_template_list_surfaces_oauth(client):
    u = _user(client)
    r = client.get("/api/mcp/templates/list",
                   headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200, r.text
    row = next((t for t in r.json() if t["id"] == TEMPLATE_ID), None)
    assert row is not None
    assert row["auth_mode"] == "oauth"
    assert row["config_schema"]["required"] == ["CLIENT_ID"]


# ---------------------------------------------------------------------------
# 2. Authorize: 503 without the tenant client ID; the user's CLIENT_ID in the
#    URL (with PKCE S256 + state) once stored
# ---------------------------------------------------------------------------
def test_authorize_requires_client_id(client):
    u = _user(client)
    r = client.post(f"/api/mcp/config/{TEMPLATE_ID}/oauth/authorize",
                    headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 503
    assert "CLIENT_ID" in r.json()["detail"]


def test_authorize_url_uses_user_client_id(client, m365_env):
    u = _user(client)
    r = _register(client, u["token"], {"CLIENT_ID": CLIENT_ID})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/mcp/config/{TEMPLATE_ID}/oauth/authorize",
                    headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith(
        "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?")
    assert q["client_id"] == CLIENT_ID
    assert q["scope"] == TOKEN_SCOPE
    assert q["response_type"] == "code"
    assert q["redirect_uri"] == "http://testserver/api/mcp/oauth/callback"
    assert q["code_challenge_method"] == "S256"

    state = mcp_oauth.decode_state(q["state"])
    assert state is not None
    assert state["tid"] == TEMPLATE_ID
    verifier = state["cv"]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert q["code_challenge"] == expected


# ---------------------------------------------------------------------------
# 3. Callback roundtrip: tokens merged into the blob, CLIENT_ID survives,
#    the tenant client_id reached the token endpoint
# ---------------------------------------------------------------------------
def test_callback_roundtrip_merges_client_id(client, m365_env):
    u = _user(client)
    r = _register(client, u["token"], {"CLIENT_ID": CLIENT_ID})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/mcp/config/{TEMPLATE_ID}/oauth/authorize",
                    headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]

    r = client.get(f"/api/mcp/oauth/callback?code={GOOD_CODE}&state={state}")
    assert r.status_code == 200, r.text
    assert "Connected" in r.text

    creds = _creds(u["username"])
    assert creds["CLIENT_ID"] == CLIENT_ID  # the merge kept the tenant config
    assert creds["access_token"] == "msft-1"
    assert creds["refresh_token"] == "msft-rt"
    assert int(creds["expires_at"]) > time.time()
    assert TOKEN_STATE["last_client_id"] == CLIENT_ID  # the token request carried it

    # The connection shows up in the user's config list.
    r = client.get("/api/mcp/config/list",
                   headers={"Authorization": f"Bearer {u['token']}"})
    row = next((c for c in r.json() if c["template_name"] == TEMPLATE_ID), None)
    assert row is not None and row["is_active"] is True


def test_edit_register_blank_client_id_keeps_stored(client, m365_env):
    u = _user(client)
    r = _register(client, u["token"], {"CLIENT_ID": CLIENT_ID})
    assert r.status_code == 200, r.text
    r = _register(client, u["token"], {"CLIENT_ID": ""})
    assert r.status_code == 200, r.text
    assert _creds(u["username"])["CLIENT_ID"] == CLIENT_ID


# ---------------------------------------------------------------------------
# 4. Refresh: the client_id is resolved from the stored blob (per-tenant),
#    and a missing one 409s cleanly
# ---------------------------------------------------------------------------
def test_ensure_fresh_token_resolves_client_id_from_blob(client, m365_env):
    u = _user(client)
    r = _register(client, u["token"], {"CLIENT_ID": CLIENT_ID})
    assert r.status_code == 200, r.text
    user = _load_user(u["username"])
    template = _load_template(TEMPLATE_ID)
    mcp_oauth.store_tokens(user.id, template, {
        "access_token": "msft-stale",
        "refresh_token": "msft-rt",
        "expires_at": str(int(time.time()) - 10),
    })
    before = TOKEN_STATE["refresh_count"]
    fresh = asyncio.run(mcp_oauth.ensure_fresh_token(
        user, template, {"access_token": "msft-stale",
                         "expires_at": str(int(time.time()) - 10)}))
    assert fresh is not None
    assert TOKEN_STATE["last_client_id"] == CLIENT_ID  # the refresh carried it
    assert TOKEN_STATE["refresh_count"] == before + 1
    creds = _creds(u["username"])
    assert creds["CLIENT_ID"] == CLIENT_ID  # merge kept it across the refresh
    assert creds["access_token"] == fresh["access_token"]


def test_ensure_fresh_token_missing_client_id_409(client, m365_env):
    u = _user(client)
    user = _load_user(u["username"])
    template = _load_template(TEMPLATE_ID)
    mcp_oauth.store_tokens(user.id, template, {
        "access_token": "msft-stale",
        "refresh_token": "msft-rt",
        "expires_at": str(int(time.time()) - 10),
    })
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mcp_oauth.ensure_fresh_token(
            user, template, {"access_token": "msft-stale",
                             "expires_at": str(int(time.time()) - 10)}))
    assert exc.value.status_code == 409
