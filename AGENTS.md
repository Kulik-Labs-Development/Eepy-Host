# Eepy Host — System Blueprint and Agent Instructions

> This file is the single source of truth for project state, architecture, and
> conventions. Historical planning documents (`PHASE_4_IMPLEMENTATION_PLAN.md`)
> are archived references only — where they disagree with this file or the code,
> the code wins.

## Project Overview

Eepy Host (https://github.com/Kulik-Labs-Development/Eepy-Host) is a managed
SaaS MCP gateway. Users connect integrations (HappyFox today; Google Calendar,
Slack Workspaces, Notion Databases, etc. on the roadmap); Eepy handles the API
plumbing, credential management (encrypted at rest), and unified proxy routing
(`/api/mcp/proxy/{template_id}/{tool_name}`) so their agent can use external
tools without operational overhead. Agents reach Eepy through TWO connectors,
both unlocked by one per-user Tool API Key: the **OpenAPI REST proxy** (for
Open WebUI-style tool-server imports) and a **native MCP endpoint**
(`POST /api/mcp/mcp`, streamable-HTTP — for MCP clients like opencode, Claude
Desktop, Cursor; see "Native MCP endpoint" below).

**Core architecture principle:** this is NOT a container orchestration
platform for the *control plane*. One unified FastAPI backend owns auth,
credentials (encrypted at rest), and all proxy routing. Integration MCP
server code lives in **separate upstream repos**, pulled into this project as
git submodules under `integrations/` (HappyFox:
`integrations/happyfox-mcp` → github.com/Glitch3dPenguin/happyfox-mcp;
eBay: `integrations/ebay-mcp` → github.com/YosefHayim/ebay-mcp;
Portainer: `integrations/portainer-mcp` →
github.com/portainer/portainer-mcp).
CI builds each submodule's code into its own GHCR sidecar image on every
push, so the deployed gateway always runs exactly the code this repo pins —
updating an integration is "bump the submodule ref", never editing its code
here. The backend spawns those sidecars per user (subprocess locally,
docker container in production), short-lived and idle-reaped.

## Current State (Phase 5 complete: modular MCP sidecar runtime + native MCP endpoint)

- Unified auth portal + dashboard hub (account, debug console, organization
  admin tools for superusers, servers).
- HappyFox Help Desk is Template #1: seeded at startup in `main.py`
  (`seed_mcp_templates()`, idempotent) with `approved_by_admin=True`, and runs
  on the **modular sidecar runtime** (`runtime=mcp-server`) from the
  `integrations/happyfox-mcp` git submodule (its own upstream repo) — CI
  builds that submodule into the `eepy-host-happyfox` GHCR sidecar image —
  the reference implementation for every future integration.
- eBay Sell is Template #2, same modular pattern: seeded at startup and run
  from the `integrations/ebay-mcp` git submodule (github.com/YosefHayim/
  ebay-mcp, a TypeScript/Node server — 299 tools over the eBay Sell APIs)
   built by CI into the `eepy-host-ebay` GHCR sidecar image. Its HTTP
   sidecar runs with `OAUTH_ENABLED=false` (the sidecar is only reachable on
   the internal `eepy-sidecars` docker network, and the unified proxy IS the
   auth layer) and its stdio dev path needs a one-time
   `pnpm install --ignore-scripts && pnpm run build` in the submodule.
- Portainer is Template #3, same modular pattern from the
  `integrations/portainer-mcp` git submodule (github.com/portainer/
  portainer-mcp — the OFFICIAL Portainer MCP server, Python/FastMCP, ~211
  tools over the Portainer API: environments, Docker, Kubernetes, Helm,
  stacks, GitOps + Docker/K8s proxy). First integration to use the bridge's
  **per-request header** machinery, because its HTTP mode is per-user
  passthrough: every request must carry a gate bearer
  (`Authorization`) AND the user's own key (`X-Portainer-API-Key`), the
  server refuses to boot with `PORTAINER_API_KEY` set under HTTP (stdio-only),
  and it 421-rejects Hosts outside `PORTAINER_MCP_ALLOWED_HOSTS`. The bridge
  therefore (a) mints a fresh per-sidecar gate token
  (`runtime_config.generated_secrets`), (b) sends the resolved headers on
  every MCP request, and (c) dials with a fixed `Host: eepy-sidecar:17717`
  header the seed's allowlist accepts. The in-band guidance gate is disabled
  in the sidecar env (`PORTAINER_MCP_DISABLE_GUIDANCE_GATE=1`) because
  sidecars idle-reap at 300s while the gate's window is 1800s — a respawn
  would bounce the user's first call after any 5-minute pause (see the
  bridge section). Match the server's minor version to the user's Portainer
   minor (2.44.x ↔ 2.44.x); the local-dev (subprocess) path needs `uv` on
   PATH (one-time dep sync in the submodule on first run).
- Warden (Vaultwarden/Bitwarden) is Template #4, same modular pattern from the
  `integrations/warden-mcp` git submodule (github.com/icoretech/warden-mcp —
  a TypeScript/Node server, 53 tools over the Bitwarden CLI: search/read items
  with redacted secrets, fetch usernames/passwords/TOTP, create/update/move/
  delete items, folders, organizations, collections, attachments, Sends).
  Second integration on the bridge's **per-request header** machinery: its
  HTTP mode (Streamable-HTTP on :3005 at `/sse`) resolves vault credentials
  from `X-BW-Host` + `X-BW-Password` + (`X-BW-ClientId` + `X-BW-ClientSecret`)
  OR `X-BW-User` on EVERY request, and `KEYCHAIN_ALLOW_ENV_FALLBACK` stays off
  so a headerless request can never inherit the sidecar's identity. Dual
  login method (API key pair vs email) means three of the five headers are
  optional — the seed carries STATIC EMPTY defaults for those env vars (the
  bridge hard-fails on a header placeholder whose env var is absent; mapped
  user credentials override the defaults at spawn) and upstream treats empty
  header values as absent, so the user's chosen method wins. The
  connection-test probe is `keychain_list_folders` because `keychain_status`
  is a LAZY check that reports "not ready" without validating credentials.
  The sidecar image's `npm ci` MUST run lifecycle scripts: the package's
  postinstall applies the Vaultwarden compatibility patch to the bundled
  `@bitwarden/cli` (never `--ignore-scripts` here). Local-dev (subprocess)
  path needs Node 24+ on PATH and a one-time `npm install && npm run build`
  in the submodule.
