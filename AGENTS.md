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
credentials (encrypted at rest), and all proxy routing. For **modular
integrations** (`runtime=mcp-server`) the backend may spawn short-lived
per-user MCP *sidecars* (subprocesses or containers) running upstream
third-party MCP servers — but those are ephemeral, idle-reaped, and never
part of the user-facing control plane. No persistent per-user containers.

## Current State (Phase 5 complete: modular MCP sidecar runtime)

- Unified auth portal + dashboard hub (account, debug console, organization
  admin tools for superusers, servers).
- HappyFox Help Desk is Template #1: seeded at startup in `main.py`
  (`seed_mcp_templates()`, idempotent) with `approved_by_admin=True`, and now
  runs on the **modular sidecar runtime** (`runtime=mcp-server`) using the
  upstream `ghcr.io/glitch3dpenguin/happyfox-mcp` image — the reference
  implementation for every future integration.
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
       "image": "ghcr.io/whoever/some-mcp:latest",
       "command": ["python", "server.py"],
       "env": {"MCP_TRANSPORT": "streamable-http", "PORT": "8000"},
       "endpoint": "/mcp",
       "port": "8000",
       "env_mapping": {"USER_FIELD_A": "UPSTREAM_ENV_A", "USER_FIELD_B": "UPSTREAM_ENV_B"},
       "test_tool": {"name": "some_read_only_tool", "arguments": {}},
       "tool_names": ["tool_a", "tool_b"]
     }
     ```
     - `env_mapping` maps each **user credential field** (from
       `config_schema`) to the **upstream env var** the sidecar reads.
       Unmapped fields are never passed to the sidecar.
     - `image` → docker backend (pulls + runs a sidecar container, needs the
       Docker socket). `command` → subprocess backend (spawns a local process;
       the server code must be reachable from the backend). Set
       `EEPY_MCP_INSTANCE_BACKEND` to pick; compose defaults to `docker`.
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

**Maintenance when the upstream repo changes:** bump the `image` tag in
`runtime_config` (or let it track `:latest`) and re-run discovery. No Eepy
backend code changes — that is the whole point of the modular path.

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
- **Node-local by design:** a sidecar is a local process/container on whichever
  backend node receives the request. All durable state (templates, encrypted
  credentials, tool keys, discovered tools) lives in the shared PostgreSQL, so
  any node can serve any user — it just (re)spawns a sidecar on demand. This is
  what keeps the stack horizontally scalable/load-balancable.
- **Instance backends:** `subprocess` (default; spawns `command`, needs the
  MCP server's deps in the backend env) or `docker` (runs `image`, pulls on
  demand, binds the container to 127.0.0.1 on an ephemeral host port — needs
  the Docker socket, which `deploy/docker-compose.yml` mounts on the backend
  service only). The bridge speaks MCP over stdio (subprocess) or
  streamable-HTTP (docker/url).

**Security note (sidecars run third-party code):** the `approved_by_admin` /
`enabled_global` gate is the moderation layer. Pin image tags to digests for
production, and consider resource/egress limits on sidecars before opening the
library to unvetted community repos.

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

- **Secrets** come from `deploy/stack.env` (git-ignored): `POSTGRES_PASSWORD`,
  `DATABASE_URL`, `SECRET_KEY`, `MCP_ENCRYPTION_KEY`, plus the optional
  `EEPY_MCP_INSTANCE_BACKEND` (sidecar runtime: `docker` default in compose,
  or `subprocess`).
  `SECRET_KEY` signs JWTs (also the Fernet fallback key) — see Key
  Architecture Decision #3 before ever rotating it.
- **Initial superuser** is bootstrapped from the `SUPERUSER_USERNAME` env var
  at startup (idempotent promotion).
- **Schema inspection:** `DESCRIBE mcp_templates; DESCRIBE user_mcp_configs;`
  in psql.
- **Monetization telemetry (planned, post-launch):** `last_used_at` + per
  config request counters for usage-based decisions.

## Workflow Preferences

- Direct main-branching (no feature branches yet); rapid prototyping →
  implementation verification cycle.
- Communication style: professional/factual; minimize emoji in documentation
  unless an aesthetic requirement is validated in code review.
