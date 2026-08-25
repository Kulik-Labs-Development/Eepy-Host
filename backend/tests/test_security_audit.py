"""Regression tests for the 2026-08 security audit pass:

- SSRF guard on the legacy native proxy path (backend dials user-supplied hosts)
- request body size cap (unauthenticated /auth/* routes)
- rate limiter key function behind trusted reverse proxies
- avatar content-type allowlist (no SVG)
- UserLogin identifier length bound
"""

import random

import pytest
from pydantic import ValidationError

from api.mcp_endpoints import _assert_public_upstream, _happyfox_base
from schemas import UserLogin


# ---------------------------------------------------------------------------
# SSRF guard: the native (legacy) path makes the BACKEND dial a user-supplied
# URL and return the response — it must only reach public https endpoints.
# ---------------------------------------------------------------------------
class TestNativePathSSRFGuard:
    @pytest.mark.parametrize("url", [
        "http://public.example.com",          # plain http: Basic-auth creds in the clear
        "https://127.0.0.1:8068",             # loopback
        "https://10.1.2.3",                   # RFC1918 private
        "https://192.168.1.10",               # RFC1918 private
        "https://169.254.169.254",            # link-local: cloud metadata endpoint
        "https://172.16.0.5",                 # RFC1918 private
        "https://100.64.0.1",                 # CGNAT (not globally routable)
        "https://[::1]:8000",                 # IPv6 loopback
        "https://[fc00::1]",                  # IPv6 ULA (private)
        "https://0.0.0.0",                    # unspecified
    ])
    def test_rejects_non_public_targets(self, url):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _assert_public_upstream(url)
        assert exc.value.status_code == 400

    def test_allows_public_ip_literal(self):
        # IP literal: range-checked without DNS (deterministic, no network).
        _assert_public_upstream("https://93.184.216.34")  # does not raise

    def test_happyfox_base_bare_host_gets_https(self):
        assert _happyfox_base("93.184.216.34") == "https://93.184.216.34/api/1.1/json"

    def test_happyfox_base_rejects_empty(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _happyfox_base("   ")

    def test_native_test_route_blocks_metadata_host_e2e(self, client):
        """End-to-end: a connected user pointing their (native-runtime)
        HappyFox domain at the cloud metadata IP gets a 400, not a proxied
        read of 169.254.169.254. Temporarily flips the seeded happyfox
        template to the legacy native runtime, then restores it."""
        from database import SessionLocal
        from models.mcp_models import MCPTemplate

        db = SessionLocal()
        try:
            template = db.query(MCPTemplate).filter(MCPTemplate.id == "happyfox").first()
            original_runtime = template.runtime
            template.runtime = "native"
            db.commit()
        finally:
            db.close()

        try:
            username = f"ssrftest{random.randint(10000, 99999)}"
            r = client.post("/auth/signup", json={
                "username": username, "email": f"{username}@example.com", "password": "ssrf-password-1"})
            assert r.status_code == 200, r.text
            r = client.post("/auth/login", json={"username": username, "password": "ssrf-password-1"})
            assert r.status_code == 200, r.text
            token = r.json()["access_token"]

            # https scheme so the guard's IP check (not the scheme check) is
            # what must block the cloud metadata endpoint.
            r = client.post("/api/mcp/config/register",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"template_id": "happyfox",
                                  "credentials_json": {
                                      "HAPPYFOX_DOMAIN": "https://169.254.169.254",
                                      "HAPPYFOX_API_KEY": "k",
                                      "HAPPYFOX_AUTH_CODE": "c"}})
            assert r.status_code == 200, r.text

            r = client.post("/api/mcp/config/happyfox/test",
                            headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 400, r.text
            assert "non-public" in r.json()["detail"]

            # Plain http is rejected too (credentials would travel in the clear).
            r = client.post("/api/mcp/config/register",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"template_id": "happyfox",
                                  "credentials_json": {
                                      "HAPPYFOX_DOMAIN": "http://93.184.216.34",
                                      "HAPPYFOX_API_KEY": "k",
                                      "HAPPYFOX_AUTH_CODE": "c"}})
            assert r.status_code == 200, r.text
            r = client.post("/api/mcp/config/happyfox/test",
                            headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 400, r.text
            assert "https" in r.json()["detail"]
        finally:
            db = SessionLocal()
            try:
                template = db.query(MCPTemplate).filter(MCPTemplate.id == "happyfox").first()
                template.runtime = original_runtime
                db.commit()
            finally:
                db.close()


# ---------------------------------------------------------------------------
# Request body size cap (unauthenticated routes, OOM DoS protection)
# ---------------------------------------------------------------------------
def test_oversized_login_body_rejected_with_413(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "MAX_REQUEST_BODY_BYTES", 1024)
    r = client.post("/auth/login", json={"username": "u" * 2000, "password": "whatever-123"})
    assert r.status_code == 413, r.text


def test_small_login_body_passes_body_cap(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "MAX_REQUEST_BODY_BYTES", 1024)
    r = client.post("/auth/login", json={"username": "nobody-here-xyz", "password": "whatever-123"})
    # 401 (bad credentials) proves the request reached the handler, not the cap.
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# Rate limiter key: per-USER limits behind a trusted reverse proxy
# ---------------------------------------------------------------------------
def test_rate_limit_key_uses_xff_from_trusted_proxy(monkeypatch):
    from starlette.requests import Request

    import main

    monkeypatch.setattr(main, "_TRUSTED_PROXY_IPS", {"10.0.0.1"})
    scope = {
        "type": "http", "method": "POST", "path": "/auth/login",
        "client": ("10.0.0.1", 50000),
        "headers": [(b"x-forwarded-for", b"203.0.113.7, 10.0.0.1")],
    }
    assert main.rate_limit_key(Request(scope)) == "203.0.113.7"


def test_rate_limit_key_ignores_xff_from_untrusted_peer(monkeypatch):
    from starlette.requests import Request

    import main

    # Untrusted direct peer: a spoofed X-Forwarded-For must not change the key
    # (otherwise an attacker could bypass limits by rotating fake client IPs).
    monkeypatch.setattr(main, "_TRUSTED_PROXY_IPS", set())
    scope = {
        "type": "http", "method": "POST", "path": "/auth/login",
        "client": ("203.0.113.9", 50000),
        "headers": [(b"x-forwarded-for", b"1.2.3.4")],
    }
    assert main.rate_limit_key(Request(scope)) == "203.0.113.9"


# ---------------------------------------------------------------------------
# Avatar: raster content types only (no SVG)
# ---------------------------------------------------------------------------
def test_avatar_rejects_svg(client):
    from test_avatar_upload import _auth_user

    token = _auth_user(client)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/track"/></svg>'
    r = client.post("/user/avatar",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("avatar.svg", svg, "image/svg+xml")})
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Login identifier bound (log-line bloat protection)
# ---------------------------------------------------------------------------
def test_userlogin_username_bounded():
    with pytest.raises(ValidationError):
        UserLogin(username="x" * 256, password="whatever-123")

    m = UserLogin(username="a" * 255, password="whatever-123")
    assert m.username == "a" * 255