- Proxmox VE is Template #5, same modular pattern from the
  `integrations/proxmox-mcp` git submodule (github.com/RekklesNA/
  ProxmoxMCP-Plus — MIT, Python/FastMCP, ~45 tools: full VM/LXC lifecycle,
  snapshots with rollback, VZDump backup/restore, ISO download/cleanup,
  storage/cluster inspection, node/task/guest-firewall logs, and persistent
  job tracking with poll/retry/cancel). Third integration on the bridge's
  **per-request header** machinery, in its simplest form: the upstream HTTP
  mode (Streamable-HTTP on :8000 at `/mcp`) wraps the app in a Bearer
  middleware whenever `MCP_API_KEY` is set, so the bridge mints a fresh
  per-sidecar `MCP_API_KEY` (`generated_secrets`) and sends it as the
  per-request `Authorization` header — one generated secret, no user
  credentials in headers. Unlike Portainer, NO fixed Host override is
  needed: with `MCP_HOST=0.0.0.0` the mcp SDK (verified on 1.29) leaves its
  DNS-rebinding Host validation disabled, so the bridge's direct container-IP
  dial passes as-is. Credentials ride `PROXMOX_*` env vars (upstream env-var
  config mode, no config-file mount); upstream safety defaults are kept —
  TLS verification ON (user opt-out via `PROXMOX_VERIFY_SSL=false` for
  self-signed certs) and command policy `deny_all`, which locks the in-guest
  command-execution tools unless an operator opts in; the user's least-
  privilege Proxmox API token is the real authorization boundary. The
  upstream pyproject already pins `mcp>=1.8,<2`, so the image needs no extra
  mcp pin (unlike happyfox). Local-dev (subprocess) path: one-time
  `pip install -e integrations/proxmox-mcp` in the backend's interpreter.
- The unified proxy (`/api/mcp/proxy/{template_id}/{tool_name}`) routes by
  template `runtime`: `mcp-server` → generic bridge (`api/mcp_bridge.py`),
  `native` → hardcoded `TEMPLATE_REGISTRY` (HappyFox reference path, kept for
  rollback).
- Open WebUI integration: per-user **Tool API Keys** (`eekey_...`, one key
  unlocks every integration) + a single unified OpenAPI spec for import.
  The spec is generated from the DB (admin-discovered `tools/list` output for
  mcp-server templates; `TEMPLATE_REGISTRY` for native). Open WebUI calls the
  API from **its browser origin** (spec fetch AND proxy calls), so CORS is
  wildcard by default (`CORS_ORIGINS` env pins an exact list; safe because
  auth is Bearer-token only, no cookie sessions). Open WebUI also **appends
   `/openapi.json`** to the pasted URL, so users paste the base URL
   (`https://<host>/api/mcp`) and the backend serves the spec at BOTH
   `/api/mcp/openapi.json` and `/api/mcp/openapi.json/openapi.json`.
- **AI Platform connector (native MCP):** `POST /api/mcp/mcp` is a real
  Model Context Protocol endpoint (mcp SDK `StreamableHTTPSessionManager`,
  **stateless** + JSON responses — multi-replica safe, no SSE buffering
  issues) implemented in `api/mcp_stream.py`. Same one-key contract as the
  proxy: a Tool API Key (or session JWT) + URL is the whole setup for
  opencode / Claude Desktop / Cursor / any streamable-HTTP MCP client.
  `tools/list` is PER-USER (only the caller's ACTIVE connections, names
  `{template}__{tool}`); `tools/call` routes exactly like the REST proxy
  (bridge for mcp-server, registry for native) with the same per-call
  credential checks; built-in `eepy__status` tool shows what is connected.
  The dashboard's "AI Platforms (MCP)" section
  (`AIPlatformConnectorPanel`) creates keys and offers copy-paste configs
  per client. Eepy-side tools surface upstream errors as `isError` MCP
  results (never transport errors) so the agent can read and react to them.

## Key Architecture Decisions

1. **Single backend endpoint per integration** — proxy routes; the
   integration code itself lives in an upstream MCP server repo (sidecar),
   never vendored into this backend. We own ONE generic bridge.
   (`runtime=native` + `TEMPLATE_REGISTRY` is the legacy/reference path only.)
2. **Credentials encrypted at rest** in PostgreSQL (`credentials_json`
   column) via Fernet. Decrypted ONLY temporarily inside request handlers —
   NEVER written to disk or logs.
3. **Fernet key resolution** (`backend/utils/crypto.py`): `MCP_ENCRYPTION_KEY`
   env var (valid Fernet key) takes priority; otherwise a key is derived
   deterministically from `SECRET_KEY` (SHA-256 → urlsafe b64). This fallback
   means rotating `SECRET_KEY` rotates the credential encryption key too —
   if you ever rotate it in production, stored credentials stop decrypting.
4. **Admin approval gate** — templates only appear in the library once a
   superuser sets `approved_by_admin` / `enabled_global`. This is also where
   the monetization pipeline starts (user template requests → admin review).
5. **Role hierarchy** — strict USER / SUPERUSER roles. Every `/superuser/*`
   endpoint enforces the role server-side via a dependency; frontend gating
   (`AuthContext.user.role === 'SUPERUSER'`) is cosmetic only — the backend is
   the source of truth.

## Technical Stack

- **Frontend:** Next.js (App Router) + TypeScript, Tailwind ("Retro Cozy"
  pixel-art aesthetic: warm `night` aubergine base with `eepy-blush` /
  `eepy-pink` / `eepy-sage` / `eepy-amber` accents, chunky 2px borders, hard
  shadows, dithered sky + scanline textures). Fonts via next/font: Pixelify
  Sans (`font-pixel`), VT323 (`font-console`), Nunito (`font-body`). Lucide
  React icons; a hand-drawn pixel moon mascot (`src/components/PixelMoon`).
- **Backend:** FastAPI, PostgreSQL via SQLAlchemy (sync), Alembic migrations
  (also an idempotent `backend/run_migrations.py`), JWT auth (PyJWT),
  slowapi rate limiting on auth routes, `mcp` SDK + `docker` SDK for the
  modular sidecar bridge.
- **Deploy:** Docker Compose in `deploy/` (db + backend + frontend), GHCR
  images via CI.

## Repository Layout

