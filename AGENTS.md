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
tools without operational overhead.

**Core architecture principle:** this is NOT a container orchestration
platform for the *control plane*. One unified FastAPI backend owns auth,
credentials (encrypted at rest), and all proxy routing. Integration MCP
server code lives in **separate upstream repos**, pulled into this project as
git submodules under `integrations/` (HappyFox:
`integrations/happyfox-mcp` → github.com/Glitch3dPenguin/happyfox-mcp).
CI builds each submodule's code into its own GHCR sidecar image on every
push, so the deployed gateway always runs exactly the code this repo pins —
updating an integration is "bump the submodule ref", never editing its code
here. The backend spawns those sidecars per user (subprocess locally,
docker container in production), short-lived and idle-reaped.

## Current State (Phase 5 complete: modular MCP sidecar runtime)

- Unified auth portal + dashboard hub (account, debug console, organization
  admin tools for superusers, servers).
- HappyFox Help Desk is Template #1: seeded at startup in `main.py`
  (`seed_mcp_templates()`, idempotent) with `approved_by_admin=True`, and runs
  on the **modular sidecar runtime** (`runtime=mcp-server`) from the
  `integrations/happyfox-mcp` git submodule (its own upstream repo) — CI
  builds that submodule into the `eepy-host-happyfox` GHCR sidecar image —
  the reference implementation for every future integration.
- The unified proxy (`/api/mcp/proxy/{template_id}/{tool_name}`) routes by
  template `runtime`: `mcp-server` → generic bridge (`api/mcp_bridge.py`),
  `native` → hardcoded `TEMPLATE_REGISTRY` (HappyFox reference path, kept for
  rollback).
- Open WebUI integration: per-user **Tool API Keys** (`eekey_...`, one key
  unlocks every integration) + a single unified OpenAPI spec for import.
  The spec is generated from the DB (admin-discovered `tools/list` output for
  mcp-server templates; `TEMPLATE_REGISTRY` for native).

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

