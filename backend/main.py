import base64
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from auth import DUMMY_HASH, create_access_token, decode_access_token, get_password_hash, verify_password
from database import Base, SessionLocal, User, UserRole, engine, get_db
from models import (
    mcp_models,  # noqa: F401  - register MCP tables on the shared Base so create_all builds them
)
from models.mcp_models import MCPTemplate
from schemas import PasswordResetIn, UserCreate, UserLogin
from utils.logging_setup import MemoryLogHandler, logger

# Build a dedicated handler instance for the superuser log endpoint so the
# buffer is decoupled from any module-level shared handler.
memory_handler = MemoryLogHandler()
memory_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(memory_handler)

# Avatars are stored as base64 data-URIs in the `users.profile_picture` TEXT
# column and returned in full on every profile read, so cap uploads at a
# realistic photo size. Anything larger is a storage/DoS vector, not an avatar.
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB


def sync_database_schema():
    try:
        with engine.connect() as conn:
            # users table columns (existing behavior).
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))
            existing_columns = {row[0] for row in result}

            required_columns = {
                "full_name": "VARCHAR",
                "profile_picture": "TEXT",
                "total_requests": "INTEGER DEFAULT 0 NOT NULL"
            }

            for col, col_type in required_columns.items():
                if col not in existing_columns:
                    logger.info(f"Adding missing column {col} to users table...")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))

            # Case-insensitive username uniqueness, rolled forward onto existing
            # installs (fresh installs get the index from the model via
            # create_all). If clashing rows already exist ("User123" +
            # "user123") the unique index cannot be created: report the
            # offending usernames and skip it until an operator renames one of
            # each pair; the app-level check in /auth/signup keeps blocking
            # NEW clashes either way.
            clash_rows = conn.execute(text(
                "SELECT min(username) FROM users GROUP BY lower(username) HAVING count(*) > 1"
            )).fetchall()
            if clash_rows:
                logger.error(
                    "Case-insensitive username uniqueness NOT enforced: the users table "
                    f"already contains clashing usernames: {[row[0] for row in clash_rows]}. "
                    "Rename one of each pair (e.g. via SQL) and restart the backend - "
                    "the unique index is created automatically on the next boot."
                )
            else:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_key ON users (lower(username))"
                ))

            # mcp_templates columns for the modular MCP sidecar runtime.
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='mcp_templates'"))
            template_cols = {row[0] for row in result}
            template_required = {
                "runtime": "VARCHAR NOT NULL DEFAULT 'native'",
                "runtime_config": "JSON",
                "discovered_tools": "JSON",
                "tools_discovered_at": "TIMESTAMP WITH TIME ZONE",
                # Upstream repo for the author credit / code-audit link.
                "repo_url": "VARCHAR(500)",
            }
            for col, col_type in template_required.items():
                if col not in template_cols:
                    logger.info(f"Adding missing column {col} to mcp_templates table...")
                    conn.execute(text(f"ALTER TABLE mcp_templates ADD COLUMN {col} {col_type}"))

            # mcp_sidecars.node_id scopes the boot orphan sweep to the node
            # that owns a sidecar (single-host, multi-replica safe).
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='mcp_sidecars'"))
            sidecar_cols = {row[0] for row in result}
            if sidecar_cols and "node_id" not in sidecar_cols:
                logger.info("Adding missing column node_id to mcp_sidecars table...")
                conn.execute(text("ALTER TABLE mcp_sidecars ADD COLUMN node_id VARCHAR(64)"))

            # mcp_user_tool_keys.key_encrypted holds the Fernet token of the
            # plaintext tool key so the owner can re-view it later (password
            # re-entry required). Legacy rows keep NULL (not re-viewable).
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='mcp_user_tool_keys'"))
            toolkey_cols = {row[0] for row in result}
            if toolkey_cols and "key_encrypted" not in toolkey_cols:
                logger.info("Adding missing column key_encrypted to mcp_user_tool_keys table...")
                conn.execute(text("ALTER TABLE mcp_user_tool_keys ADD COLUMN key_encrypted TEXT"))

            conn.commit()
            logger.info("Database columns synchronized.")
    except Exception as e:
        logger.error(f"Schema column synchronization failed: {e}")


def bootstrap_superuser() -> None:
    """Optional first-boot bootstrap: promote the account named in the
    SUPERUSER_USERNAME env var to superuser (the initial admin).

    Runs at EVERY boot (idempotent) AND opportunistically at login (see
    ``login``): the account may only be created after the first boot, and a
    boot that ran before Postgres was ready (or before the account existed)
    would otherwise leave the configured admin a plain USER — with the
    result that e.g. the Debug Log console 403s and the operator assumes
    the log stream is empty.
    """
    bootstrap_username = os.getenv("SUPERUSER_USERNAME", "").strip()
    if not bootstrap_username:
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(func.lower(User.username) == bootstrap_username.lower()).first()
        if user:
            if user.role != UserRole.SUPERUSER:
                logger.info(f"Promoting {bootstrap_username} to superuser...")
                user.role = UserRole.SUPERUSER
                db.commit()
                logger.info(f"User {bootstrap_username} promoted to superuser successfully.")
        # No warning when the account does not exist yet: it may be the very
        # first signup. The login-time hook below picks it up.
    except Exception as e:
        logger.error(f"Superuser promotion failed: {e}")
    finally:
        db.close()