```
├── backend/
│   ├── main.py               # FastAPI app, router mounting, template seeding,
│   │                         #   superuser routes, superuser bootstrap
│   ├── auth.py               # JWT encode/decode (PyJWT; migrated from
│   │                         #   python-jose — jose is unmaintained, CVE-2024-29370)
│   ├── database.py           # engine/session (DATABASE_URL from env)
│   ├── run_migrations.py     # idempotent schema bootstrap
 │   ├── api/
 │   │   ├── mcp_endpoints.py  # ALL MCP routes: tool keys, template list,
 │   │   │                     #   config register/list/delete/test/mcp-url,
 │   │   │                     #   unified proxy (routes by runtime), unified
 │   │   │                     #   OpenAPI spec (from DB + registry),
 │   │   │                     #   MCP_STREAM_PATH + the eekey scope check
 │   │   ├── mcp_stream.py     # native MCP endpoint (AI Platform connector):
 │   │   │                     #   streamable-HTTP at /api/mcp/mcp (stateless),
 │   │   │                     #   ASGI auth middleware, per-user tools/list,
 │   │   │                     #   tools/call → bridge/registry routing
 │   │   └── mcp_bridge.py     # modular sidecar bridge: spawn/reuse per-user
 │   │                         #   MCP sidecars (subprocess or docker), speak
 │   │                         #   MCP (tools/list, tools/call), idle reaper
│   ├── models/
│   │   └── mcp_models.py     # MCPTemplate, UserMCPConfig, MCPUserToolKey,
│   │                         #   MCPSidecar (durable sidecar tracking),
│   │                         #   MCPTemplateRequest
│   ├── utils/
│   │   ├── crypto.py         # Fernet encrypt/decrypt (+ SECRET_KEY fallback)
│   │   └── logging_setup.py  # shared logger config (used across backend)
│   ├── alembic/              # migration structure + MCP migration
│   └── requirements.txt
├── frontend/
│   ├── app/                  # App Router pages: /auth, /dashboard/*
│   ├── context/AuthContext.tsx
│   ├── lib/api.ts
 │   └── src/components/       # MCPConnectionWizard, OpenWebUIExportPanel,
 │                             #   AIPlatformConnectorPanel
├── deploy/
│   ├── docker-compose.yml    # db + backend + frontend (no secrets in file)
│   └── stack.env.example     # secret reference — copy to stack.env and fill in
│                             #   (named stack.env, not .env, because the stack
│                             #   is normally deployed via Portainer)
├── tools/
│   ├── eepy_mcp_shim.py    # stdio MCP bridge for local agents (opencode):
│   │                       #   spec-driven tools over the unified proxy —
│   │                       #   see "opencode MCP bridge" under Testing
│   └── .eepy_env           # git-ignored: EEPY_BASE_URL / EEPY_TOOL_KEY
├── opencode.json           # opencode dev config: eepy-local shim (disabled
│                           #   by default). The production eepy connection
│                           #   (native endpoint + key) lives in the USER-
│                           #   level opencode config — never committed
├── integrations/
│   ├── Dockerfile.happyfox   # builds the submodule into the sidecar image
│   ├── Dockerfile.ebay       #   (build context = repo root; see .github/workflows/main.yml)
│   ├── Dockerfile.portainer  #   (mirrors the upstream Dockerfile; repo-root context)
│   ├── Dockerfile.warden     #   (mirrors the upstream Dockerfile; npm ci runs
│   │                         #    the postinstall Vaultwarden patch — no
│   │                         #    --ignore-scripts)
│   ├── Dockerfile.proxmox    #   (pip-installs the submodule; upstream pyproject
│   │                         #    already pins mcp<2, no extra pin needed)
│   ├── happyfox-mcp/         # GIT SUBMODULE → Glitch3dPenguin/happyfox-mcp
│   ├── ebay-mcp/             # GIT SUBMODULE → YosefHayim/ebay-mcp
│   ├── portainer-mcp/        # GIT SUBMODULE → portainer/portainer-mcp
│   ├── warden-mcp/           # GIT SUBMODULE → icoretech/warden-mcp
│   └── proxmox-mcp/          # GIT SUBMODULE → RekklesNA/ProxmoxMCP-Plus
└── assets/
```

## MCP API Surface (implemented)

All under `/api/mcp` (router prefix in `api/mcp_endpoints.py`):

| Method & Path | Purpose | Auth |
|---------------|---------|------|
| `POST /api/mcp/api-keys` | Create (ADD) a Tool API Key (`eekey_...`) — never replaces existing keys; a user may hold several active keys | USER |
| `GET /api/mcp/api-keys` | List keys (prefix only, never plaintext; `can_reveal` says whether re-view is possible) | USER |
| `DELETE /api/mcp/api-keys/{key_id}` | Revoke a key (soft — the entry stays listed). `?hard=true` physically deletes the row (the UI "remove entry" action for revoked keys) | USER (owner) |
| `POST /api/mcp/api-keys/{key_id}/reveal` | Re-view a key's plaintext after re-entering the account password (body `{"password": ...}`) — decrypts the Fernet copy stored at creation; 401 wrong password, 410 legacy key without a stored copy | USER |
| `GET /api/mcp/templates/list` | Approved+enabled templates with config schemas | USER |
| `POST /api/mcp/config/register` | Save credentials for a template (encrypted on write) | USER |
| `GET /api/mcp/config/list` | User's active configs (no plaintext creds) | USER |
| `DELETE /api/mcp/config/{template_id}` | Remove a config + stored creds | USER (owner) |
| `GET /api/mcp/config/{template_id}/mcp-url` | Per-template MCP URL | USER |
| `POST /api/mcp/config/{template_id}/test` | Test stored credentials live | USER / Tool Key |
| `GET/POST/PUT /api/mcp/proxy/{template_id}/{tool_name}` | The core proxy: decrypt in memory → call upstream → stream back. ALSO bound at `/api/mcp/{template_id}/{tool_name}` (no `proxy` segment) via `mcp_proxy_alias` so pre-fix Open WebUI spec imports (which call the base-URL + path shape) keep working | USER / Tool Key |
| `POST /api/mcp/mcp` | The native MCP endpoint (AI Platform connector): streamable-HTTP JSON-RPC (`initialize`, `tools/list`, `tools/call`) served by `api/mcp_stream.py` — per-user tool list, proxy-equivalent calls, `eepy__status` built-in. NOT a FastAPI route (ASGI middleware + SDK session manager); see "Native MCP endpoint" below | USER / Tool Key |
| `POST /superuser/mcp/templates/{template_id}/discover` | Run `tools/list` against the template's sidecar (superuser's own creds) and store the tool schemas | SUPERUSER |
| `PATCH /superuser/mcp/templates/{template_id}/runtime` | Register/update a template's sidecar spec (`runtime`, `runtime_config`, approval flags) | SUPERUSER |
| `GET /api/mcp/openapi.json` | Unified OpenAPI spec of ALL connected tools (Open WebUI import). Paths are `/proxy/{template_id}/{tool_name}` and `servers[0].url` is the base URL `.../api/mcp` — because Open WebUI appends spec paths to the PASTED base URL and ignores `servers[].url`, both compositions must yield the same route. Also served at `/api/mcp/openapi.json/openapi.json` because Open WebUI auto-appends `/openapi.json` to the pasted URL (users paste the base URL `.../api/mcp`) | public |

**Tool API Keys** are stored as a SHA-256 hash plus a Fernet-encrypted
plaintext copy (`mcp_user_tool_keys` — the copy exists so the owner can
re-view the key later in the UI via the password-gated reveal route; legacy
rows pre-dating it have `key_encrypted = NULL` and report `can_reveal:
false`). The hash is what authenticates, and keys are accepted ONLY
on the proxy, the native MCP stream endpoint (`/api/mcp/mcp`), and the
config-test routes. On any other route an `eekey_` bearer is rejected —
session JWTs and tool keys have strictly different scopes. The scope list
lives in ONE place: the `key_allowed` check in `_resolve_scoped_user`
(`api/mcp_endpoints.py`), with `MCP_STREAM_PATH` defined there as the single
source of truth.

## Adding a New Integration (runbook)

Two runtimes exist. **Prefer `mcp-server`** — it is the scalable path and is
what lets a third party's repo (e.g. another person's HappyFox MCP server)
ship its own tools without us maintaining that integration's code.

### A. Modular: `runtime=mcp-server` (recommended, no per-integration code)

The integration's MCP server is published as a container image (or a local
`command`). We only register its **spec** and its **credential fields** — we
do not read, vendor, or maintain its tool code. Tool schemas are captured at
admin-discovery time from the upstream server's own `tools/list`.