- **Frontend:** Next.js (App Router) + TypeScript, Tailwind ("Void & Neon"
  aesthetic: `eepy-lavender` / `eepy-peach` / `eepy-mint` accents), Lucide
  React icons, "console feel" UI convention.
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
│   │   │                     #   OpenAPI spec (from DB + registry)
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
│   └── src/components/       # MCPConnectionWizard, OpenWebUIExportPanel
├── deploy/
│   ├── docker-compose.yml    # db + backend + frontend (no secrets in file)
│   └── stack.env.example     # secret reference — copy to stack.env and fill in
│                             #   (named stack.env, not .env, because the stack
│                             #   is normally deployed via Portainer)
├── integrations/
│   ├── Dockerfile.happyfox   # builds the submodule into the sidecar image
│   │                         #   (build context = repo root; see .github/workflows/main.yml)
│   └── happyfox-mcp/         # GIT SUBMODULE → Glitch3dPenguin/happyfox-mcp
└── assets/
```

## MCP API Surface (implemented)

All under `/api/mcp` (router prefix in `api/mcp_endpoints.py`):

| Method & Path | Purpose | Auth |
|---------------|---------|------|
| `POST /api/mcp/api-keys` | Create a Tool API Key (`eekey_...`, shown once) | USER |
| `GET /api/mcp/api-keys` | List keys (prefix only, never plaintext) | USER |
| `DELETE /api/mcp/api-keys/{key_id}` | Revoke a key | USER |
| `GET /api/mcp/templates/list` | Approved+enabled templates with config schemas | USER |
| `POST /api/mcp/config/register` | Save credentials for a template (encrypted on write) | USER |
| `GET /api/mcp/config/list` | User's active configs (no plaintext creds) | USER |
| `DELETE /api/mcp/config/{template_id}` | Remove a config + stored creds | USER (owner) |
| `GET /api/mcp/config/{template_id}/mcp-url` | Per-template MCP URL | USER |
| `POST /api/mcp/config/{template_id}/test` | Test stored credentials live | USER / Tool Key |
| `GET/POST/PUT /api/mcp/proxy/{template_id}/{tool_name}` | The core proxy: decrypt in memory → call upstream → stream back | USER / Tool Key |
| `POST /superuser/mcp/templates/{template_id}/discover` | Run `tools/list` against the template's sidecar (superuser's own creds) and store the tool schemas | SUPERUSER |
| `PATCH /superuser/mcp/templates/{template_id}/runtime` | Register/update a template's sidecar spec (`runtime`, `runtime_config`, approval flags) | SUPERUSER |
| `GET /api/mcp/openapi.json` | Unified OpenAPI spec of ALL connected tools (Open WebUI import) | public |

**Tool API Keys** are stored hashed (`mcp_user_tool_keys`) and accepted ONLY
on the proxy and config-test routes. On any other route an `eekey_` bearer is
rejected — session JWTs and tool keys have strictly different scopes.

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
       "endpoint": "/",
       "port": "8000",
       "env_mapping": {"USER_FIELD_A": "UPSTREAM_ENV_A", "USER_FIELD_B": "UPSTREAM_ENV_B"},
       "test_tool": {"name": "some_read_only_tool", "arguments": {}},
       "tool_names": ["tool_a", "tool_b"]
     }
     ```
     - `env_mapping` maps each **user credential field** (from
       `config_schema`) to the **upstream env var** the sidecar reads.
       Unmapped fields are never passed to the sidecar.
     - `image` → docker backend (production: the image is built from the
       integration's git submodule by CI on every push — needs the Docker
       socket). `command` (+ optional relative `cwd`, resolved against the
       repo root) → subprocess backend (local dev; the sidecar's deps are
       picked up from the backend's own interpreter, which the bridge puts
       first on PATH). Set `EEPY_MCP_INSTANCE_BACKEND` to pick; compose
       defaults to `docker`.
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
   appear in every user's single Open WebUI connection automatically.

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
  a sidecar's port is dialed through this host's loopback/host-gateway
  (`EEPY_MCP_DOCKER_HOST`), so a sidecar spawned on another host would be
  unreachable. Scale out by moving the whole stack, not by adding remote
  backend nodes.
 - **Instance backends:** `subprocess` (local dev; spawns `command`, with an
  optional relative `cwd` resolved against the repo root so the integration
  can be run straight from its `integrations/` submodule; the backend's
  interpreter is put first on PATH so the sidecar's deps resolve) or `docker`
  (production: runs `image` — built from the integration's git submodule by
  CI — pulls on demand, binds the container to 127.0.0.1 on an ephemeral
  host port, needs the Docker socket, which `deploy/docker-compose.yml`
  mounts on the backend service only). The sidecar port stays loopback-only;
  the backend dials it via `EEPY_MCP_DOCKER_HOST` (default `127.0.0.1` for
  on-host dev; compose sets it to `host.docker.internal` + `extra_hosts:
  host-gateway` because the backend is itself containerized). The bridge
  speaks MCP over stdio (subprocess) or streamable-HTTP (docker/url).
  **Per-backend env:** the two backends need different upstream transports
  for the same server, so runtime_config may set `subprocess_env` (replaces
  `env` for the subprocess backend; `env` stays the docker-backend value).
  The HappyFox seed uses `env: {MCP_TRANSPORT: streamable-http, PORT: 8000}`
  + `subprocess_env: {MCP_TRANSPORT: stdio}` — without the override the
  subprocess sidecar would bind 0.0.0.0:8000 in HTTP mode and the stdio
  handshake would fail (regression-tested; the fake test server refuses
  stdio when an HTTP transport is selected, and an e2e test drives the real
  pinned happyfox-mcp submodule through the subprocess path).
 - **Durable tracking + boot orphan sweep (Portainer-safety):** the in-memory
  registry dies with the process, so long-lived docker sidecars are ALSO
  recorded in the `mcp_sidecars` table (key = secret-free credential hash;
  never credentials; `node_id` = the backend process that owns it). Every
  sidecar container is labelled `eepy-host.sidecar=true` (plus template +
  key prefix) so it is identifiable in Portainer's container list and by
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
  `NODE_ID` is a per-process uuid by default; set `EEPY_NODE_ID` only if your
  orchestrator already guarantees a unique id per backend process. Tracking
  is fail-soft: a DB hiccup must never break a tool call.

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
4. Dark "console feel" — void surfaces with eepy-lavender/peach/mint accents.

## Operational Notes

- **Working repo is `~/Eepy-Host` (capital E).** Do not create or clone a
  second copy (a stray lowercase `~/eepy-host` clone was found and deleted
  2026-08-20; one of its never-pushed commits was saved as a patch in
  `~/attachments/` before deletion). If a fresh clone is ever needed, use
  `git clone --recurse-submodules` so `integrations/happyfox-mcp` is present
  (a plain clone leaves the submodule dir empty until
  `git submodule update --init`).
- **Two CI workflows, both on push to main:** `CI` (ruff+pytest, eslint+tsc —
  no image builds) and `Build and Push to GHCR`, which builds **three**
  images: `eepy-host-backend`, `eepy-host-frontend`, and
  `eepy-host-happyfox` (the sidecar, built from the submodule via
  `integrations/Dockerfile.happyfox` with the repo root as build context). So
  every push to main refreshes all deployed images.
- **Seed roll-forward:** `seed_mcp_templates()` in `main.py` updates the
  existing HappyFox row's `runtime`, `runtime_config`, `config_schema`,
  `image_tag`, and approval flags on **every boot** (idempotent). That is how
  spec changes reach the live DB — pushing a backend change is enough; no
  manual DB edit needed.
- **Portainer rollout (primary deploy path):** after a main push, pull the
  updated `eepy-host-backend:latest` / `eepy-host-frontend:latest` /
  `eepy-host-happyfox:latest` images and recreate the containers (the
  sidecar image is pulled lazily by the bridge, so just make sure the
  backend has fresh access). `stack.env` values rarely change — only when a
  new secret is introduced.
- **Verify the docker sidecar path (production):** it cannot be exercised in
  the dev sandbox (no Docker daemon), so after a deploy: hit the dashboard's
  connection test, then a real proxy tool call, and confirm in the backend
  logs that `mcp-bridge: started sidecar container ... port=...` appears and
  the call returns upstream data. The `EEPY_MCP_DOCKER_HOST` routing
  (host-gateway → loopback-bound sidecar port) is the piece to watch.
- **Dev-sandbox test tooling (ephemeral, rebuild if missing):** venv at
  `/tmp/eevenv` (`python3 -m venv /tmp/eevenv && /tmp/eevenv/bin/pip install
  -r requirements.txt pytest ruff`), and integration script
  `/tmp/eepy_test.sh` + `/tmp/eepy_test.py` (22 end-to-end checks: role
  escalation, JWT, superuser authz, Fernet-at-rest, rate limits, eekey
  scoping). Tests use a throwaway SQLite DB via `conftest.py`.
 - **Secrets** come from `deploy/stack.env` (git-ignored): `POSTGRES_PASSWORD`,
  `DATABASE_URL`, `SECRET_KEY`, `MCP_ENCRYPTION_KEY`, plus the optional
  `EEPY_MCP_INSTANCE_BACKEND` (sidecar runtime: `docker` default in compose,
  or `subprocess`). `EEPY_MCP_DOCKER_HOST` is set by the compose file itself
  (not in stack.env) to `host.docker.internal` so a containerized backend can
  reach loopback-bound sidecar ports. Optional sidecar containment dials
  (env-overridable, sensible defaults): `EEPY_MCP_SIDECAR_MEM_LIMIT`,
  `EEPY_MCP_SIDECAR_CPU_LIMIT`, and per-template `user` / digest-pinned
  `image` in `runtime_config` (see the security note above).
  `SECRET_KEY` signs JWTs (also the Fernet fallback key) — see Key
  Architecture Decision #3 before ever rotating it.
- **Initial superuser** is bootstrapped from the `SUPERUSER_USERNAME` env var
  at startup (idempotent promotion).
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