def seed_mcp_templates():
    """Seed the admin-approved templates (HappyFox #1, eBay #2, Portainer #3,
    Warden #4, Proxmox VE #5) into the library.

    Each integration's MCP server code lives OUTSIDE this backend, in its own
    git submodule under integrations/ (happyfox-mcp →
    github.com/Glitch3dPenguin/happyfox-mcp, ebay-mcp →
    github.com/YosefHayim/ebay-mcp, portainer-mcp →
    github.com/portainer/portainer-mcp, warden-mcp →
    github.com/icoretech/warden-mcp, proxmox-mcp →
    github.com/RekklesNA/ProxmoxMCP-Plus). These rows only register *how to
    run* them:

    - docker backend (production/Portainer): CI builds each submodule into its
      eepy-host-<name> GHCR sidecar image on every push (the submodule pin in
      git = exactly that code).
    - subprocess backend (local dev): runs the submodule in-repo directly.

    Updating an integration = update its submodule ref + re-run admin
    discovery; never edit its code inside the backend.
    """
    from models.mcp_models import MCPTemplate

    happyfox = MCPTemplate(
        id="happyfox",
        name="HappyFox Help Desk",
        repo_url="https://github.com/Glitch3dPenguin/happyfox-mcp",
        description=(
            "Manage, read, and respond to support tickets in your HappyFox Help Desk. "
            "Agents can triage queues, read threads, post replies and private notes, "
            "change ticket status, and download attachments. All traffic is routed "
            "through the Eepy unified proxy with credentials encrypted at rest."
        ),
        config_schema={
            "category": "Support / Ticketing",
            "type": "object",
            "properties": {
                "HAPPYFOX_DOMAIN": {
                    "type": "string",
                    "label": "HappyFox Domain",
                    "placeholder": "yourcompany.happyfox.com",
                    "help": "The domain of your HappyFox instance.",
                    "required": True,
                },
                "HAPPYFOX_API_KEY": {
                    "type": "password",
                    "label": "API Key",
                    "help": "From HappyFox dashboard: Settings > Integrations > API Key.",
                    "required": True,
                },
                "HAPPYFOX_AUTH_CODE": {
                    "type": "password",
                    "label": "Auth Code",
                    "help": "Second API credential from the same panel.",
                    "required": True,
                },
            },
            "required": ["HAPPYFOX_DOMAIN", "HAPPYFOX_API_KEY", "HAPPYFOX_AUTH_CODE"],
        },
        image_tag="ghcr.io/kulik-labs-development/eepy-host-happyfox",
        runtime="mcp-server",
        # Modular sidecar spec. Production (docker backend): CI builds the
        # integrations/happyfox-mcp submodule into the image below on every
        # push, so the sidecar always runs exactly the upstream commit this
        # repo pins. Local (subprocess backend): the command + cwd run the
        # submodule's server straight from the repo (stdio transport).
        runtime_config={
            "image": "ghcr.io/kulik-labs-development/eepy-host-happyfox:latest",
            "command": ["python", "happyfox_mcp.py"],
            "cwd": "integrations/happyfox-mcp",
            # Docker backend env: the sidecar serves streamable-HTTP so the
            # bridge can dial it on its loopback-bound host port.
            "env": {
                "MCP_TRANSPORT": "streamable-http",
                "PORT": "8000",
            },
            # Subprocess backend env (local dev): the bridge speaks stdio to
            # subprocess sidecars, so the server must run in stdio mode.
            # Without this override the docker-oriented env above would make
            # the sidecar bind 0.0.0.0:8000 in HTTP mode and the stdio
            # handshake fail (port clash + no stdio traffic).
            "subprocess_env": {"MCP_TRANSPORT": "stdio"},
            "endpoint": "/",
            "port": "8000",
            "env_mapping": {
                "HAPPYFOX_DOMAIN": "HAPPYFOX_DOMAIN",
                "HAPPYFOX_API_KEY": "HAPPYFOX_API_KEY",
                "HAPPYFOX_AUTH_CODE": "HAPPYFOX_AUTH_CODE",
            },
            # Read-only tool used by POST /config/{id}/test. The server returns
            # "Error ..." as tool text on auth failure, so the test inspects it.
            "test_tool": {"name": "list_tickets", "arguments": {"status": "_pending", "size": 1}},
            # Best-effort tool list for the OpenAPI spec until admin discovery
            # stores the authoritative tools/list (from the upstream repo).
            # Kept in sync with integrations/happyfox-mcp (16 tools at submodule
            # commit 91906dc, verified through the subprocess sidecar path).
            "tool_names": [
                "list_tickets", "get_ticket_details", "get_ticket_messages",
                "get_ticket_attachments", "download_attachment", "list_statuses",
                "list_categories", "list_staff", "list_priorities",
                "add_ticket_update", "create_ticket", "assign_ticket",
                "suggest_ticket_rename", "change_ticket_status",
                "change_ticket_priority", "change_ticket_category",
            ],
        },
        approved_by_admin=True,
        enabled_global=True,
    )

    ebay = MCPTemplate(
        id="ebay",
        name="eBay Sell",
        repo_url="https://github.com/YosefHayim/ebay-mcp",
        description=(
            "Manage your eBay seller account across 299 tools over eBay's Sell APIs: "
            "inventory and offers, orders and fulfillment, promoted-listings marketing, "
            "seller analytics, and buyer messaging. Runs against sandbox or production "
            "with your own eBay Developer keys; credentials stay encrypted at rest and "
            "are proxied through the Eepy unified proxy."
        ),
        config_schema={
            "category": "E-commerce / Marketplace",
            "type": "object",
            "properties": {
                "EBAY_CLIENT_ID": {
                    "type": "string",
                    "label": "Client ID (App ID)",
                    "help": "eBay Developer Portal (developer.ebay.com > My apps > Keys): the App ID.",
                    "required": True,
                },
                "EBAY_CLIENT_SECRET": {
                    "type": "password",
                    "label": "Client Secret (Cert ID)",
                    "help": "The Cert ID from the same Keys panel.",
                    "required": True,
                },
                "EBAY_ENVIRONMENT": {
                    "type": "string",
                    "label": "Environment",
                    "placeholder": "sandbox",
                    "help": "sandbox (test data) or production (live seller data).",
                    "required": True,
                },
                "EBAY_REDIRECT_URI": {
                    "type": "string",
                    "label": "Redirect URI (RuName)",
                    "help": "Optional. The RuName from Developer Portal > User Tokens; enables the higher-limit user-token OAuth flow.",
                    "required": False,
                },
                "EBAY_MARKETPLACE_ID": {
                    "type": "string",
                    "label": "Marketplace ID",
                    "placeholder": "EBAY_US",
                    "help": "Optional. Defaults to EBAY_US (e.g. EBAY_GB, EBAY_DE, EBAY_AU).",
                    "required": False,
                },
                "EBAY_USER_REFRESH_TOKEN": {
                    "type": "password",
                    "label": "User Refresh Token",
                    "help": "Optional. An existing eBay OAuth refresh token raises rate limits from 1k to 10k-50k requests/day.",
                    "required": False,
                },
            },
            "required": ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENVIRONMENT"],
        },
        image_tag="ghcr.io/kulik-labs-development/eepy-host-ebay",
        runtime="mcp-server",
        # Modular sidecar spec (same contract as the HappyFox reference).
        # Production (docker backend): CI builds the integrations/ebay-mcp
        # submodule into the image below on every push. The upstream HTTP
        # entrypoint serves streamable-HTTP on :3000; OAUTH_ENABLED=false
        # disables the upstream bearer middleware because the sidecar is only
        # reachable on the internal eepy-sidecars docker network and the Eepy
        # unified proxy is the auth layer.
        # MCP_HOST must be explicit: upstream binds localhost when PORT is
        # unset, which the docker port mapping cannot reach.
        # Local (subprocess backend): stdio entrypoint; needs a one-time
        # `pnpm install && pnpm run build` inside integrations/ebay-mcp.
        runtime_config={
            "image": "ghcr.io/kulik-labs-development/eepy-host-ebay:latest",
            "command": ["node", "build/index.js"],
            "cwd": "integrations/ebay-mcp",
            "env": {
                "OAUTH_ENABLED": "false",
                "MCP_HOST": "0.0.0.0",
                "MCP_PORT": "3000",
            },
            # The stdio entrypoint needs none of the HTTP transport vars.
            "subprocess_env": {},
            "endpoint": "/",
            "port": "3000",
            "env_mapping": {
                "EBAY_CLIENT_ID": "EBAY_CLIENT_ID",
                "EBAY_CLIENT_SECRET": "EBAY_CLIENT_SECRET",
                "EBAY_ENVIRONMENT": "EBAY_ENVIRONMENT",
                "EBAY_REDIRECT_URI": "EBAY_REDIRECT_URI",
                "EBAY_MARKETPLACE_ID": "EBAY_MARKETPLACE_ID",
                "EBAY_USER_REFRESH_TOKEN": "EBAY_USER_REFRESH_TOKEN",
            },
            # Read-only probe for POST /config/{id}/test: a rate-limits lookup
            # confirms credentials + API reachability without touching data.
            # (The upstream server exits at startup if client id/secret are
            # missing, so a misconfigured sidecar fails the test loudly.)
            "test_tool": {"name": "ebay_get_rate_limits", "arguments": {}},
            # Representative subset of the 299 upstream tools so the OpenAPI
            # spec has entries before admin discovery stores the full
            # authoritative tools/list (discovery takes precedence).
            "tool_names": [
                "ebay_get_rate_limits", "ebay_get_inventory_items",
                "ebay_get_inventory_item", "ebay_get_offers", "ebay_get_orders",
                "ebay_get_order", "ebay_get_campaigns",
                "ebay_get_seller_standards_profile", "ebay_get_traffic_report",
                "ebay_get_default_category_tree_id",
                "ebay_get_shipping_fulfillments", "ebay_get_oauth_url",
                "ebay_create_or_replace_inventory_item",
            ],
        },
        approved_by_admin=True,
        enabled_global=True,
    )

    portainer = MCPTemplate(
        id="portainer",
        name="Portainer",
        repo_url="https://github.com/portainer/portainer-mcp",
        description=(
            "Manage your Portainer instance across ~211 tools: environments and "
            "endpoints, Docker containers and images, Kubernetes resources, Helm "
            "releases, stacks, and GitOps workflows — plus proxy calls straight to "
            "each environment's Docker/K8s API. Runs against YOUR Portainer with "
            "your own access token (match the server's minor version to your "
            "Portainer's, e.g. 2.44); credentials stay encrypted at rest and are "
            "proxied through the Eepy unified proxy."
        ),
        config_schema={
            "category": "DevOps / Container Management",
            "type": "object",
            "properties": {
                "PORTAINER_URL": {
                    "type": "string",
                    "label": "Portainer URL",
                    "placeholder": "https://portainer.example.com",
                    "help": "Base URL of your Portainer instance (no trailing /api).",
                    "required": True,
                },
                "PORTAINER_API_KEY": {
                    "type": "password",
                    "label": "API Key (Access Token)",
                    "placeholder": "ptr_...",
                    "help": "Portainer: My Account > Access tokens. The MCP server's minor version must match your Portainer's minor (2.44.x server ↔ 2.44.x instance).",
                    "required": True,
                },
                "PORTAINER_TLS_VERIFY": {
                    "type": "string",
                    "label": "Verify TLS Certificates",
                    "placeholder": "1",
                    "help": "Optional. Set 0 if your Portainer instance uses a self-signed certificate (default: 1).",
                    "required": False,
                },
            },
            "required": ["PORTAINER_URL", "PORTAINER_API_KEY"],
        },
        image_tag="ghcr.io/kulik-labs-development/eepy-host-portainer",
        runtime="mcp-server",
        # Modular sidecar spec (same contract as the HappyFox/eBay reference),
        # with the two Eepy bridge extensions this upstream needs because its
        # HTTP mode is per-user passthrough:
        #
        #  - generated_secrets: the server REQUIRES an HTTP gate secret
        #    (PORTAINER_MCP_AUTH_TOKEN, 32+ chars) but the token must be
        #    unique per sidecar and never stored — the bridge mints a fresh
        #    random one into the sidecar env on every spawn.
        #  - headers: every request (initialize AND tools/call) must carry
        #    the gate bearer in Authorization AND the user's own key in
        #    X-Portainer-API-Key (validated per request, cached 60s). The
        #    {{ENV}} placeholders resolve from the sidecar env, so the user's
        #    key reaches the header without ever being in runtime_config.
        #  - Host override: the server 421-rejects any Host not in
        #    PORTAINER_MCP_ALLOWED_HOSTS, but the sidecar's container IP is
        #    only known AFTER spawn. The bridge therefore dials with a fixed
        #    Host header (eepy-sidecar:17717) and the allowlist below accepts
        #    it via the `host:*` wildcard-port pattern.
        #
        # Production (docker backend): the image serves streamable-HTTP on
        # :17717 at /mcp. It is ONLY reachable on the internal eepy-sidecars
        # docker network, so the plaintext-HTTP opt-in is the deployment's
        # trusted-private-network posture (the gate token + per-user key are
        # the auth layers; the Eepy unified proxy is the front door). Under
        # HTTP the server REFUSES to boot with PORTAINER_API_KEY set (it is
        # stdio-only), so the docker env_mapping parks the user's key in
        # EEPY_PORTAINER_API_KEY for the header template.
        # Local (subprocess backend): stdio transport reads PORTAINER_URL +
        # PORTAINER_API_KEY from env — hence the subprocess_env_mapping that
        # swaps the key back to the upstream var name. Needs `uv` on PATH
        # (one-time dep sync in the submodule on first run).
        runtime_config={
            "image": "ghcr.io/kulik-labs-development/eepy-host-portainer:latest",
            "command": ["uv", "run", "mcp-portainer"],
            "cwd": "integrations/portainer-mcp",
            "env": {
                # Trusted-private-network posture: the sidecar is unreachable
                # outside the eepy-sidecars docker network.
                "PORTAINER_MCP_DANGEROUSLY_ALLOW_PLAINTEXT_HTTP": "1",
                # Accepts the bridge's fixed Host header (eepy-sidecar:17717).
                "PORTAINER_MCP_ALLOWED_HOSTS": "eepy-sidecar:*",
                # The upstream in-band guidance gate answers a caller's FIRST
                # tool call (per 1800s idle window) with the guide instead of
                # the tool result. Sidecars here are idle-reaped at 300s — a
                # respawn resets the gate, so the user's first call after any
                # 5-minute pause would return a ~30KB guide instead of their
                # result. Disable the gate: get_guidance stays available on
                # demand and the server's MCP instructions still point at it.
                "PORTAINER_MCP_DISABLE_GUIDANCE_GATE": "1",
            },
            "subprocess_env": {
                "PORTAINER_MCP_TRANSPORT": "stdio",
                "PORTAINER_MCP_DISABLE_GUIDANCE_GATE": "1",
            },
            "endpoint": "/mcp",
            "port": "17717",
            # Docker backend: key parked under an upstream-ignorable name.
            "env_mapping": {
                "PORTAINER_URL": "PORTAINER_URL",
                "PORTAINER_API_KEY": "EEPY_PORTAINER_API_KEY",
                "PORTAINER_TLS_VERIFY": "PORTAINER_TLS_VERIFY",
            },
            # Subprocess (stdio) backend: the upstream var name the stdio
            # transport actually reads.
            "subprocess_env_mapping": {
                "PORTAINER_URL": "PORTAINER_URL",
                "PORTAINER_API_KEY": "PORTAINER_API_KEY",
                "PORTAINER_TLS_VERIFY": "PORTAINER_TLS_VERIFY",
            },
            "generated_secrets": ["PORTAINER_MCP_AUTH_TOKEN"],
            "headers": {
                "Host": "eepy-sidecar:17717",
                "Authorization": "Bearer {{PORTAINER_MCP_AUTH_TOKEN}}",
                "X-Portainer-API-Key": "{{EEPY_PORTAINER_API_KEY}}",
            },
            # Read-only probe for POST /config/{id}/test: the server validates
            # the user's key (per request) before any tool runs, so a bad key
            # or unreachable instance fails the test loudly.
            "test_tool": {"name": "systemVersion", "arguments": {}},
            # Representative subset of the ~211 upstream tools so the OpenAPI
            # spec has entries before admin discovery stores the full
            # authoritative tools/list (discovery takes precedence).
            "tool_names": [
                "systemVersion", "systemStatus", "systemInfo", "MOTD",
                "EndpointList", "EndpointInspect", "dockerDashboard",
                "dockerImagesList", "StackList", "StackInspect",
                "GitOpsSourcesList", "GitOpsWorkflowsList", "HelmList",
                "HelmGet", "GetKubernetesNamespaces", "GetKubernetesNodes",
                "get_guidance",
            ],
        },
        approved_by_admin=True,
        enabled_global=True,
    )

    warden = MCPTemplate(
        id="warden",
        name="Warden (Vaultwarden / Bitwarden)",
        repo_url="https://github.com/icoretech/warden-mcp",
        description=(
            "Read and manage your Vaultwarden / Bitwarden vault across ~60 tools: "
            "search items, fetch usernames, passwords, and TOTP codes (secret fields "
            "redacted unless a tool is asked to reveal), and create, update, move, or "
            "delete items, folders, organizations, collections, attachments, and "
            "Sends. Built for agents that must log in to real systems without secrets "
            "in prompts. Works with an API key pair OR email login; credentials stay "
            "encrypted at rest and are proxied through the Eepy unified proxy."
        ),
        config_schema={
            "category": "Security / Password Management",
            "type": "object",
            "properties": {
                "VAULT_HOST": {
                    "type": "string",
                    "label": "Vault Host",
                    "placeholder": "https://vaultwarden.example.com",
                    "help": "HTTPS origin of your Vaultwarden/Bitwarden server (https only, no path or credentials).",
                    "required": True,
                },
                "MASTER_PASSWORD": {
                    "type": "password",
                    "label": "Master Password",
                    "help": "Your vault's master password (unlocks the vault for every session).",
                    "required": True,
                },
                "API_CLIENT_ID": {
                    "type": "string",
                    "label": "API Key Client ID",
                    "placeholder": "user.xxxxx",
                    "help": "Option A: Bitwarden API key pair (My Account > Security > API key). Leave both blank if you log in with your email instead.",
                    "required": False,
                },
                "API_CLIENT_SECRET": {
                    "type": "password",
                    "label": "API Key Client Secret",
                    "help": "Option A (continued): the secret shown once when the API key was generated.",
                    "required": False,
                },
                "LOGIN_USERNAME": {
                    "type": "string",
                    "label": "Login Email / Username",
                    "placeholder": "you@example.com",
                    "help": "Option B: log in with your account email instead of an API key pair. Fill either Option A or Option B, not both.",
                    "required": False,
                },
            },
            "required": ["VAULT_HOST", "MASTER_PASSWORD"],
        },
        image_tag="ghcr.io/kulik-labs-development/eepy-host-warden",
        runtime="mcp-server",
        # Modular sidecar spec (same contract as the Portainer reference) with
        # the per-request header machinery, because the upstream HTTP mode is
        # per-user passthrough: every /sse request (initialize AND tools/call)
        # must carry X-BW-Host + X-BW-Password + (X-BW-ClientId +
        # X-BW-ClientSecret) or X-BW-User. KEYCHAIN_ALLOW_ENV_FALLBACK stays
        # at its default false, so a headerless request can NEVER inherit the
        # sidecar's env identity — the headers ARE the auth layer.
        #
        # Upstream treats EMPTY header values as absent (trim → length 0),
        # which is what makes the dual login method work: the bridge always
        # sends all five headers, and the user's choice (API key pair vs email)
        # decides which ones carry values. For the placeholders to resolve,
        # every referenced env var must exist on the sidecar — so env /
        # subprocess_env carry STATIC EMPTY defaults for the three optional
        # login vars; mapped user credentials override them at spawn.
        #
        # State: bw profile state under /data/bw-profiles (KEYCHAIN_BW_HOME_ROOT)
        # is a warm cache only — sidecars are ephemeral (idle-reaped), so a
        # respawn re-authenticates from the per-request credentials (first call
        # after a reap costs a few extra seconds for bw login + unlock).
        #
        # Local (subprocess backend): stdio transport reads the BW_* env vars
        # and LOGS IN AT STARTUP (before the MCP handshake), so a misconfigured
        # sidecar fails loudly at spawn. Needs Node 24+ on the host PATH and a
        # one-time `npm install && npm run build` inside integrations/warden-mcp
        # (the postinstall applies the Vaultwarden compat patch to the bundled
        # @bitwarden/cli — do not use --ignore-scripts).
        runtime_config={
            "image": "ghcr.io/kulik-labs-development/eepy-host-warden:latest",
            "command": ["node", "bin/warden-mcp.js", "--stdio"],
            "cwd": "integrations/warden-mcp",
            # Docker backend (production): streamable-HTTP on :3005 at /sse.
            # Express binds all interfaces when WARDEN_MCP_HOST is unset, which
            # is exactly what the eepy-sidecars docker network dial needs.
            "env": {
                "PORT": "3005",
                "KEYCHAIN_BW_HOME_ROOT": "/data/bw-profiles",
                "BW_CLIENTID": "",
                "BW_CLIENTSECRET": "",
                "BW_USER": "",
            },
            # Subprocess backend (local dev): stdio mode; same static empty
            # defaults (readBwEnv treats empty values as absent too).
            "subprocess_env": {
                "BW_CLIENTID": "",
                "BW_CLIENTSECRET": "",
                "BW_USER": "",
            },
            "endpoint": "/sse",
            "port": "3005",
            "env_mapping": {
                "VAULT_HOST": "BW_HOST",
                "MASTER_PASSWORD": "BW_PASSWORD",
                "API_CLIENT_ID": "BW_CLIENTID",
                "API_CLIENT_SECRET": "BW_CLIENTSECRET",
                "LOGIN_USERNAME": "BW_USER",
            },
            # Per-request vault credentials (see header comment above).
            "headers": {
                "X-BW-Host": "{{BW_HOST}}",
                "X-BW-Password": "{{BW_PASSWORD}}",
                "X-BW-ClientId": "{{BW_CLIENTID}}",
                "X-BW-ClientSecret": "{{BW_CLIENTSECRET}}",
                "X-BW-User": "{{BW_USER}}",
            },
            # Read-only probe for POST /config/{id}/test: keychain_status is a
            # LAZY check (it reports "not ready" without unlocking), so the
            # test uses keychain_list_folders instead — it forces the full bw
            # login + unlock + list with the user's real credentials, so a bad
            # host / master password / login method fails the test loudly.
            # (A very large vault makes the first call do a full sync; the
            # EEPY_MCP_INSTANCE_CALL_TIMEOUT dial covers that.)
            "test_tool": {"name": "keychain_list_folders", "arguments": {}},
            # Representative subset of the upstream tool catalogue (prefix
            # keychain_) so the OpenAPI spec has entries before admin
            # discovery stores the authoritative tools/list.
            "tool_names": [
                "keychain_status", "keychain_sync", "keychain_search_items",
                "keychain_get_item", "keychain_get_username",
                "keychain_get_password", "keychain_get_totp",
                "keychain_create_login", "keychain_create_note",
                "keychain_create_card", "keychain_update_item",
                "keychain_move_item_to_organization", "keychain_delete_item",
                "keychain_restore_item", "keychain_list_folders",
                "keychain_create_folder", "keychain_list_organizations",
                "keychain_list_collections", "keychain_create_attachment",
                "keychain_get_attachment",                 "keychain_send_list",
                "keychain_generate", "keychain_sdk_version",
            ],
        },
        approved_by_admin=True,
        enabled_global=True,
    )

    proxmox = MCPTemplate(
        id="proxmox",
        name="Proxmox VE",
        repo_url="https://github.com/RekklesNA/ProxmoxMCP-Plus",
        description=(
            "Manage your Proxmox VE cluster across ~45 tools: full VM and LXC "
            "lifecycle (create, clone, start, stop, delete), snapshots with "
            "rollback, VZDump backups and restores, ISO download and cleanup, "
            "storage and cluster inspection, node, task, and guest firewall "
            "logs, plus persistent job tracking (poll, retry, cancel) for "
            "long-running Proxmox tasks. Runs against YOUR Proxmox with your "
            "own API token (create one with the least privileges your workflow "
            "needs); credentials stay encrypted at rest and are proxied through "
            "the Eepy unified proxy."
        ),
        config_schema={
            "category": "Infrastructure / Virtualization",
            "type": "object",
            "properties": {
                "PROXMOX_HOST": {
                    "type": "string",
                    "label": "Proxmox Host",
                    "placeholder": "192.168.1.10",
                    "help": "Hostname or IP of your Proxmox VE API server.",
                    "required": True,
                },
                "PROXMOX_USER": {
                    "type": "string",
                    "label": "API User",
                    "placeholder": "root@pam",
                    "help": "Proxmox user the API token belongs to (e.g. root@pam, mcp@pve).",
                    "required": True,
                },
                "PROXMOX_TOKEN_NAME": {
                    "type": "string",
                    "label": "API Token Name",
                    "placeholder": "eepy",
                    "help": "Datacenter > Permissions > API Tokens: the token name you created.",
                    "required": True,
                },
                "PROXMOX_TOKEN_VALUE": {
                    "type": "password",
                    "label": "API Token Value",
                    "help": "The token secret, shown once when the token is created.",
                    "required": True,
                },
                "PROXMOX_PORT": {
                    "type": "string",
                    "label": "API Port",
                    "placeholder": "8006",
                    "help": "Optional. Proxmox API port (default: 8006).",
                    "required": False,
                },
                "PROXMOX_VERIFY_SSL": {
                    "type": "string",
                    "label": "Verify TLS Certificates",
                    "placeholder": "true",
                    "help": "Optional. Set false if your Proxmox uses a self-signed certificate (default: true).",
                    "required": False,
                },
            },
            "required": ["PROXMOX_HOST", "PROXMOX_USER", "PROXMOX_TOKEN_NAME", "PROXMOX_TOKEN_VALUE"],
        },
        image_tag="ghcr.io/kulik-labs-development/eepy-host-proxmox",
        runtime="mcp-server",
        # Modular sidecar spec (same contract as the HappyFox reference) with
        # the per-sidecar bearer gate from the bridge's generated_secrets +
        # headers machinery:
        #
        #  - The upstream HTTP mode wraps its Streamable-HTTP app in a Bearer
        #    middleware whenever MCP_API_KEY is set (constant-time compare;
        #    every request, including initialize, must carry
        #    `Authorization: Bearer <key>`). The bridge mints a FRESH random
        #    MCP_API_KEY into the sidecar env on every spawn and resolves the
        #    same value into the per-request Authorization header, so a
        #    headerless client on the sidecar network gets 401 and the key is
        #    never stored.
        #  - No Host header override is needed (unlike Portainer): with
        #    MCP_HOST=0.0.0.0 the mcp SDK (verified on 1.29) leaves its
        #    DNS-rebinding Host validation disabled, so the bridge's direct
        #    container-IP dial on the eepy-sidecars network passes as-is.
        #  - Credentials ride env vars: upstream reads PROXMOX_* from the
        #    environment whenever PROXMOX_MCP_CONFIG is unset (no config file
        #    mount needed). Upstream safety defaults are kept: TLS verification
        #    ON (opt-out per user via PROXMOX_VERIFY_SSL) and command policy
        #    deny_all, which locks the in-guest command-execution tools unless
        #    an operator opts in — the user's Proxmox API token (least
        #    privilege) is the real authorization boundary either way.
        #
        # Production (docker backend): the image serves streamable-HTTP on
        # :8000 at /mcp, reachable only on the internal eepy-sidecars docker
        # network. Local (subprocess backend): stdio transport via
        # subprocess_env; needs a one-time `pip install -e
        # integrations/proxmox-mcp` in the backend's own interpreter (the
        # bridge puts it first on PATH; the package itself imports from the
        # submodule cwd).
        runtime_config={
            "image": "ghcr.io/kulik-labs-development/eepy-host-proxmox:latest",
            "command": ["python", "-m", "proxmox_mcp.server"],
            "cwd": "integrations/proxmox-mcp",
            # Docker backend env: streamable-HTTP on :8000 (upstream
            # normalizes STREAMABLE_HTTP to the SDK's STREAMABLE mode).
            "env": {
                "MCP_TRANSPORT": "STREAMABLE_HTTP",
                "MCP_HOST": "0.0.0.0",
                "MCP_PORT": "8000",
            },
            # Subprocess backend env (local dev): stdio handshake, no HTTP
            # transport vars.
            "subprocess_env": {"MCP_TRANSPORT": "stdio"},
            "endpoint": "/mcp",
            "port": "8000",
            "env_mapping": {
                "PROXMOX_HOST": "PROXMOX_HOST",
                "PROXMOX_USER": "PROXMOX_USER",
                "PROXMOX_TOKEN_NAME": "PROXMOX_TOKEN_NAME",
                "PROXMOX_TOKEN_VALUE": "PROXMOX_TOKEN_VALUE",
                "PROXMOX_PORT": "PROXMOX_PORT",
                "PROXMOX_VERIFY_SSL": "PROXMOX_VERIFY_SSL",
            },
            # Fresh per-spawn Bearer gate (see comment above).
            "generated_secrets": ["MCP_API_KEY"],
            "headers": {
                "Authorization": "Bearer {{MCP_API_KEY}}",
            },
            # Read-only probe for POST /config/{id}/test: lists cluster nodes,
            # so a bad token, unreachable host, or TLS mismatch fails the
            # test loudly without touching any resource.
            "test_tool": {"name": "get_nodes", "arguments": {}},
            # The full tool set the upstream registers without an [ssh]
            # config section (the two SSH-backed container-command tools are
            # not registered in env-var mode). Admin discovery overwrites
            # this with the authoritative tools/list.
            "tool_names": [
                "get_nodes", "get_node_status", "get_storage",
                "get_cluster_status",
                "list_jobs", "get_job", "poll_job", "cancel_job", "retry_job",
                "get_vms", "get_vm_config", "set_vm_description", "create_vm",
                "clone_vm", "execute_vm_command", "start_vm", "stop_vm",
                "shutdown_vm", "reset_vm", "delete_vm",
                "get_containers", "get_container_config",
                "set_container_description", "get_container_ip",
                "create_container", "start_container", "stop_container",
                "restart_container", "update_container_resources",
                "delete_container",
                "list_snapshots", "create_snapshot", "delete_snapshot",
                "rollback_snapshot",
                "list_isos", "list_templates", "download_iso", "delete_iso",
                "list_backups", "create_backup", "restore_backup",
                "delete_backup",
                "get_node_syslog", "get_task_log", "get_cluster_log",
                "get_node_firewall_log", "get_guest_firewall_log",
            ],
        },
        approved_by_admin=True,
        enabled_global=True,
    )

    db = SessionLocal()
    try:
        for spec in (happyfox, ebay, portainer, warden, proxmox):
            existing = db.query(MCPTemplate).filter(MCPTemplate.id == spec.id).first()
            if existing:
                existing.approved_by_admin = True
                existing.enabled_global = True
                existing.description = spec.description
                existing.config_schema = spec.config_schema
                existing.image_tag = spec.image_tag
                existing.repo_url = spec.repo_url
                # Roll forward to the modular sidecar runtime on every boot so
                # the seeded templates always match this code's expectations.
                existing.runtime = spec.runtime
                existing.runtime_config = spec.runtime_config
                db.commit()
                logger.info(f"{spec.name} MCP template exists; ensured enabled (mcp-server runtime).")
            else:
                db.add(spec)
                db.commit()
                logger.info(f"Seeded {spec.name} MCP template (approved, mcp-server runtime).")
    finally:
        db.close()