1. **Register the template** — add an `MCPTemplate` row (seed in `main.py`
   like HappyFox, or via the superuser runtime endpoint) with:
   - `runtime = "mcp-server"`
   - `config_schema` (JSON): the credential fields to collect from the user.
    - `runtime_config` (JSON), e.g.:
      ```json
      {
        "image": "ghcr.io/kulik-labs-development/eepy-host-happyfox:latest",
        "command": ["python", "server.py"],
        "cwd": "integrations/happyfox-mcp",
        "env": {"MCP_TRANSPORT": "streamable-http", "PORT": "8000"},
        "subprocess_env": {"MCP_TRANSPORT": "stdio"},
        "endpoint": "/",
        "port": "8000",
        "env_mapping": {"USER_FIELD_A": "UPSTREAM_ENV_A", "USER_FIELD_B": "UPSTREAM_ENV_B"},
        "subprocess_env_mapping": {"USER_FIELD_A": "UPSTREAM_STDIO_ENV_A"},
        "generated_secrets": ["UPSTREAM_GATE_TOKEN"],
        "headers": {
          "Authorization": "Bearer {{UPSTREAM_GATE_TOKEN}}",
          "X-User-Key": "{{UPSTREAM_ENV_A}}"
        },
        "test_tool": {"name": "some_read_only_tool", "arguments": {}},
        "tool_names": ["tool_a", "tool_b"]
      }
      ```
      - `env_mapping` maps each **user credential field** (from
        `config_schema`) to the **upstream env var** the sidecar reads.
        Unmapped fields are never passed to the sidecar.
        `subprocess_env_mapping` (like `subprocess_env` for static env)
        REPLACES `env_mapping` for the subprocess backend when present — for
        upstreams that read the same credential from a different env var per
        transport (Portainer: stdio reads `PORTAINER_API_KEY`, HTTP mode
        refuses to boot with it set — the key rides a per-request header
        instead).
      - `generated_secrets`: env var names the bridge mints a FRESH random
        value for on every sidecar spawn (e.g. a per-sidecar gate token).
        Never stored in runtime_config or the DB.
      - `headers`: per-request HTTP headers for an HTTP (docker/url)
        sidecar; `{{ENV_VAR}}` placeholders resolve from the sidecar's final
        env (static + mapped credentials + generated secrets), so credentials
        can ride in headers without being stored anywhere (the Portainer
        contract: gate bearer + the user's own `X-Portainer-API-Key` on every
        request, plus a fixed `Host` its allowlist accepts). The subprocess
        backend ignores `headers` (stdio has no HTTP).
     - `image` → docker backend (production: the image is built from the
       integration's git submodule by CI on every push — needs the Docker
       socket). `command` (+ optional relative `cwd`, resolved against the
       repo root) → subprocess backend (local dev; the sidecar's deps are
       picked up from the backend's own interpreter, which the bridge puts
       first on PATH — Python submodules only; a Node/TypeScript submodule
       like ebay-mcp needs a one-time `pnpm install --ignore-scripts &&
       pnpm run build` in its dir first, and `node` on the host PATH).
       Set `EEPY_MCP_INSTANCE_BACKEND` to pick; compose defaults to
       `docker`.
     - `test_tool` is a read-only tool used by `/config/{id}/test`.
     - `tool_names` is a best-effort list so the OpenAPI spec has entries
       before discovery (discovery overwrites `discovered_tools` with the real
       schemas and takes precedence).
   - `approved_by_admin=True`, `enabled_global=True`.
2. **Discover the tools (once, as superuser)** — the superuser must first
   connect the template with their own credentials (dashboard → Connect), then
   call `POST /superuser/mcp/templates/{template_id}/discover`. This spawns an
   ephemeral sidecar, runs `tools/list`, stores the result on the row, and
   tears the sidecar down. The unified OpenAPI spec and dashboard now show the
   upstream author's real tool schemas. **Re-run discovery after the upstream
   image changes** so the spec stays current.
 3. **Done.** It appears in the library; the connect wizard renders from
    `config_schema`; proxy + test route through the generic bridge; its tools
    appear in every user's Open WebUI connection AND in their native MCP
    client (opencode / Claude Desktop / Cursor via `/api/mcp/mcp`)
    automatically.

**Maintenance when the upstream repo changes:** the upstream repo is a git
submodule under `integrations/` — update its ref
(`cd integrations/happyfox-mcp && git fetch && git checkout <new-commit>`
then `git add integrations/happyfox-mcp`), push, and CI rebuilds the sidecar
image from that exact commit. Re-run discovery. No Eepy backend code changes
— that is the whole point of the modular path.

### B. Legacy/reference: `runtime=native` (hardcoded, only for HappyFox today)

1. Register the template with `runtime="native"` + `config_schema`.
2. Add an entry to `TEMPLATE_REGISTRY` in `backend/api/mcp_endpoints.py`
   (tool name → upstream HTTP method + path) plus upstream base-URL/auth logic
   in the native proxy handler.
3. Approve it (`approved_by_admin=True`, `enabled_global=True`).

> This path requires writing and maintaining per-integration Python. Use it
> only for the original HappyFox reference; everything new should be
> `mcp-server`.

## Native MCP endpoint (AI Platform connector, `backend/api/mcp_stream.py`)

`POST /api/mcp/mcp` speaks real Model Context Protocol (streamable-HTTP,
JSON-RPC) so MCP-native clients connect without any OpenAPI import. This is
the "AI Platform connector" in the dashboard — the pair to the Open WebUI
tool-server connector, with the identical one-key contract.

- **Transport:** mcp SDK `StreamableHTTPSessionManager` with `stateless=True`
  + `json_response=True`. Every request is a self-contained exchange — no
  server-side session store (any backend replica on the host can serve any
  request, like the proxy) and plain JSON responses (no SSE) so Portainer /
  reverse-proxy SSE buffering can't wedge a call. The SDK's cookie-oriented
  DNS-rebinding Host/Origin checks are DISABLED
  (`TransportSecuritySettings(enable_dns_rebinding_protection=False)`)
  because auth is Bearer-token only and clients dial through container
  IPs/proxies.
- **Wiring (`main.py`):** `session_manager.run()` is entered in the app
  lifespan (its task group must be live for the whole process); an ASGI
  middleware (`MCPStreamAuthMiddleware`) is added BEFORE the CORS middleware
  (Starlette: last-added is outermost, so CORS stays outermost and MCP
  responses carry normal CORS headers). The middleware intercepts
  `/api/mcp/mcp` (POST/GET/DELETE) before routing.
- **Auth:** the middleware resolves the caller with the SAME
  `_resolve_scoped_user` the proxy uses (session JWT OR `eekey_` Tool API
  Key — eekey scope includes `MCP_STREAM_PATH`), answers 401 JSON otherwise,
  and hands the `User` to the handlers through a **ContextVar**
  (`_current_mcp_user`) — the SDK's low-level `Server` handlers have no
  access to the HTTP request. The eekey path COMMITs (last_used_at bump)
  which expires the SQLAlchemy instance, so the middleware `db.refresh()` +
  `db.expunge()`s the user before closing the session (detached lazy access
  would raise "not bound to a Session").
- **tools/list is PER-USER:** only templates the caller has an ACTIVE
  `UserMCPConfig` for are listed — a tool you cannot call is not offered.
  Schemas come from `discovered_tools` (admin discovery); undiscovered
  mcp-server templates fall back to `runtime_config.tool_names`, then
  `TEMPLATE_REGISTRY` (native), else an untyped `{"type":"object"}` —
  arguments are forwarded verbatim upstream. Tool names are
  `{template}__{tool}` (sanitized to `[a-zA-Z0-9_-]`, max 64).
