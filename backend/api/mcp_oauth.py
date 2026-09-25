"""OAuth 2.0 authorization-code + PKCE login for hosted remote MCP templates.

Some templates authenticate against a HOSTED MCP server with a per-user OAuth
token instead of a user-entered API key (Uber / Uber Eats: the upstream has no
self-serve API keys — the user logs in to their own account and we store the
resulting tokens). Flow:

  1. Frontend POSTs /api/mcp/config/{id}/oauth/authorize (session JWT)
     -> {url}. The browser is redirected to the provider's authorize endpoint
     (authorization code + PKCE S256; the state parameter is a short-lived
     server-signed JWT binding user + template + code verifier).
  2. The provider bounces the browser to GET /api/mcp/oauth/callback?code&state.
     The callback is PUBLIC (a browser redirect carries no session) — the state
     JWT IS the authentication for it. The code is exchanged for tokens and the
     token blob is Fernet-encrypted into the user's config row (same table and
     same at-rest guarantees as every other template).
  3. Before every proxied call, ``ensure_fresh_token`` refreshes the access
     token shortly before it expires (offline_access refresh grant). A refresh
     rewrites the blob; the bridge's instance key (a hash of the exact
     credentials) rotates, so the old instance carrying the stale token is
     torn down by the existing per-credential-identity semantics — no bridge
     changes needed. The per-request Bearer header rides the url-instance
     ``headers``/``env_mapping`` machinery (the Cloudflare template shape).

OAuth config lives in the template's ``runtime_config["oauth"]``:

    {
      "authorize_endpoint": "https://auth.example.com/authorize",
      "token_endpoint":     "https://auth.example.com/token",
      "client_id":          "...",               # issued by the provider (admin-managed)
      "client_secret":      "...",               # optional; omit for public (PKCE) clients
      "client_id_field":    "CLIENT_ID",         # optional; read the client_id from the
                                                 # user's stored config (per-tenant apps)
      "scopes":             "openid offline_access ...",
      "auth_label":         "Provider",          # UI text
      "redirect_uri":       "https://.../api/mcp/oauth/callback"  # optional override
    }

Security notes:
- Endpoints are admin-registered static config (same trust class as the
  bridge's ``url`` templates) and get the same public-https SSRF guard, once
  per process per endpoint.
- The PKCE verifier and all tokens live only in the Fernet blob / memory.
  Nothing OAuth-related is logged.
- ``client_secret`` is NEVER read from user input; it can only come from
  runtime_config (admin surface).
"""

import asyncio
import base64
import hashlib
import secrets
import time
from datetime import timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from auth import create_access_token, decode_access_token
from database import SessionLocal, User
from models.mcp_models import MCPTemplate, UserMCPConfig
from utils.crypto import decrypt_credentials, encrypt_credentials
from utils.logging_setup import logger
from utils.upstream import assert_public_upstream

STATE_TTL_SECONDS = 600  # login-state JWT lifetime: browser round trip, no more
REFRESH_MARGIN_SECONDS = 60  # refresh when the access token expires within this


class OAuthError(Exception):
    """OAuth flow failure with a user-safe message (no tokens, no secrets)."""


def oauth_config(template: MCPTemplate) -> dict[str, Any] | None:
    """The template's OAuth config, or None if the template is not a complete
    OAuth login (missing section, missing authorize/token endpoints, or
    neither an admin-registered client_id nor a per-user client_id_field)."""
    rc = template.runtime_config or {}
    cfg = rc.get("oauth")
    if not isinstance(cfg, dict):
        return None
    for key in ("authorize_endpoint", "token_endpoint"):
        if not str(cfg.get(key) or "").strip():
            return None
    if not str(cfg.get("client_id") or "").strip() and not str(cfg.get("client_id_field") or "").strip():
        return None
    return cfg


# Endpoints already SSRF-guarded this process (admin static config — the guard
# runs once, like the bridge's per-registration url check).
_guarded_endpoints: set[str] = set()


def _guard_endpoint(url: str) -> None:
    """Same public-https guard as the bridge's url templates. The authorize
    endpoint is never dialed by the backend (browser redirect) but is checked
    too: an http:// or internal authorize URL would leak the login state."""
    url = str(url)
    if url in _guarded_endpoints:
        return
    try:
        assert_public_upstream(url)
    except HTTPException as exc:
        raise OAuthError(f"OAuth endpoint rejected: {exc.detail}") from exc
    _guarded_endpoints.add(url)