def _log_boot_data_summary() -> None:
    """One boot-time line into the debug console telling the operator whether
    persistent data survived a redeploy: users=0 / mcp_configs=0 right after
    a Portainer redeploy means the postgres volume was NOT carried over (the
    stack was re-imported under a different project name, or `down -v` was
    run) — no amount of code change can recover data the DB does not have."""
    try:
        db = SessionLocal()
        try:
            from models.mcp_models import MCPUserToolKey, UserMCPConfig
            users = db.query(User).count()
            configs = db.query(UserMCPConfig).count()
            keys = db.query(MCPUserToolKey).count()
            templates = db.query(MCPTemplate).count()
        finally:
            db.close()
        logger.info(
            f"Boot data summary: users={users} mcp_configs={configs} tool_keys={keys} "
            f"templates={templates} (all zero after a redeploy = postgres volume was not carried over)"
        )
    except Exception as e:
        logger.warning(f"Boot data summary unavailable: {e.__class__.__name__}: {e}")


def _init_database_with_retry(max_attempts: int = 10, delay_s: float = 3.0) -> None:
    """Create tables, sync columns, seed templates, bootstrap the initial
    superuser — RETRYING while the database comes up.

    On a fresh deploy the db container is started (depends_on) but Postgres
    may not accept connections for a few seconds yet. The old single attempt
    at import time swallowed the failure: the app then served with NO tables
    (signup and every credential write 500) and no superuser promotion —
    until a manual container restart. Retrying makes the stack self-heal on
    boot; every attempt is logged to the debug console.
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            sync_database_schema()
            seed_mcp_templates()
            bootstrap_superuser()
            logger.info("Database initialized and synchronized.")
            _log_boot_data_summary()
            return
        except Exception as e:
            last_err = e
            logger.warning(
                f"Database not ready (attempt {attempt}/{max_attempts}): "
                f"{e.__class__.__name__}: {str(e).splitlines()[0] if str(e) else e}"
            )
            if attempt < max_attempts:
                time.sleep(delay_s)
    logger.error(f"Critical error initializing database after {max_attempts} attempts: {last_err}")


try:
    _init_database_with_retry()
except Exception as e:
    logger.error(f"Critical error initializing database: {e}")

# MCP endpoints (Phase 5: HappyFox template #1). Absolute import (never relative):
# Uvicorn runs this module top-level.
from api import mcp_bridge, mcp_stream  # noqa: E402  (mcp_stream: native MCP endpoint /api/mcp/mcp)
from api.mcp_endpoints import router as mcp_router  # noqa: E402

app = FastAPI(title="Eepy Host API")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifecycle: sweep orphaned sidecars from the last boot,
    start the MCP sidecar idle-reaper, tear down live sidecars on shutdown."""
    import asyncio

    # Surface a missing Docker socket mount AT BOOT instead of on the user's
    # first 'Run live test' click: Portainer stacks created from an older
    # compose file have no /var/run/docker.sock bind mount on the backend,
    # in which case sidecar spawning can never succeed.
    daemon_ok, daemon_detail = await asyncio.to_thread(mcp_bridge.check_docker_daemon)
    if daemon_ok:
        logger.info(f"mcp-bridge: docker daemon {daemon_detail}")
    else:
        logger.error(
            f"mcp-bridge: Docker daemon NOT reachable - MCP sidecars will fail on every "
            f"tool call until this is fixed. {daemon_detail}"
        )

    # Boot reconciliation: every mcp_sidecars row is a leftover sidecar still
    # holding a user's decrypted credentials in their env (OOM kill, kill -9,
    # host reboot, Portainer remove). Remove it; the next request re-spawns.
    await asyncio.to_thread(mcp_bridge.sweep_orphan_sidecars)
    mcp_bridge.ensure_reaper_started()
    # The MCP streamable-HTTP session manager must be running for the duration
    # of the app (its task group handles /api/mcp/mcp requests).
    async with mcp_stream.session_manager.run():
        try:
            yield
        finally:
            # Blocking Docker/proc teardown must not stall the event loop even
            # at shutdown time.
            await asyncio.to_thread(mcp_bridge.shutdown_all_instances)


