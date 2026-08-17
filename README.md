<p align="center">
  <img src="assets/images/glossy-zzz.png" alt="Eepy Host" width="220" />
</p>

<h1 align="center">Eepy Host</h1>

<p align="center">
  <strong>The managed MCP gateway.</strong><br/>
  A unified platform that connects AI agents to external tools and services —<br/>
  without containers, without credential sprawl, without operational overhead.
</p>

<p align="center">
  <img alt="Frontend" src="https://img.shields.io/badge/Frontend-Next.js_14-38bdf8?logo=next.js&logoColor=white" />
  <img alt="Backend" src="https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white" />
  <img alt="Database" src="https://img.shields.io/badge/Database-PostgreSQL-336791?logo=postgresql&logoColor=white" />
  <img alt="Auth" src="https://img.shields.io/badge/Auth-JWT_%2B_bcrypt-4f46e5" />
  <img alt="Encryption" src="https://img.shields.io/badge/Credentials-Fernet_encrypted_0f9d58" />
  <img alt="License" src="https://img.shields.io/badge/License-Proprietary-lightgrey" />
</p>

---

## What is Eepy Host?

Eepy Host is a **managed integration layer between LLM agents and real-world SaaS APIs**. Instead of having users self-host a Docker container per MCP server — managing networking, credentials, and upgrades for each one — Eepy Host runs a single unified proxy. Users **connect integrations** through a guided wizard; Eepy Host stores their credentials **encrypted at rest**, and routes all agent tool calls through one gateway.

```
┌────────────────┐      ┌──────────────────────────────┐      ┌──────────────────┐
│ LLM Agent /    │      │          Eepy Host           │      │  External SaaS   │
│ Open WebUI     │ ───► │  /api/mcp/proxy/{id}/*       │ ───► │  (HappyFox, …)   │
└────────────────┘      │                              │      └──────────────────┘
                        │  · Fernet-encrypted creds    │
                        │  · per-user isolation        │
                        │  · scoped, revocable keys    │
                        └──────────────────────────────┘
```

### Why this design

| | Self-hosted MCP servers | Eepy Host |
|---|---|---|
| **User complexity** | Deploy and maintain one container per integration | Connect an integration in a browser wizard |
| **Resource cost** | N users × M integrations = N×M containers | One shared proxy process |
| **Credential security** | Keys scattered across container environments | Centralized, encrypted at rest in PostgreSQL |
| **Agent setup** | A separate tool connection per integration | **One** Open WebUI tool-server connection for everything |
| **Upgrades & plumbing** | Every user, every container | Once, on the gateway |

## Features

- **Unified authentication portal** — single `/auth` flow for sign-in and sign-up with JWT sessions (`python-jose` + bcrypt).
- **Role hierarchy** — strict `USER` / `SUPERUSER` roles enforced at the API layer (the frontend is never the source of truth). Superusers manage the organization hub: user directory, role changes, account purging.
- **Integration library** — admin-approved MCP templates with schema-driven connect wizards. Credentials are collected, encrypted server-side (Fernet), and never returned to the client.
- **Unified proxy** — every tool call for every integration flows through `/api/mcp/proxy/{template_id}/{tool}`. Credentials are decrypted in memory for the duration of the request only — never logged, never persisted in plaintext.
- **Live connection testing** — users validate stored credentials against the real upstream API from the dashboard in one click.
- **Open WebUI as a single tool server** — one user-scoped, revocable API key + one OpenAPI spec URL covers *every* integration the user has connected, now and in the future. No per-server imports, ever.
- **Dashboard** — account & profile management, per-server observability (last used, live tests), organization tools for superusers.

## Current Integrations

### HappyFox Help Desk (live)

Nine tools are exposed through the proxy, mapped to the HappyFox REST API v1.1:

| Tool | Description |
|------|-------------|
| `list_tickets` | List support tickets with status/pagination filters |
| `list_statuses` | List all ticket statuses in the account |
| `list_staff` | List staff members in the account |
| `get_ticket_details` | Full details of a single ticket |
| `get_ticket_messages` | All messages on a ticket thread |
| `add_ticket_update` | Post a public reply or private internal note |
| `create_ticket` | Create a new support ticket |
| `rename_ticket` | Change a ticket's subject line |
| `change_ticket_status` | Move a ticket to a new status |

