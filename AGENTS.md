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
platform. No per-user containers, no container sprawl — a single unified
FastAPI backend proxies every integration.

## Current State (Phase 4+ complete)

- Unified auth portal + dashboard hub (account, debug console, organization
  admin tools for superusers, servers).
- HappyFox Help Desk is Template #1: seeded at startup in `main.py`
  (`seed_mcp_templates()`, idempotent) with `approved_by_admin=True`.
- Unified proxy endpoint handles all templates via `TEMPLATE_REGISTRY` in
  `backend/api/mcp_endpoints.py`.
- Open WebUI integration: per-user **Tool API Keys** (`eekey_...`, one key
  unlocks every integration) + a single unified OpenAPI spec for import.

## Key Architecture Decisions

1. **Single backend endpoint per integration** — proxy routes, no user
   containers.
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
  (also an idempotent `backend/run_migrations.py`), JWT auth (python-jose).
- **Deploy:** Docker Compose in `deploy/` (db + backend + frontend), GHCR
  images via CI.

## Repository Layout

```
├── backend/
│   ├── main.py               # FastAPI app, router mounting, template seeding,
│   │                         #   superuser routes, superuser bootstrap
│   ├── auth.py               # JWT encode/decode (python-jose)
│   ├── database.py           # engine/session (DATABASE_URL from env)
│   ├── run_migrations.py     # idempotent schema bootstrap
│   ├── api/
│   │   └── mcp_endpoints.py  # ALL MCP routes: tool keys, template list,
│   │                         #   config register/list/delete/test/mcp-url,
│   │                         #   unified proxy, unified OpenAPI spec
│   ├── models/
│   │   └── mcp_models.py     # MCPTemplate, UserMCPConfig, MCPUserToolKey,
│   │                         #   MCPTemplateRequest
│   ├── utils/
│   │   └── crypto.py         # Fernet encrypt/decrypt (+ SECRET_KEY fallback)
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
| `GET /api/mcp/openapi.json` | Unified OpenAPI spec of ALL connected tools (Open WebUI import) | public |

**Tool API Keys** are stored hashed (`mcp_user_tool_keys`) and accepted ONLY
on the proxy and config-test routes. On any other route an `eekey_` bearer is
rejected — session JWTs and tool keys have strictly different scopes.

## Adding a New Integration (runbook)

1. **Register the template** — either seed it in `main.py` (like HappyFox) or
   add an `MCPTemplate` row, with `config_schema` (JSON: field name, type
   `string`/`password`, label, help, required) describing which credentials to
   collect.
2. **Add to `TEMPLATE_REGISTRY`** in `backend/api/mcp_endpoints.py` — the tool
   map (tool name → upstream HTTP method + path) plus upstream base-URL/
   auth logic. The unified proxy picks it up automatically.
3. **Approve it** — `approved_by_admin=True`, `enabled_global=True`.
4. **Done.** It appears in the library, the connect wizard renders from
   `config_schema`, and its tools show up in every user's unified Open WebUI
   connection automatically (single-connection model).

HappyFox credential fields: `HAPPYFOX_DOMAIN` (string),
`HAPPYFOX_API_KEY` + `HAPPYFOX_AUTH_CODE` (password). Upstream API:
`https://{domain}/api/1.1/json/`. Write tools require user confirmation per
the upstream spec — keep that.

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
python run_migrations.py
uvicorn main:app --reload --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
```

### Frontend development
```bash
cd frontend
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev
pnpm build && pnpm start
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
cd frontend && pnpm vitest run --reporter=verbose && pnpm lint
```

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
  `DATABASE_URL`, `SECRET_KEY`, `MCP_ENCRYPTION_KEY`.
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