def build_authorize_url(template: MCPTemplate, user_id: int, base_url: str) -> str:
    """The provider authorize URL the user's browser must visit (PKCE S256,
    state = short-lived server-signed JWT carrying the code verifier)."""
    cfg = complete_config_for_user(template, user_id)
    _guard_endpoint(str(cfg["authorize_endpoint"]))
    _guard_endpoint(str(cfg["token_endpoint"]))

    redirect_uri = str(cfg.get("redirect_uri") or f"{base_url.rstrip('/')}/api/mcp/oauth/callback")
    verifier = secrets.token_urlsafe(48)  # 64 urlsafe chars
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("utf-8")).digest()
    ).decode("ascii").rstrip("=")
    state = create_access_token(
        {"sub": str(user_id), "tid": template.id, "cv": verifier},
        expires_delta=timedelta(seconds=STATE_TTL_SECONDS),
    )
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": str(cfg["client_id"]),
        "redirect_uri": redirect_uri,
        "scope": str(cfg.get("scopes") or "").strip(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    params = {k: v for k, v in params.items() if v}
    from urllib.parse import urlencode

    return f"{cfg['authorize_endpoint']}?{urlencode(params)}"


def decode_state(state: str) -> dict[str, Any] | None:
    """Validate the callback's state JWT. Returns {sub, tid, cv} or None on any
    failure (bad signature, expired, wrong shape)."""
    payload = decode_access_token(state)
    if not payload or "cv" not in payload or "tid" not in payload or "sub" not in payload:
        return None
    return payload
def _user_creds(user_id: int, template_id: str) -> dict[str, Any]:
    """The user's stored config for the template, decrypted. {} on any
    failure — a missing or unreadable row must not break the flow, only
    the fields that need it."""
    db: Session = SessionLocal()
    try:
        row = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user_id,
                    UserMCPConfig.template_name == template_id)
            .first()
        )
        if not row:
            return {}
        try:
            creds = decrypt_credentials(row.credentials_json)
        except Exception:
            return {}
        return creds if isinstance(creds, dict) else {}
    finally:
        db.close()


def complete_config_for_user(template: MCPTemplate, user_id: int) -> dict[str, Any]:
    """The template's OAuth config with the client_id resolved for this user.

    Some hosted MCP servers take the client_id per-tenant: the tenant's IT
    admin registers one public (PKCE) app and every user pastes its client
    ID into the named config field (``client_id_field``). Otherwise the
    admin-registered client_id stands. Raises OAuthError when the needed
    client_id is absent."""
    cfg = oauth_config(template)
    if not cfg:
        raise OAuthError("Template has no complete OAuth config.")
    field = str(cfg.get("client_id_field") or "").strip()
    if not field:
        return cfg
    client_id = str(_user_creds(user_id, template.id).get(field) or "").strip()
    if not client_id:
        raise OAuthError(
            f"This login needs the {field} value your IT admin registered for "
            "your tenant — connect with it before signing in."
        )
    return {**cfg, "client_id": client_id}


def _token_request(cfg: dict[str, str], form: dict[str, str]) -> dict[str, Any]:
    """One POST to the provider's token endpoint (form-encoded, per RFC 6749)."""
    _guard_endpoint(str(cfg["token_endpoint"]))
    secret = str(cfg.get("client_secret") or "").strip()
    if secret:
        form = {**form, "client_secret": secret}
    try:
        with httpx.Client(timeout=20) as client:
            r = client.post(str(cfg["token_endpoint"]), data=form)
    except httpx.HTTPError as exc:
        raise OAuthError(f"Could not reach the OAuth token endpoint ({exc.__class__.__name__}).") from exc
    if r.status_code != 200:
        detail = ""
        try:
            body = r.json()
            detail = str(body.get("error_description") or body.get("error") or "")
        except Exception:
            detail = r.text[:200]
        raise OAuthError(
            f"Token endpoint returned HTTP {r.status_code}" + (f": {detail[:200]}" if detail else "")
        )
    try:
        data = r.json()
    except Exception:
        raise OAuthError("Token endpoint returned a non-JSON response.") from None
    if not data.get("access_token"):
        raise OAuthError("Token endpoint returned no access_token.")
    return data


def exchange_code(cfg: dict[str, str], code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
    """authorization_code grant (PKCE). The verifier comes from the state JWT,
    never from the network."""
    return _token_request(cfg, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": str(cfg["client_id"]),
        "code_verifier": code_verifier,
    })


def refresh_tokens(cfg: dict[str, str], refresh_token: str) -> dict[str, Any]:
    """refresh_token grant (the offline_access scope)."""
    return _token_request(cfg, {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": str(cfg["client_id"]),
    })