- **tools/call routes exactly like the REST proxy:** name is split on the
  first `__`; the template must be approved+enabled and the caller must have
  an active connection (same `_load_active_creds` as the proxy);
  `mcp-server` → `mcp_bridge.bridge_call`, `native` → `_proxy_native`
  (wrapped with a standalone session). Unknown template / unknown tool /
  missing connection / bridge failure / upstream HTTP error all come back as
  `isError=True` MCP results with a human-readable message — never transport
  errors — so the agent can read and react. A built-in `eepy__status` tool
  (no upstream call) reports the caller's connected integrations + tool
  counts.
- **Tests:** `backend/tests/test_mcp_stream.py` speaks raw JSON-RPC over the
  test client (auth 401s, JWT + eekey accept, stateless list-without-init,
  per-user listing, bridge-routed call with decrypted creds, error
  surfacing, `eepy__status`). The test client is a CONTEXT MANAGER in
  `conftest.py` (runs the lifespan → session manager task group + reaper).

## How the MCP sidecar bridge works (`backend/api/mcp_bridge.py`)

- **Per-user, per-credential identity:** a sidecar is keyed by
  `(user_id, template_id, hash-of-exact-credentials)`. A user who changes
  their credentials gets a fresh sidecar; the old one is torn down.
- **Credential injection:** the user's Fernet-decrypted credentials are mapped
  (via `env_mapping`) into the sidecar's process environment at spawn time.
  They live **only** in the sidecar's env and the live MCP stdio/HTTP stream —
  never on disk, never in logs, never returned to the client. The sidecar env
  is minimal (a fixed allowlist of non-sensitive vars + template static env +
  mapped credentials) so the backend's own `SECRET_KEY`/`DATABASE_URL`/
  `MCP_ENCRYPTION_KEY` never leak into third-party processes (covered by a
  test).