Connecting requires three values from your HappyFox account: **domain**, **API key**, and **auth code** (found in *Settings → API* on your HappyFox site).

### More on the way

New integrations are added as admin-approved templates. Because the Open WebUI export is a single unified spec, new integrations appear in existing agent connections automatically — no re-import, no second connection.

## Open WebUI Integration

Eepy Host is designed to be **one** external tool server for your agent, not one per integration:

1. **Create a key** — In the Eepy dashboard, open the **Open WebUI** section on the MCP Servers page and generate a Tool API Key (`eekey_…`). The plaintext is shown once; only a SHA-256 hash is stored. The key is user-scoped: it unlocks every integration *you* have connected.
2. **Copy the spec URL** — `https://<your-host>/api/mcp/openapi.json` is a public, secret-free OpenAPI 3.0 document describing the entire Eepy tool surface (tools namespaced as `/{template}/{tool}`).
3. **Import in Open WebUI** — Settings → Tools → add an external Tool Server → paste the URL → Bearer auth with your key. Done.

Security properties of the key:

- Accepted **only** on the MCP proxy and connection-test routes — it cannot touch account, billing, or admin endpoints.
- Every call additionally requires that the key's owner has an *active connection* to the requested integration (otherwise `404`), so a leaked key can never reach an integration its owner hasn't connected.
- Revocable from the dashboard at any time; the next call with a revoked key fails with `401`.

## Getting Started

### Prerequisites

- Docker and Docker Compose (production)
- For local development: Python 3.12+, Node.js 18+, a PostgreSQL 15 instance (or let Compose provide it)

### Option 1 — Docker Compose

```bash
git clone https://github.com/Kulik-Labs-Development/Eepy-Host.git
cd Eepy-Host
cp .env.example .env
# edit .env: set a strong SECRET_KEY and generate a Fernet key:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose up -d
```

| Service | URL |
|---------|-----|
| Frontend (Next.js) | http://localhost:3000 |
| Backend API (FastAPI) | http://localhost:8000 |
| Swagger docs | http://localhost:8000/docs |
| Unified OpenAPI spec (Open WebUI) | http://localhost:8000/api/mcp/openapi.json |

### Option 2 — Local development