app.router.lifespan_context = _lifespan

# --- RATE LIMITING ---
# Brute-force protection for credential endpoints. In-memory limiter (single
# backend process); keyed by client IP.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount the MCP integration router (Phase 5: HappyFox template #1).
app.include_router(mcp_router)

# Native MCP endpoint (AI Platform connector): an ASGI middleware intercepts
# /api/mcp/mcp BEFORE routing (the MCP streamable-HTTP manager is not a
# FastAPI route). Added before the CORS middleware below so CORS stays
# OUTERMOST and MCP responses carry the normal CORS headers.
app.add_middleware(mcp_stream.MCPStreamAuthMiddleware, manager=mcp_stream.session_manager)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.url.path}: {exc.errors() if callable(getattr(exc, 'errors', None)) else exc.errors}")
    errors = exc.errors() if callable(getattr(exc, "errors", None)) else exc.errors
    first_error = errors[0] if errors else {"msg": "Invalid request data"}
    return JSONResponse(
        status_code=422,
        content={"detail": first_error.get("msg", "Validation failed")},
    )

# CORS: browser-based clients (notably Open WebUI, which fetches the spec AND
# calls the proxy from its own origin) send preflights from whatever domain the
# user self-hosts them on. Default to allowing ALL origins: the API is
# Bearer-token authenticated only (no cookie sessions), so a wildcard origin
# cannot leak cross-origin data — the token itself is the security boundary.
# Operators can pin an exact comma-separated origin list via CORS_ORIGINS; an
# explicit list re-enables credentials mode for those origins.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if not _cors_origins:
    _cors_origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# NOTE: sync `def` on purpose — FastAPI runs these in the threadpool, so the
