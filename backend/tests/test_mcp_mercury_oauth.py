"""Mercury Bank: Mercury's hosted remote MCP (mcp.mercury.com, streamable
HTTP at /mcp). The gateway performs a one-time RFC 7591 Dynamic Client
Registration at boot (POST /register, public client:
token_endpoint_auth_method "none" — no secret, PKCE proves identity at the
token endpoint) and stores the client_id Fernet-encrypted in
mcp_client_registrations; the hosted OAuth layer resolves it per request
(dcr: true). Both /register and /token are served by ONE fake TLS server on
loopback (same pattern as test_mcp_m365_oauth)."""

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

TEMPLATE_ID = "mercury"
CLIENT_ID = "dcr-client-1"
GOOD_CODE = "mercury-code"
TOKEN_SCOPE = "read offline_access"
CANONICAL_REDIRECT = "https://api.eepy.host/api/mcp/oauth/callback"

REG_STATE = {"register_bodies": [], "last_content_type": ""}
TOKEN_STATE = {"last_form": {}, "refresh_count": 0}


def _self_signed_cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("mercury-tls")
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


async def _send_json(send, status: int, payload: dict) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": json.dumps(payload).encode()})


async def mercury_app(scope, receive, send):
    """Fake Mercury: POST /register (RFC 7591) + POST /token (the grants)."""
    if scope["type"] != "http":
        return
    path = scope.get("path", "")
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break
    text = body.decode()
    if path == "/register":
        REG_STATE["last_content_type"] = (
            dict(scope.get("headers") or {}).get(b"content-type", b"").decode()
        )
        try:
            data = json.loads(text)
        except Exception:
            data = None
        REG_STATE["register_bodies"].append(data)
        if (
            not isinstance(data, dict)
            or data.get("client_name") != "Eepy Host"
            or data.get("redirect_uris") != [CANONICAL_REDIRECT]
            or data.get("grant_types") != ["authorization_code", "refresh_token"]
            or data.get("response_types") != ["code"]
            or data.get("token_endpoint_auth_method") != "none"
        ):
            await _send_json(send, 400, {"error": "invalid_client_metadata"})
            return
        # Public client: a client_id, and NO usable secret (a null here
        # exercises the "if the response did contain a client_secret: log
        # one line and ignore it" branch).
        await _send_json(send, 201, {"client_id": CLIENT_ID, "client_secret": None})
        return
    if path == "/token":
        form = {k: v[0] for k, v in parse_qs(text).items()}
        TOKEN_STATE["last_form"] = form
        if form.get("grant_type") == "authorization_code":
            if (
                form.get("code") != GOOD_CODE
                or not form.get("code_verifier")
                or form.get("client_id") != CLIENT_ID
                or "client_secret" in form
            ):
                await _send_json(send, 400, {"error": "invalid_grant"})
                return
            await _send_json(send, 200, {
                "access_token": "merc-1", "refresh_token": "merc-rt",
                "expires_in": 3600, "scope": TOKEN_SCOPE})
            return
        if form.get("grant_type") == "refresh_token":
            if (
                form.get("refresh_token") != "merc-rt"
                or form.get("client_id") != CLIENT_ID
                or "client_secret" in form
            ):
                await _send_json(send, 400, {
                    "error": "invalid_grant", "error_description": "bad client"})
                return
            TOKEN_STATE["refresh_count"] += 1
            await _send_json(send, 200, {
                "access_token": f"merc-{TOKEN_STATE['refresh_count'] + 1}",
                "refresh_token": "merc-rt", "expires_in": 3600})
            return
        await _send_json(send, 400, {"error": "unsupported_grant_type"})
        return
    await _send_json(send, 404, {"error": "not_found"})


@pytest.fixture(scope="module")
def mercury_server(tmp_path_factory):
    """Fake Mercury /register + /token on 127.0.0.1 (self-signed TLS)."""
    import uvicorn

    cert_path, key_path = _self_signed_cert(tmp_path_factory)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(mercury_app, host="127.0.0.1", port=port,
                            ssl_certfile=str(cert_path), ssl_keyfile=str(key_path),
                            log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("fake mercury oauth server did not start")
        time.sleep(0.05)

    yield {"base": f"https://127.0.0.1:{port}", "cert": cert_path}

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def mercury_env(monkeypatch, mercury_server):
    """Guard patched to loopback + mcp.mercury.com (the authorize endpoint is
    never dialed by the backend), httpx trusting the test cert, the DCR URL
    and the seeded template's token endpoint pointed at the fake server, and
    a clean slate for the registration row (the REAL boot DCR may have stored
    one against the real Mercury before the session's first client use —
    the throwaway row is deleted here so every test starts unregistered)."""
    from database import SessionLocal
    from models.mcp_models import MCPClientRegistration, MCPTemplate

    base, cert = mercury_server["base"], mercury_server["cert"]

    def guard(url):
        if not str(url).lower().startswith("https://"):
            raise HTTPException(status_code=400, detail="Upstream host must use https.")
        host = urlparse(url).hostname or ""
        if host not in ("127.0.0.1", "localhost", "mcp.mercury.com"):
            raise HTTPException(status_code=400, detail="test guard: host not allowed")

    real_client = httpx.Client

    def trusting_client(*args, **kwargs):
        kwargs["verify"] = str(cert)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(mcp_oauth, "assert_public_upstream", guard)
    monkeypatch.setattr(httpx, "Client", trusting_client)
    monkeypatch.setattr(mcp_oauth, "MERCURY_REGISTER_URL", f"{base}/register")
    mcp_oauth._guarded_endpoints.clear()
    REG_STATE["register_bodies"] = []
    REG_STATE["last_content_type"] = ""
    TOKEN_STATE["last_form"] = {}
    TOKEN_STATE["refresh_count"] = 0

    db = SessionLocal()
    try:
        db.query(MCPClientRegistration).filter(
            MCPClientRegistration.template_id == TEMPLATE_ID).delete()
        t = db.query(MCPTemplate).filter(MCPTemplate.id == TEMPLATE_ID).first()
        assert t is not None, "mercury template was not seeded"
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

    username = f"mercurytest{random.randint(100000, 999999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "mercury-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "mercury-password-1"})
    assert r.status_code == 200, r.text
    return {"token": r.json()["access_token"], "username": username}


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