```bash
# 1. Database
docker compose up -d db

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example ../.env   # and fill in DATABASE_URL, SECRET_KEY, MCP_ENCRYPTION_KEY
uvicorn main:app --reload --port 8000

# 3. Frontend
cd ../frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

The backend creates missing tables on startup and seeds the approved template registry automatically.

### Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | Long random string; signs JWTs |
| `MCP_ENCRYPTION_KEY` | Fernet key for credential encryption at rest. Generate with `Fernet.generate_key()`. |
| `NEXT_PUBLIC_API_URL` | Backend base URL used by the frontend |

See [.env.example](.env.example) for the full reference.

## API Overview

All endpoints live under a single FastAPI app. Interactive docs at `/docs` when running.

| Method & Path | Purpose | Auth |
|---------------|---------|------|
| `POST /auth/signup` / `POST /auth/login` | Account creation / JWT session | public |
| `GET /user/me` | Current profile | JWT |
| `GET /api/mcp/templates/list` | Admin-approved integration library | JWT |
| `POST /api/mcp/config/register` | Store (encrypted) credentials for an integration | JWT |
| `GET /api/mcp/config/list` | List the user's connections (no credentials) | JWT |
| `POST /api/mcp/config/{template}/test` | Live validation against the upstream API | JWT or tool key |
| `DELETE /api/mcp/config/{template}` | Disconnect an integration | JWT |
| `POST/GET/PUT /api/mcp/proxy/{template}/{tool}` | Execute a tool call through the gateway | JWT or tool key |
| `GET /api/mcp/openapi.json` | Unified OpenAPI spec for Open WebUI | public |
| `POST /api/mcp/api-keys` | Create a user-scoped, revocable tool key | JWT |
| `GET /api/mcp/api-keys` | List keys (hash-only; prefixes only) | JWT |
| `DELETE /api/mcp/api-keys/{id}` | Revoke a key | JWT |

## Security Model

- **Encryption at rest.** Integration credentials are encrypted with Fernet (single master key from `MCP_ENCRYPTION_KEY`) before being written to PostgreSQL. Only ciphertext is ever persisted.
- **Memory-only decryption.** Credentials are decrypted inside the request handler and dropped at the end of the request. Plaintext never reaches logs, disk, or API responses.
- **Backend-enforced RBAC.** Every privileged route checks the JWT role server-side; client-side role checks are presentation only.
- **Scoped, revocable tool keys.** External integrations (Open WebUI) authenticate with narrow `eekey_` keys that work on proxy routes only, resolve to a single user, and can be killed instantly.
- **Admin-gated integrations.** No template is usable until a superuser approves it — the library is curated, not open.

## Project Structure

```
├── frontend/                 # Next.js (App Router) + Tailwind
│   └── app/
│       ├── auth/             # Unified sign-in / sign-up portal
│       └── dashboard/
│           ├── servers/      # MCP hub: active servers, Open WebUI, library
│           ├── account/      # Profile & identity management
│           ├── organization/ # Superuser org hub
│           ├── debug/        # Live console log
│           └── settings/
├── backend/
│   ├── main.py               # FastAPI app, router mounting, template seeding
│   ├── auth.py               # JWT encode/decode (python-jose)
│   ├── api/
│   │   └── mcp_endpoints.py  # Proxy, config lifecycle, tool keys, OpenAPI spec
│   ├── models/
│   │   └── mcp_models.py     # Templates, user configs, tool keys
│   ├── utils/
│   │   └── crypto.py         # Fernet credential encryption
│   ├── alembic/              # Migration structure
│   └── requirements.txt
├── docker-compose.yml        # db + backend + frontend
└── .env.example
```

## Adding a New Integration

1. **Register the template** — add an `MCPTemplate` (id, display name, description, `config_schema` describing which credentials to collect). It becomes visible to users once a superuser sets `approved_by_admin` and `enabled_global`.
2. **Implement proxy routing** — add the template to `TEMPLATE_REGISTRY` in `backend/api/mcp_endpoints.py` (tool map: tool name → upstream HTTP method + path) and the corresponding handler logic in the proxy route.
3. **Done.** The template appears in the library, the connect wizard renders from its `config_schema`, and — because the OpenAPI export is unified — the new tools appear in every user's existing Open WebUI connection automatically.

## Development Notes

A few hard-learned conventions for this codebase:

- **Absolute imports in the backend.** `backend/main.py` runs as a top-level module under Uvicorn, so relative imports (`from .models…`) fail with `ImportError`. Always import absolutely (`from models…`, `from api…`).
- **Never log credential values.** Handlers may log *which* template was connected or which tool ran — never the credential fields themselves.
- **Backend is the source of truth.** Frontend role checks are UX sugar; every protected endpoint enforces JWT + role server-side.
- **JSX edits.** When generating `.tsx` programmatically, verify the file compiles after the write — escaping artifacts break the Next.js build immediately.

## Roadmap

- [x] Auth portal, JWT RBAC, organization hub
- [x] HappyFox integration (9 tools) + encrypted credential lifecycle
- [x] Unified MCP proxy + live connection testing
- [x] Single-connection Open WebUI tool server (user-scoped keys, unified spec)
- [ ] Additional integrations (calendar, workspace chat, notes/databases)
- [ ] Usage analytics (per-template call volume, health)
- [ ] Template pricing tiers and billing

## Contributing

This project currently follows a rapid-iteration workflow on `main`:

1. Prototype the UI, then wire the backend route.
2. Verify end-to-end (build + a live call through the proxy) before pushing.
3. Keep credential handling on the approved path: Fernet at rest, in-memory only.

Issues and PRs are welcome. For security concerns, please open a private issue rather than a public report.

## License

Proprietary — all rights reserved. © Kulik Labs Development.

---

<p align="center"><em>Stay cozy, keep connecting.</em></p>