def tokens_to_creds(tokens: dict[str, Any]) -> dict[str, str]:
    """Token-endpoint response -> the stored credentials blob. All values are
    strings, matching every other template's credentials shape (the bridge's
    env_mapping / header resolution only deals in strings)."""
    blob: dict[str, str] = {"access_token": str(tokens["access_token"])}
    if tokens.get("expires_in") is not None:
        try:
            blob["expires_at"] = str(int(time.time()) + int(tokens["expires_in"]))
        except (TypeError, ValueError):
            pass
    for key in ("refresh_token", "scope"):
        if tokens.get(key):
            blob[key] = str(tokens[key])
    return blob


def store_tokens(user_id: int, template: MCPTemplate, creds: dict[str, str]) -> None:
    """Encrypt + upsert the user's config row for the template with the token
    blob, MERGED over any stored config fields (per-tenant values like the
    Microsoft 365 client ID must survive the token round trip). Raises
    ValueError when no encryption key is configured (the caller surfaces a
    clean error instead of a 500)."""
    db: Session = SessionLocal()
    try:
        row = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user_id,
                    UserMCPConfig.template_name == template.id)
            .first()
        )
        if row:
            # Merge (never replace): per-tenant config fields (e.g. the
            # Microsoft 365 client ID) live in the same blob and must
            # survive the token round trip.
            try:
                merged = decrypt_credentials(row.credentials_json)
                if not isinstance(merged, dict):
                    merged = {}
            except Exception:
                merged = {}
            merged.update(creds)
            row.credentials_json = encrypt_credentials(merged)
            row.is_active = True
        else:
            row = UserMCPConfig(
                owner_id=user_id,
                template_name=template.id,
                name_display=f"{template.name} login",
                credentials_json=encrypt_credentials(creds),
                is_active=True,
            )
            db.add(row)
        db.commit()
    finally:
        db.close()
    # Log the event, never the values.
    logger.info(f"OAuth: stored tokens for user {user_id} template {template.id}")


_refresh_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _refresh_lock(user_id: int, template_id: str) -> asyncio.Lock:
    key = (user_id, template_id)
    lock = _refresh_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[key] = lock
    return lock


def _refresh_detail(template: MCPTemplate) -> str:
    label = str((template.runtime_config or {}).get("oauth", {}).get("auth_label") or template.name)
    return (
        f"Your {label} login has expired and could not be refreshed. "
        "Reconnect (dashboard -> MCP Servers -> Connect)."
    )


async def ensure_fresh_token(user: User, template: MCPTemplate,
                             creds: dict[str, str]) -> dict[str, str] | None:
    """Refresh the stored OAuth access token shortly before it expires.

    Returns the NEW credentials dict when a refresh happened, or None when no
    refresh was needed (non-OAuth blob, no expiry data, still fresh). Raises
    HTTPException 409 when the token is expired but unrefreshable (the stored
    blob is unusable — the same status class the decrypt-failure path uses).
    """
    cfg = oauth_config(template)
    if not cfg or not creds.get("access_token"):
        return None
    expires_at = creds.get("expires_at")
    if expires_at is None:
        return None
    try:
        exp = float(expires_at)
    except (TypeError, ValueError):
        return None
    if exp - time.time() > REFRESH_MARGIN_SECONDS:
        return None

    async with _refresh_lock(user.id, template.id):
        # Double-check under the lock: a parallel call may have just refreshed.
        db: Session = SessionLocal()
        row: UserMCPConfig | None = None
        current: dict[str, str] = {}
        try:
            row = (
                db.query(UserMCPConfig)
                .filter(UserMCPConfig.owner_id == user.id,
                        UserMCPConfig.template_name == template.id)
                .first()
            )
            if row and row.is_active:
                current = decrypt_credentials(row.credentials_json)
        finally:
            db.close()

        try:
            current_exp = float(current.get("expires_at") or 0)
        except (TypeError, ValueError):
            current_exp = 0.0
        if current_exp - time.time() > REFRESH_MARGIN_SECONDS:
            return None

        refresh_token = current.get("refresh_token")
        if not refresh_token:
            raise HTTPException(status_code=409, detail=_refresh_detail(template))
        # Per-tenant templates take the client_id from the user's stored
        # config (client_id_field) — resolve it from the fresh blob.
        field = str(cfg.get("client_id_field") or "").strip()
        client_id = (
            str(current.get(field) or "").strip() if field
            else str(cfg.get("client_id") or "").strip()
        )
        if not client_id:
            raise HTTPException(status_code=409, detail=_refresh_detail(template))
        cfg = {**cfg, "client_id": client_id}
        try:
            tokens = await asyncio.to_thread(refresh_tokens, cfg, refresh_token)
        except OAuthError as exc:
            logger.warning(f"OAuth: refresh failed for user {user.id} template {template.id}: {exc}")
            raise HTTPException(status_code=409, detail=_refresh_detail(template)) from exc
        fresh = tokens_to_creds(tokens)
        store_tokens(user.id, template, fresh)
        return fresh