def _reg_row():
    from database import SessionLocal
    from models.mcp_models import MCPClientRegistration

    db = SessionLocal()
    try:
        row = (
            db.query(MCPClientRegistration)
            .filter(MCPClientRegistration.template_id == TEMPLATE_ID)
            .first()
        )
        if row:
            db.expunge(row)
        return row
    finally:
        db.close()


def _creds(username: str) -> dict:
    from database import SessionLocal, User
    from models.mcp_models import UserMCPConfig

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        row = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user.id,
                    UserMCPConfig.template_name == TEMPLATE_ID)
            .first()
        )
        assert row is not None
        return decrypt_credentials(row.credentials_json)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Seed shape: hosted remote MCP, gateway-registered public (PKCE) client
# ---------------------------------------------------------------------------
def test_seeded_template_shape(client):
    t = _load_template(TEMPLATE_ID)
    assert t is not None, "mercury template was not seeded"
    assert t.approved_by_admin is True
    assert t.enabled_global is True
    assert t.runtime == "mcp-server"
    rc = t.runtime_config
    assert rc["url"] == "https://mcp.mercury.com"
    assert rc["endpoint"] == "/mcp"
    assert rc["env_mapping"] == {"access_token": "MERCURY_ACCESS_TOKEN"}
    assert rc["headers"] == {"Authorization": "Bearer {{MERCURY_ACCESS_TOKEN}}"}
    assert "image" not in rc and "command" not in rc  # no sidecar
    o = rc["oauth"]
    assert o["authorize_endpoint"] == "https://mcp.mercury.com/authorize"
    assert o["token_endpoint"] == "https://mcp.mercury.com/token"
    assert o["dcr"] is True
    assert o["client_id"] == ""
    assert "client_id_field" not in o
    assert "client_secret" not in o
    assert o["scopes"] == TOKEN_SCOPE
    assert o["auth_label"] == "Mercury Bank"
    assert o["resource"] == "https://mcp.mercury.com/mcp"
    assert t.config_schema == {}
    assert t.repo_url == "https://docs.mercury.com/docs/connecting-mercury-mcp"