- **Lifecycle:** sidecars are spawned lazily on first use, reused while
  active, and reaped by a background task after
  `EEPY_MCP_INSTANCE_IDLE_TIMEOUT` (default 300s). MCP sessions are
  short-lived (one `initialize` + call per proxy request) so a stuck session
  cannot wedge a long-lived sidecar.
  - **Node-local, single-host by design:** a sidecar is a local
  process/container on whichever backend replica receives the request. All
  durable state (templates, encrypted credentials, tool keys, discovered
  tools) lives in the shared PostgreSQL, so any replica on the same host can
  serve any user — it just (re)spawns a sidecar on demand. Multi-replica on
  ONE host is safe (the boot sweep is node-scoped, below); multi-HOST is NOT:
  a sidecar is dialed over THIS host's docker daemon (same-network
  container IP, or the host-gateway/loopback fallback), so a sidecar spawned
  on another host would be unreachable. Scale out by moving the whole stack,
  not by adding remote backend nodes.
 - **Instance backends:** `subprocess` (local dev; spawns `command`, with an
  optional relative `cwd` resolved against the repo root so the integration
  can be run straight from its `integrations/` submodule; the backend's
  interpreter is put first on PATH so the sidecar's deps resolve) or `docker`
  (production: runs `image` — built from the integration's git submodule by
  CI — pulls on demand, needs the Docker socket, which
  `deploy/docker-compose.yml` mounts on the backend service only).
  **Sidecar dialing:** when `EEPY_MCP_SIDECAR_NETWORK` is set (compose
  defaults it to `eepy-sidecars`, a dedicated bridge network the backend
  also joins), the sidecar is attached to that network and dialed DIRECTLY
  by container IP — no host port is published at all, so the sidecar (which
  holds the user's decrypted creds) is unreachable from the host/LAN AND
  from the db/frontend network. The short network name is resolved to the
  daemon's project-prefixed name (`deploy_eepy-sidecars`, `<stack>_...`) by
  matching the backend's own attached networks. Without the variable the
  bridge falls back to publishing on 127.0.0.1 and dialing via
  `EEPY_MCP_DOCKER_HOST` (default `127.0.0.1`; compose sets
   `host.docker.internal` + `extra_hosts: host-gateway`) — that legacy path
   is NOT reliable from a containerized backend on Linux (a port published
   on 127.0.0.1 is not reachable via the host-gateway IP) and is kept only
   for on-host dev. After the container reports "running" the bridge polls
   the sidecar port until the APP is serving (`EEPY_MCP_SIDECAR_READY_TIMEOUT`,
   default 30s) so the first MCP handshake never races the app binding:
   the network dial (production) polls a TCP connect to the container IP
   (accurate — no forwarding layer), while the legacy port-publish dial
   probes at HTTP level, because a forwarding layer (Docker Desktop's
   Mac/Windows VM) accepts the TCP connection BEFORE the app inside the
   container has bound its socket, and a bare TCP connect would declare
   readiness too early (first handshake died with a ReadError; any HTTP
   response — 200/404/405/421 — proves the app's HTTP stack is up).
   NOTE for bare-host dev on Docker Desktop for Mac/Windows: the host
   cannot route to container IPs on user-defined networks (VM isolation),
   so a non-containerized backend there can only use the legacy dial; the
   network dial requires the backend itself to be containerized on the
   network (the production/compose topology).
   The bridge speaks MCP over stdio (subprocess) or streamable-HTTP
   (docker/url).
 - **Sidecar failure diagnostics:** spawn/handshake failures are logged to
  the `eepy-backend` logger (Debug Log console + docker logs) WITH the
  sidecar's own log output (docker: redacted `container.logs()` tail
  captured BEFORE the container is removed; subprocess: stderr tail). The
  redaction strips the user's credential values out of sidecar output.
  SDK teardown explosions (anyio `BaseExceptionGroup` / cross-task
  cancel-scope `RuntimeError` from `mcp` streamable-http when the sidecar
  is unreachable) are flattened into a one-line summary and converted to a
  `BridgeError` → clean 502 with detail, never a 500.
 - **Node identity + boot sweep (Portainer-safety):** sidecars are tracked
  in `mcp_sidecars` with `node_id` = a STABLE deployment identity:
  `EEPY_NODE_ID` if set, else this process's own docker container name
  (discovered via the mounted socket; stable across restarts/redeploys of
  the same service, distinct per replica), else a random uuid (bare host).
  Stability matters: with a per-boot uuid the sweep would treat the
  previous boot's still-running sidecars as foreign and leave them (and
  their decrypted creds) alive forever after a redeploy. Every sidecar
  container is also labelled `eepy-host.sidecar=true` (plus template + key
  prefix) so it is identifiable in Portainer's container list and by
  filter. On boot the lifespan runs `sweep_orphan_sidecars()`:
  - rows recorded by THIS node (`node_id == NODE_ID`, or NULL pre-node
    tracking) are definitive leftovers holding a user's decrypted creds in
    their env with no session handle: force-remove the container, delete the
    row (the next request re-spawns).
  - rows recorded by ANOTHER node are only reconciled when their container
    is NOT running on the shared daemon (exited/dead/gone → clean up +
    delete the stale row). A foreign RUNNING sidecar is never touched — it
    may still be serving live users.
  This self-heals after OOM kills, `docker kill -9`, host reboots, daemon
  restarts, and Portainer removes that skip the graceful shutdown hook.
  Tracking is fail-soft: a DB hiccup must never break a tool call.
   - **Per-backend env:** the two backends need different upstream transports
   for the same server, so runtime_config may set `subprocess_env` (replaces
   `env` for the subprocess backend; `env` stays the docker-backend value).
   The HappyFox seed uses `env: {MCP_TRANSPORT: streamable-http, PORT: 8000}`
   + `subprocess_env: {MCP_TRANSPORT: stdio}` — without the override the
   subprocess sidecar would bind 0.0.0.0:8000 in HTTP mode and the stdio
   handshake would fail (regression-tested; the fake test server refuses
   stdio when an HTTP transport is selected, and an e2e test drives the real
   pinned happyfox-mcp submodule through the subprocess path).
   - **Docker sidecar env = image ENV + bridge additions ONLY:** for a docker
   spawn the container's baseline env is the IMAGE's own ENV — the bridge
   overlays only its additions (static template env, mapped credentials,
   generated secrets) and deliberately drops the host allowlist vars
   (`_docker_container_env`), notably **PATH**: a host PATH would override
   the image's ENV PATH and break entrypoints living in image-local
   locations (the Portainer image's uv-venv `mcp-portainer` at
   `/app/.venv/bin` died with "executable file not found in $PATH" until
   this was fixed; happyfox/ebay only survived because `python`/`node` sit
   on standard paths that happen to overlap the host PATH). The subprocess
   backend is unchanged — the host allowlist IS its whole environment.
   - **Per-request headers + generated secrets (Portainer contract):**
   `runtime_config.headers` are sent on EVERY MCP request to an HTTP
   sidecar, with `{{ENV_VAR}}` placeholders resolved from the sidecar's
   final env; `runtime_config.generated_secrets` are fresh per-spawn random
   values for vars that must never be stored. The mechanism is needed
   because some upstreams (Portainer) authenticate PER REQUEST with a
   bearer + per-user header, refuse to boot with the user key in env, and
   421-reject Hosts outside their allowlist. The bridge sends the headers
   via a pre-configured `httpx.AsyncClient` (the mcp SDK's `headers` kwarg
   is deprecated/ignored), and an explicit `Host` header overrides the dial
   URL's — that is how the fixed `Host: eepy-sidecar:17717` gets past the
   upstream's `PORTAINER_MCP_ALLOWED_HOSTS=eepy-sidecar:*` without knowing
   the container IP. The subprocess backend ignores `headers` (covered by
   e2e tests, incl. a live HTTP MCP server behind a Portainer-style
   host-guard).
   - **Config deletion tears down sidecars:** `DELETE /api/mcp/config/{id}`
  also kills the user's live sidecars for that template immediately (they
  hold the user's decrypted creds in their env) instead of waiting for the
  idle reaper.

**Security note (sidecars run third-party code):** the `approved_by_admin` /
`enabled_global` gate is the moderation layer. Containment in place today:
docker sidecars run with CPU/memory limits (`EEPY_MCP_SIDECAR_MEM_LIMIT`
default 512m, `EEPY_MCP_SIDECAR_CPU_LIMIT` default 1.0) and may drop to a
non-root uid via the optional runtime_config `user` field (e.g.
`"1000:1000"` — the image must contain that uid; enable per-template once
verified, since a wrong uid kills the container). Known trade-offs to close
before opening the library to unvetted community repos: (1) images deploy as
`:latest` (the push-to-main pipeline re-tags on every build) — for a
production lock-in, register the template with a digest-pinned reference
(`ghcr.io/.../eepy-host-happyfox@sha256:...`), which the bridge passes
through unchanged; (2) sidecars need outbound egress to reach their upstream
API and hold the user's decrypted creds in their env, so egress is
unrestricted by design — put community-repo sidecars behind an egress
allowlist/proxy (dedicated docker network + forward proxy) before trusting
unknown code.

## Setup Commands

### Prerequisites
```bash
python 3.12+ (backend) | Node.js 18+ (frontend) | PostgreSQL 15+ (or Docker)
```

### Backend development
```bash
cd backend
pip install -r requirements.txt
# DATABASE_URL, SECRET_KEY (and optionally MCP_ENCRYPTION_KEY) from env:
source ../deploy/stack.env   # after filling it in
# Optional sidecar-bridge tuning (defaults shown):
#   EEPY_MCP_INSTANCE_BACKEND=subprocess   # or docker (needs Docker socket)
#   EEPY_MCP_INSTANCE_IDLE_TIMEOUT=300
python run_migrations.py
uvicorn main:app --reload --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
```

### Frontend development
```bash
cd frontend
npm install                      # npm (package-lock.json) — not pnpm
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
npm run build && npm start
```

### Docker deployment (compose file lives in `deploy/`)
```bash
cd deploy
cp stack.env.example stack.env   # then fill in real secrets (stack.env is git-ignored)
chmod 600 stack.env
docker compose --env-file stack.env up -d
docker compose ps
docker logs eepy-backend -f
```

**Portainer is the primary deployment path:** import `deploy/docker-compose.yml`
as a stack and paste the filled-in `stack.env` contents into the stack's
Environment section. The file is named `stack.env` (not `.env`) on purpose —
keeps stack secrets distinct from any host-level dotfiles.

### Testing
```bash
cd backend && pytest tests/ --cov=. -v || echo "Tests failed"
cd frontend && npm run lint && npx tsc --noEmit
```

(CI mirrors this: ruff+pytest for the backend, eslint+tsc for the frontend —
there is no vitest in the frontend.)

### opencode MCP connection (production) + local shim

The production path is the NATIVE endpoint (`POST /api/mcp/mcp`, see "Native
MCP endpoint"): point the MCP client at the URL + a Bearer Tool API Key.
Deployed: `https://api.eepy.host/api/mcp/mcp` (frontend is `dev.eepy.host`;
`getApiUrl()` in `frontend/lib/api.ts` maps any `*.eepy.host` to the API
host). In opencode the connection lives in the USER-LEVEL config
(`~/.config/opencode/opencode.jsonc`, `mcp.eepy`: `type: "remote"`,
`oauth: false` — required so the 401 path never starts a browser OAuth flow —
plus the key in `headers.Authorization`). The key lives there on purpose:
that file is never committed, and the project config has HIGHER precedence
than the global one, so a committed `mcp.eepy` entry would shadow it.

`tools/eepy_mcp_shim.py` remains a small stdio MCP server for LOCAL dev
against a local backend (registered in the root `opencode.json` as
`eepy-local`, `enabled: false` — opt-in: it fetches the unified
`/api/mcp/openapi.json` spec, registers each tool as `{template}__{tool}`, and
proxies each `tools/call` to `POST /api/mcp/proxy/{template}/{tool}`):
- Config: env vars, or `tools/.eepy_env` (git-ignored, chmod 600, `KEY=VALUE`
  lines): `EEPY_BASE_URL` (e.g. `http://localhost:8000`), `EEPY_TOOL_KEY`
  (`eekey_...` created in the dashboard — one key unlocks every integration
  you have connected).
- `EEPY_TEMPLATES` (comma list) restricts which integrations are exposed.
  Set it when testing one integration (e.g. `EEPY_TEMPLATES=happyfox`) — a
  large catalog blows the agent's context window (opencode loads every MCP
  tool it lists).
- One-time venv (recreate if missing):
  `uv venv --python 3.12 tools/.venv && uv pip install --python
  tools/.venv/bin/python "mcp==1.29.0" "httpx==0.28.1"` (same pins as the
  backend). Debug: `tools/.venv/bin/python tools/eepy_mcp_shim.py --list`.
- Config is loaded at opencode startup: quit + restart opencode after changing
  any opencode config or `tools/.eepy_env`.

## Critical Developer Nuances (learn the hard way)

1. **Absolute import rule — CRITICAL.** Never use relative imports in
   `backend/main.py` (Uvicorn runs it as a top-level script →
   `ImportError: attempted relative import with no known parent package`).
   Always `from api.mcp_endpoints import ...`, etc.
2. **JSX syntax fragility.** When rewriting `.tsx` files with automated
   tools, escaping artifacts break the build immediately. Use quoted HEREDOCs
   for file writes and re-verify the file after every automated edit.
3. **Credential security — SECURITY CRITICAL.** All MCP credentials are
   Fernet-encrypted at rest. Decryption happens only in memory during handler
   execution. No logs, no disk, no error messages that echo decrypted values.
   Sidecars (mcp-server runtime) receive decrypted credentials ONLY via their
   process environment at spawn time; the sidecar env is a minimal allowlist
   (see `api/mcp_bridge.py:_MINIMAL_PROC_ENV`) so backend secrets never leak
   into third-party processes.
4. **Role enforcement is server-side.** Client-side role checks are UX only;
   every privileged endpoint validates the JWT role in a FastAPI dependency.
5. **Event-loop rule — keep it or the app serializes under load.** A FastAPI
   `async def` runs ON the event loop; any synchronous work in it (SQLAlchemy,
   Fernet, subprocess/docker API, `proc.wait`) blocks EVERY other in-flight
   request. So:
   - Endpoints/deps that only do sync work must be plain `def` — FastAPI runs
     them in the threadpool. (Guarded by `tests/test_event_loop.py`; do not
     "modernize" a sync `def` route back to `async def`.)
   - Endpoints that genuinely await non-blocking I/O (the MCP bridge, httpx
     upstream calls, `request.json()` streaming) stay `async def`; their sync
     DB work goes in a sync dependency (`get_proxy_context`) or is offloaded
     with `asyncio.to_thread`.
   - In `api/mcp_bridge.py`, blocking work (spawns, image pulls, kills,
     liveness) is ALWAYS wrapped in `asyncio.to_thread` from the async entry
     points. `_spawn_docker`/`_spawn_subprocess` are sync on purpose.
    - Sidecar spawn locks are PER-KEY (`_KEY_LOCKS`), never global: one user's
      first-call docker pull must not serialize every other user's request.
 6. **Never let a test install uvloop.** `uvicorn.Config(...)` with the
    default `loop="auto"` runs `uvloop.install()` — which replaces the
    PROCESS-WIDE asyncio event-loop policy and never restores it. uvloop's
    policy has no child watcher, so any LATER subprocess spawn on a
    plain-asyncio loop (the test suite's persistent TestClient portal, which
    predates the install) dies with a bare `NotImplementedError` deep in
    `anyio.open_process` (surfaced as "MCP handshake with sidecar failed
    (NotImplementedError)"). Pass `loop="asyncio"` to every test uvicorn
    Config (see `test_http_sidecar_headers_reach_the_upstream_server`).

## Code Style Guidelines

### Backend (Python/FastAPI)
1. Absolute imports in `main.py` (see Critical Nuances #1).
2. Pydantic models inherit `BaseModel` with type hints and validation.
3. Wrap DB operations in try/except and return standardized
   `HTTPException` responses.
4. Never log or persist decrypted credentials (see #3 above).

### Frontend (TypeScript/Next.js App Router)
1. PascalCase component naming.
2. Tailwind utilities; no arbitrary CSS values unless necessary.
3. Lucide React icons only.
4. **Follow the "Retro Cozy" design system** (see `tailwind.config.js`):
   - Surfaces: `night` (base/deep/surface/raise/border/line) — never reintroduce
     the old `void`/neon palette.
   - Accents: `eepy-blush` (primary), `eepy-pink` (highlight), `eepy-sage`
     (success/on), `eepy-amber` (secondary/warn), `eepy-lilac` (tertiary),
     `eepy-ember` (error/danger). Text: `ink` / `ink-soft` / `ink-faint` /
     `ink-dim` (no raw `text-gray-*`).
   - Reuse the component classes in `app/globals.css` instead of re-deriving:
     `.panel` (raised card), `.well` (recessed), `.card` (mid), `.btn` +
     `.btn-blush|sage|amber|ghost|danger`, `.btn-icon`, `.input-pixel`,
     `.label-pixel`, `.chip` (+ `-blush|-sage|-amber|-lilac|-ember`), `.led`
     (squared status light — not a glowing dot).
   - Fonts: `font-pixel` (headings/buttons/nav), `font-console` (logs/code/
     URLs, keep ≥13px), `font-body` (prose).
   - Pixel touches: `.pixel-caps` corner rivets (color via
     `[--cap:theme('colors.eepy.…')]`), `.tex-dither` / `.tex-bands` textures,
     `.text-px` hard text shadow, `steps()` animations (no smooth ease on
     hovers/presses), hard `shadow-pixel*` (no blurred glows).

## Operational Notes

- **Working repo is `~/Eepy-Host` (capital E).** Do not create or clone a
  second copy (a stray lowercase `~/eepy-host` clone was found and deleted
  2026-08-20; one of its never-pushed commits was saved as a patch in
  `~/attachments/` before deletion). If a fresh clone is ever needed, use
  `git clone --recurse-submodules` so `integrations/happyfox-mcp` is present
  (a plain clone leaves the submodule dir empty until
  `git submodule update --init`).
- **Two CI workflows, both on push to main:** `CI` (ruff+pytest, eslint+tsc —
  no image builds) and `Build and Push to GHCR`, which builds **seven**
  images: `eepy-host-backend`, `eepy-host-frontend`, `eepy-host-happyfox`
  (sidecar, built from the submodule via `integrations/Dockerfile.happyfox`),
  `eepy-host-ebay` (sidecar, via `integrations/Dockerfile.ebay`),
  `eepy-host-portainer` (sidecar, via `integrations/Dockerfile.portainer`),
  `eepy-host-warden` (sidecar, via `integrations/Dockerfile.warden`) and
  `eepy-host-proxmox` (sidecar, via `integrations/Dockerfile.proxmox`)
  — all sidecars built with the repo root as build context. So every push to
  main refreshes all deployed images.
- **Seed roll-forward:** `seed_mcp_templates()` in `main.py` updates the
  existing seeded rows' (HappyFox, eBay, Portainer, Warden, Proxmox) `runtime`,
  `runtime_config`, `config_schema`, `image_tag`, and approval flags on
  **every boot** (idempotent). That is how spec changes reach the live DB —
  pushing a backend change is enough; no manual DB edit needed.
- **Portainer rollout (primary deploy path):** after a main push, pull the
  updated `eepy-host-backend:latest` / `eepy-host-frontend:latest` /
  `eepy-host-happyfox:latest` / `eepy-host-ebay:latest` /
  `eepy-host-portainer:latest` / `eepy-host-warden:latest` /
  `eepy-host-proxmox:latest` images and recreate the containers (sidecar images are pulled lazily by the bridge, so
  just make sure the backend has fresh access). `stack.env` values rarely
  change — only when a new secret is introduced.
  - **The backend needs the Docker socket or sidecars can never spawn:** with
    `EEPY_MCP_INSTANCE_BACKEND=docker` (the compose default) the backend
    spawns per-user sidecar containers THROUGH the host Docker socket, which
    `deploy/docker-compose.yml` mounts ONLY on the backend service
    (`volumes: - /var/run/docker.sock:/var/run/docker.sock`). A common
    Portainer failure: the stack was created from an OLDER compose (before
    this mount / the `eepy-sidecars` network existed) and a later "redeploy"
    only pulled newer images — the SERVICE CONFIG is still the old one, so
    the socket is missing and every tool call 502s with "Cannot reach the
    Docker daemon." Fix: edit the stack in Portainer, paste the CURRENT
    `deploy/docker-compose.yml`, update & recreate `eepy-backend`. The backend
    probes the daemon AT BOOT and logs to the Debug Log console: `mcp-bridge:
    docker daemon reachable (sidecar backend ready)` (good) or a red
    `Docker daemon NOT reachable` line with the remediation (fix the stack).
    Host check: `docker exec eepy-backend ls -l /var/run/docker.sock`.
  - **Sidecars are spawned ON DEMAND, per (user, template, exact credentials),
    and reaped after `EEPY_MCP_INSTANCE_IDLE_TIMEOUT` (default 300s) idle.**
    So seeing NO extra `eepy-sidecar-*` containers on the host while idle is
    NORMAL — a sidecar exists only from first use until ~5 min after the last
    call. If none EVER appears when a tool is called, spawning is failing
    (check the daemon line above / the Debug Log console).
  - **Verify the docker sidecar path (production):** the dev machine has
     Docker, so the full compose stack CAN be exercised locally (build the
     seven app+sidecar images with the GHCR tags, `docker compose --env-file
    stack.env up -d`). After a deploy: hit the dashboard's connection test,
   then a real proxy tool call, and confirm in the backend logs (or the
   Debug Log console) that `mcp-bridge: started sidecar container ...
   network=... dial=...` appears and the call returns upstream data.
   Sidecars dial through the `eepy-sidecars` network (container IP) — the
   legacy `EEPY_MCP_DOCKER_HOST` loopback/host-gateway path is
   fallback-only and NOT reliable on Linux.
   - **Sidecar images are pulled by the HOST daemon on demand — GHCR
    visibility matters:** the bridge pulls `ghcr.io/.../eepy-host-happyfox`
    etc. through the host Docker socket, with whatever credentials the HOST
    daemon has. GHCR packages default to PRIVATE, so an anonymous host gets
    `error from registry: unauthorized` on the first tool call. Fix either
    by making the org's `eepy-host-*` packages Public (GitHub → org →
    Packages → Change visibility; safe — all images build from public repos
    and carry no secrets) or by `docker login ghcr.io` on the host with a
    token that has `read:packages`. The spawn error carries these steps in
    the 502 detail (see `_spawn_error_bridge`).
  - **Sidecar images must pin the mcp SDK 1.x line:** the submodules'
   `requirements.txt` declares `mcp>=1.0.0` with no upper bound, and the
   2.0.0 release removed `mcp.server.fastmcp` (FastMCP), which crashes the
   HappyFox sidecar at startup (container exits, bridge reports "cannot
   communicate"). `integrations/Dockerfile.happyfox` force-reinstalls
   `mcp[cli]>=1.0,<2` after the submodule's pip install, in OUR Dockerfile so
   the pin survives every CI rebuild without touching upstream submodule
   code. The portainer sidecar is NOT affected: its image installs from
   `uv.lock` (mcp pinned at 1.28.x by upstream). If a future sidecar image
   is built from a submodule whose code imports the 1.x API, keep such a
   pin in its Dockerfile.
- **Dev-sandbox test tooling (ephemeral, rebuild if missing):** venv at
  `/tmp/eevenv` (`python3 -m venv /tmp/eevenv && /tmp/eevenv/bin/pip install
  -r requirements.txt pytest ruff`), and integration script
  `/tmp/eepy_test.sh` + `/tmp/eepy_test.py` (22 end-to-end checks: role
  escalation, JWT, superuser authz, Fernet-at-rest, rate limits, eekey
  scoping). Tests use a throwaway SQLite DB via `conftest.py`.
 - **Secrets** come from `deploy/stack.env` (git-ignored): `POSTGRES_PASSWORD`,
  `DATABASE_URL`, `SECRET_KEY`, `MCP_ENCRYPTION_KEY`, plus the optional
  `EEPY_MCP_INSTANCE_BACKEND` (sidecar runtime: `docker` default in compose,
  or `subprocess`) and `CORS_ORIGINS` (comma-separated origin pin for
  browser-based clients like Open WebUI; unset = wildcard, which is safe —
  Bearer-token auth only, no cookie sessions). `EEPY_MCP_DOCKER_HOST` is set
  by the compose file itself (not in stack.env) to `host.docker.internal` so
  a containerized backend can
   reach loopback-bound sidecar ports (fallback only; the primary dial is
   `EEPY_MCP_SIDECAR_NETWORK`, which the compose file sets itself). Optional
   sidecar containment dials (env-overridable, sensible defaults):
   `EEPY_MCP_SIDECAR_MEM_LIMIT`, `EEPY_MCP_SIDECAR_CPU_LIMIT`, and
   per-template `user` / digest-pinned `image` in `runtime_config` (see the
   security note above).
   `SECRET_KEY` signs JWTs (also the Fernet fallback key) — see Key
   Architecture Decision #3 before ever rotating it.
 - **Initial superuser** comes from the `SUPERUSER_USERNAME` env var (passed
   to the backend by compose; set it in `stack.env`): the account is promoted
   at boot AND on its next login (idempotent) — the login hook covers the case
   where the account is only created after the first boot. A missing
   superuser is why the Debug Log console 403s (it is superuser-only).
 - **Redeploys and data persistence (read before touching Portainer):**
   users, saved credentials, and tool keys live ONLY in the `postgres_data`
   volume (Portainer: `<stackname>_postgres_data`). A redeploy of the SAME
   stack keeps it; deleting + re-adding the stack (or a name change) creates a
   NEW empty volume and all data is gone. The backend prints a
   `Boot data summary: users=N mcp_configs=M tool_keys=K ...` line to the
   Debug Log console on every boot — zeros right after a redeploy mean the
   volume was not carried over (no code fix; dump/restore with
   pg_dump/pg_restore or move the volume). Boot itself is race-safe: the db
   has a `pg_isready` healthcheck the backend waits on, and the one-shot
   init (tables/seed/bootstrap) retries up to 10x while the DB comes up.
- **Schema inspection:** `DESCRIBE mcp_templates; DESCRIBE user_mcp_configs;
  DESCRIBE mcp_sidecars;` in psql. (`mcp_sidecars` is normally empty while a
  node is healthy - rows exist only between a sidecar spawn and its teardown,
  plus any the boot sweep has not reconciled yet.)
- **Monetization telemetry (planned, post-launch):** `last_used_at` + per
  config request counters for usage-based decisions.

## Workflow Preferences

- Direct main-branching (no feature branches yet); rapid prototyping →
  implementation verification cycle.
- Communication style: professional/factual; minimize emoji in documentation
  unless an aesthetic requirement is validated in code review.