# JWT decode + DB lookup never block the event loop. (Async endpoints below
# that only do sync work have the same problem and must stay sync def too.)
def get_current_user(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")

    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

def get_superuser(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.SUPERUSER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operation restricted to superusers only")
    return current_user

@app.get("/")
def root():
    return {"status": "online", "message": "Welcome to Eepy Host API. Stay cozy."}

@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

@app.post("/auth/signup")
@limiter.limit("5/hour")
def signup(
    request: Request,
    user_in: UserCreate,
    db: Session = Depends(get_db),
):
    try:
        logger.info(f"Signup request received for user: {user_in.username}")
        # Case-insensitive uniqueness for BOTH username and email: "User123"
        # and "user123" are the same identity (clash), and email is
        # conventionally case-insensitive as well.
        existing_user = db.query(User).filter(
            (func.lower(User.username) == user_in.username.lower())
            | (func.lower(User.email) == user_in.email.lower())
        ).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username or email already registered (usernames are case-insensitive)")

        # SECURITY: role is NOT accepted from the client. Every account starts
        # as USER; superuser status comes only from the SUPERUSER_USERNAME
        # bootstrap or an admin role change (see /superuser/* endpoints).
        new_user = User(
            username=user_in.username,
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password[:72]),
            role=UserRole.USER,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info(f"New user created: {user_in.username}")
        return {"message": "Account created successfully", "user_id": new_user.id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during signup")
        raise HTTPException(status_code=500, detail="Internal server error") from None

@app.post("/auth/login")
@limiter.limit("10/minute")
def login(
    request: Request,
    credentials: UserLogin,
    db: Session = Depends(get_db),
):
    try:
        # The identifier may be the username OR the account's email address;
        # both are matched case-insensitively.
        logger.info(f"Login request received for identifier: {credentials.username}")
        identifier = credentials.username
        user = db.query(User).filter(
            (func.lower(User.username) == identifier.lower())
            | (func.lower(User.email) == identifier.lower())
        ).first()
        # Always run bcrypt on a dummy hash when the user does not exist so
        # response timing does not reveal which usernames are registered.
        # The message deliberately does not say WHICH part was wrong (no user
        # enumeration) but does state that username or email is accepted.
        invalid_detail = "Invalid credentials. You can sign in with your username or email address."
        if not user:
            verify_password(credentials.password[:72], DUMMY_HASH)
            raise HTTPException(status_code=401, detail=invalid_detail)
        if not verify_password(credentials.password[:72], user.hashed_password):
            raise HTTPException(status_code=401, detail=invalid_detail)
        # Opportunity to promote the configured initial superuser if their
        # account only existed after the last boot (see bootstrap_superuser).
        # Cheap: one string comparison, write only on the rare promotion.
        if (
            os.getenv("SUPERUSER_USERNAME", "").strip().lower() == user.username.lower()
            and user.role != UserRole.SUPERUSER
        ):
            user.role = UserRole.SUPERUSER
            db.commit()
            logger.info(f"Promoted {user.username} to superuser at login (SUPERUSER_USERNAME).")
        token = create_access_token({"sub": user.username, "role": user.role})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {"username": user.username, "role": user.role, "email": user.email, "full_name": user.full_name}
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during login")
        raise HTTPException(status_code=500, detail="Internal server error") from None

@app.get("/user/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    return {"full_name": current_user.full_name, "email": current_user.email, "profile_picture": current_user.profile_picture, "username": current_user.username}

class ProfileUpdateIn(BaseModel):
    full_name: str | None = None


@app.patch("/user/profile")
def update_profile(body: ProfileUpdateIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if body.full_name is not None:
            current_user.full_name = body.full_name[:255]
            db.commit()
            db.refresh(current_user)
        return {"message": "Profile updated successfully", "full_name": current_user.full_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile") from e

@app.post("/user/avatar")
def upload_avatar(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"Avatar upload started for user: {current_user.username}")
        if not file.content_type.startswith("image/"):
            logger.warning(f"Invalid file type attempted by {current_user.username}: {file.content_type}")
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload an image.")
        # Sync def + file.file (the SpooledTemporaryFile underneath UploadFile):
        # the bounded read runs in the threadpool, never on the event loop.
        # Bounded read: never buffer more than the cap + 1 byte, then reject
        # oversized uploads before they touch the database.
        contents = file.file.read(MAX_AVATAR_BYTES + 1)
        if len(contents) > MAX_AVATAR_BYTES:
            logger.warning(f"Oversized avatar rejected for {current_user.username}: {len(contents)} bytes > {MAX_AVATAR_BYTES}")
            raise HTTPException(status_code=413, detail=f"Avatar too large. Maximum size is {MAX_AVATAR_BYTES // (1024 * 1024)} MB.")
        base64_encoded = base64.b64encode(contents).decode('utf-8')
        logger.info(f"Encoded image for {current_user.username} to Base64 string of length {len(base64_encoded)} bytes")
        data_uri = f"data:{file.content_type};base64,{base64_encoded}"
        current_user.profile_picture = data_uri
        db.commit()
        db.refresh(current_user)
        logger.info(f"Avatar successfully persisted to database for {current_user.username}.")
        return {"message": "Avatar uploaded successfully", "profile_picture": data_uri}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error uploading avatar for {current_user.username}")
        raise HTTPException(status_code=500, detail="Failed to upload avatar") from e

@app.get("/superuser/users", response_model=list[dict])
def list_all_users(superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "email": u.email, "full_name": u.full_name, "role": u.role, "total_requests": u.total_requests, "created_at": u.created_at} for u in users]

@app.get("/superuser/logs")
def get_system_logs(superuser: User = Depends(get_superuser)):
    return list(memory_handler.buffer)

@app.patch("/superuser/users/{user_id}/role")
def update_user_role(user_id: int, role: str, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    try:
        new_role = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role specified") from None
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = new_role
    db.commit()
    logger.info(f"Superuser {superuser.username} updated user {user.username} role to {role}")
    return {"message": f"User {user.username} role updated to {role}"}

@app.post("/superuser/users/{user_id}/password")
def reset_user_password(user_id: int, body: PasswordResetIn, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    # SECURITY: password arrives in the JSON body, never the URL query string
    # (query strings end up in access logs, proxy logs, and browser history).
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = get_password_hash(body.password[:72])
    db.commit()
    logger.info(f"Superuser {superuser.username} reset password for user {user.username}")
    return {"message": f"Password for {user.username} has been reset successfully"}

@app.delete("/superuser/users/{user_id}")
def delete_user_by_admin(user_id: int, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if target_user.id == superuser.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own superuser account")
    db.delete(target_user)
    db.commit()
    return {"message": f"User {target_user.username} has been removed from the system"}

class AdminUserUpdateIn(BaseModel):
    full_name: str | None = None
    email: str | None = None
    role: str | None = None


@app.patch("/superuser/users/{user_id}/update")
def update_user_details(user_id: int, body: AdminUserUpdateIn, superuser: User = Depends(get_superuser), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if body.full_name is not None:
            user.full_name = body.full_name[:255]
        if body.email is not None:
            if "@" not in body.email:
                raise HTTPException(status_code=400, detail="Invalid email")
            user.email = body.email
        if body.role is not None:
            try:
                user.role = UserRole(body.role)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid role specified") from None
        db.commit()
        db.refresh(user)
        return {"message": "User updated successfully", "user": user.username}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin update error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user") from e


# ---------------------------------------------------------------------------
# Superuser: MCP template runtime management (modular sidecar integrations)
# ---------------------------------------------------------------------------
class TemplateRuntimeIn(BaseModel):
    runtime: str | None = None  # "native" | "mcp-server"
    runtime_config: dict | None = None  # sidecar spec (image/command/env_mapping/...)
    approved_by_admin: bool | None = None
    enabled_global: bool | None = None


@app.patch("/superuser/mcp/templates/{template_id}/runtime")
def update_mcp_template_runtime(
    template_id: str,
    body: TemplateRuntimeIn,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db),
):
    """Register/update the sidecar spec for an integration.

    `runtime_config` never contains secrets -- only template-level static
    config (image, command, env mapping, endpoint, test_tool). User secrets
    come from each user's encrypted config and are injected per sidecar.
    """
    template = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    if body.runtime is not None:
        if body.runtime not in ("native", "mcp-server"):
            raise HTTPException(status_code=400, detail="runtime must be 'native' or 'mcp-server'.")
        template.runtime = body.runtime
    if body.runtime_config is not None:
        template.runtime_config = body.runtime_config
    if body.approved_by_admin is not None:
        template.approved_by_admin = body.approved_by_admin
    if body.enabled_global is not None:
        template.enabled_global = body.enabled_global
    db.commit()
    logger.info(f"Superuser {superuser.username} updated runtime for template '{template_id}'")
    return {"status": "updated", "template_id": template_id, "runtime": template.runtime}


class TemplateDiscoveryOut(BaseModel):
    id: str
    name: str
    runtime: str
    tool_count: int
    tools_discovered_at: str | None


@app.get("/superuser/mcp/templates", response_model=list[TemplateDiscoveryOut])
def list_mcp_template_discovery(
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db),
):
    """Discovery state for every approved template (superuser dashboard).

    The unified OpenAPI spec is built from discovered_tools; a template with
    tool_count=0 is serving name-only UNTYPED tools, so Open WebUI presents
    them as parameter-less and argument-taking tools fail upstream with
    'Field required'. The dashboard shows this state so discovery is never
    silently skipped again.
    """
    rows = (
        db.query(MCPTemplate)
        .filter(MCPTemplate.approved_by_admin == True)  # noqa: E712
        .order_by(MCPTemplate.name)
        .all()
    )
    out: list[dict] = []
    for t in rows:
        tools = [x for x in (t.discovered_tools or []) if isinstance(x, dict) and x.get("name")]
        out.append({
            "id": t.id,
            "name": t.name,
            "runtime": t.runtime,
            "tool_count": len(tools),
            "tools_discovered_at": t.tools_discovered_at.isoformat() if t.tools_discovered_at else None,
        })
    return out


@app.post("/superuser/mcp/templates/{template_id}/discover")
async def discover_mcp_tools(
    template_id: str,
    superuser: User = Depends(get_superuser),
    db: Session = Depends(get_db),
):
    """Run tools/list against the template's sidecar using the superuser's OWN
    stored credentials for that template, and store the result on the row.

    This is what makes a new upstream-repo integration appear in the unified
    OpenAPI spec (and dashboard) with zero backend code: the upstream repo's
    author owns the tool definitions; we just capture them. The sidecar is
    ephemeral and is torn down immediately after discovery.
    """
    from api.mcp_bridge import discover_tools_for_template
    from utils.crypto import decrypt_credentials

    template = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    if template.runtime != "mcp-server":
        raise HTTPException(status_code=400, detail="Template does not use the mcp-server runtime.")

    cfg_row = (
        db.query(mcp_models.UserMCPConfig)
        .filter(mcp_models.UserMCPConfig.owner_id == superuser.id,
                mcp_models.UserMCPConfig.template_name == template_id,
                mcp_models.UserMCPConfig.is_active == True)  # noqa: E712
        .first()
    )
    if not cfg_row:
        raise HTTPException(
            status_code=400,
            detail=f"You must first connect to '{template_id}' with your own account "
                   f"(dashboard > Connect) before discovering its tools.",
        )

    try:
        credentials = decrypt_credentials(cfg_row.credentials_json)  # memory-only
    except Exception as exc:
        logger.warning(
            f"mcp: superuser {superuser.username} discovery aborted - stored {template_id} "
            f"credentials could not be decrypted (encryption key changed?). Re-connect first."
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Your saved {template_id} credentials can no longer be decrypted (the server's "
                f"encryption key changed). Re-enter them via dashboard → MCP Servers → Connect, "
                f"then run discovery again."
            ),
        ) from exc

    tools = await discover_tools_for_template(db, superuser, template, credentials)
    template.discovered_tools = tools
    template.tools_discovered_at = datetime.now(UTC)
    db.commit()
    logger.info(f"Superuser {superuser.username} discovered {len(tools)} tools for '{template_id}'")
    return {"template_id": template_id, "tool_count": len(tools), "tools": [t["name"] for t in tools]}