def test_template_list_surfaces_oauth(client):
    u = _user(client)
    r = client.get("/api/mcp/templates/list",
                   headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200, r.text
    row = next((t for t in r.json() if t["id"] == TEMPLATE_ID), None)
    assert row is not None
    assert row["auth_mode"] == "oauth"
    assert row["config_schema"] == {}


# ---------------------------------------------------------------------------
# 2. Boot DCR: the right RFC 7591 body, the stored row; idempotent on the
#    second boot
# ---------------------------------------------------------------------------
def test_boot_dcr_posts_public_client_and_stores_row(client, mercury_env):
    mcp_oauth.ensure_mercury_client_registration("https://api.eepy.host")
    assert len(REG_STATE["register_bodies"]) == 1
    body = REG_STATE["register_bodies"][0]
    assert body["client_name"] == "Eepy Host"
    assert body["redirect_uris"] == [CANONICAL_REDIRECT]  # the layer's default redirect
    assert body["grant_types"] == ["authorization_code", "refresh_token"]
    assert body["response_types"] == ["code"]
    assert body["token_endpoint_auth_method"] == "none"
    assert REG_STATE["last_content_type"].startswith("application/json")

    row = _reg_row()
    assert row is not None, "DCR did not store the registration row"
    assert row.template_id == TEMPLATE_ID
    assert row.client_id_enc.startswith("gAAAAA")  # a Fernet token, never plaintext
    assert row.client_secret_enc is None  # public client
    assert mcp_oauth.resolve_dcr_client(TEMPLATE_ID) == {
        "client_id": CLIENT_ID, "client_secret": None}


def test_boot_dcr_is_idempotent(client, mercury_env):
    mcp_oauth.ensure_mercury_client_registration("https://api.eepy.host")
    mcp_oauth.ensure_mercury_client_registration("https://api.eepy.host")
    assert len(REG_STATE["register_bodies"]) == 1  # the second boot made zero extra POSTs
    assert mcp_oauth.resolve_dcr_client(TEMPLATE_ID) is not None


# ---------------------------------------------------------------------------
# 3. DCR failure at boot: boot completes (template stays seeded), authorize
#    returns the 503 not-registered detail (operator message)
# ---------------------------------------------------------------------------
def test_boot_dcr_failure_keeps_boot_and_503s_authorize(client, monkeypatch, mercury_env):
    monkeypatch.setattr(mcp_oauth, "MERCURY_REGISTER_URL", "https://127.0.0.1:1/register")
    mcp_oauth.ensure_mercury_client_registration("https://api.eepy.host")  # must NOT raise
    assert REG_STATE["register_bodies"] == []
    assert _reg_row() is None
    t = _load_template(TEMPLATE_ID)
    assert t is not None and t.approved_by_admin is True  # the template is still seeded

    u = _user(client)
    r = client.post(f"/api/mcp/config/{TEMPLATE_ID}/oauth/authorize",
                    headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "not registered" in detail
    assert "boot log" in detail


# ---------------------------------------------------------------------------
# 4. Authorize: resource + the DCR client_id + scope + PKCE S256
# ---------------------------------------------------------------------------
def test_authorize_url_carries_resource_dcr_client_and_pkce(client, mercury_env):
    mcp_oauth.ensure_mercury_client_registration("https://api.eepy.host")
    u = _user(client)
    r = client.post(f"/api/mcp/config/{TEMPLATE_ID}/oauth/authorize",
                    headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://mcp.mercury.com/authorize?")
    assert q["client_id"] == CLIENT_ID  # resolved from the DCR registration row
    assert q["resource"] == "https://mcp.mercury.com/mcp"
    assert q["scope"] == TOKEN_SCOPE
    assert q["response_type"] == "code"
    assert q["redirect_uri"] == CANONICAL_REDIRECT
    assert q["code_challenge_method"] == "S256"

    state = mcp_oauth.decode_state(q["state"])
    assert state is not None
    assert state["tid"] == TEMPLATE_ID
    verifier = state["cv"]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert q["code_challenge"] == expected


# ---------------------------------------------------------------------------
# 5. Code exchange: the token server sees the DCR client_id, NO
#    client_secret, and the code_verifier; tokens are stored
# ---------------------------------------------------------------------------
def test_callback_roundtrip_exchanges_dcr_code(client, mercury_env):
    mcp_oauth.ensure_mercury_client_registration("https://api.eepy.host")
    u = _user(client)
    r = client.post(f"/api/mcp/config/{TEMPLATE_ID}/oauth/authorize",
                    headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]

    r = client.get(f"/api/mcp/oauth/callback?code={GOOD_CODE}&state={state}")
    assert r.status_code == 200, r.text
    assert "Connected" in r.text

    form = TOKEN_STATE["last_form"]
    assert form["grant_type"] == "authorization_code"
    assert form["client_id"] == CLIENT_ID  # the DCR client_id reached the token endpoint
    assert "client_secret" not in form  # public client: secretless PKCE exchange
    assert form.get("code_verifier")  # PKCE verifier present
    assert form["code"] == GOOD_CODE
    assert form["redirect_uri"] == CANONICAL_REDIRECT

    creds = _creds(u["username"])
    assert creds["access_token"] == "merc-1"
    assert creds["refresh_token"] == "merc-rt"
    assert int(creds["expires_at"]) > time.time()

    r = client.get("/api/mcp/config/list",
                   headers={"Authorization": f"Bearer {u['token']}"})
    row = next((c for c in r.json() if c["template_name"] == TEMPLATE_ID), None)
    assert row is not None and row["is_active"] is True


# ---------------------------------------------------------------------------
# 6. Refresh: grant_type=refresh_token + the DCR client_id -> fresh tokens
# ---------------------------------------------------------------------------
def test_refresh_uses_dcr_client_id(client, mercury_env):
    mcp_oauth.ensure_mercury_client_registration("https://api.eepy.host")
    u = _user(client)
    user = _load_user(u["username"])
    template = _load_template(TEMPLATE_ID)
    mcp_oauth.store_tokens(user.id, template, {
        "access_token": "merc-stale",
        "refresh_token": "merc-rt",
        "expires_at": str(int(time.time()) - 10),
    })
    before = TOKEN_STATE["refresh_count"]
    fresh = asyncio.run(mcp_oauth.ensure_fresh_token(
        user, template, {"access_token": "merc-stale",
                         "expires_at": str(int(time.time()) - 10)}))
    assert fresh is not None
    form = TOKEN_STATE["last_form"]
    assert form["grant_type"] == "refresh_token"
    assert form["client_id"] == CLIENT_ID  # the DCR client_id survived the refresh
    assert "client_secret" not in form
    assert TOKEN_STATE["refresh_count"] == before + 1
    creds = _creds(u["username"])
    assert creds["access_token"] == fresh["access_token"]
    assert creds["refresh_token"] == "merc-rt"
