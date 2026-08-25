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
  <img alt="Frontend" src="https://img.shields.io/badge/Frontend-Next.js_15-38bdf8?logo=next.js&logoColor=white" />
  <img alt="Backend" src="https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white" />
  <img alt="Database" src="https://img.shields.io/badge/Database-PostgreSQL-336791?logo=postgresql&logoColor=white" />
  <img alt="Auth" src="https://img.shields.io/badge/Auth-JWT_%2B_bcrypt-4f46e5" />
  <img alt="Encryption" src="https://img.shields.io/badge/Credentials-Fernet_encrypted_0f9d58" />
  <img alt="License" src="https://img.shields.io/badge/License-Proprietary-lightgrey" />
  <img alt="CI" src="https://github.com/Kulik-Labs-Development/Eepy-Host/actions/workflows/ci.yml/badge.svg" />
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

- **Unified authentication portal** — single `/auth` flow for sign-in and sign-up with JWT sessions (PyJWT + bcrypt), plus brute-force rate limiting on `/auth/login` and `/auth/signup`.
- **Role hierarchy** — strict `USER` / `SUPERUSER` roles enforced at the API layer (the frontend is never the source of truth). Superusers manage the organization hub: user directory, role changes, account purging.
- **Integration library** — admin-approved MCP templates with schema-driven connect wizards. Credentials are collected, encrypted server-side (Fernet), and never returned to the client.
- **Unified proxy** — every tool call for every integration flows through `/api/mcp/proxy/{template_id}/{tool}`. Credentials are decrypted in memory for the duration of the request only — never logged, never persisted in plaintext.
- **Live connection testing** — users validate stored credentials against the real upstream API from the dashboard in one click.
- **Modular integration runtime** — integration MCP servers live in their own upstream repos, pulled in as git submodules under `integrations/`. CI builds each submodule into its own sidecar image on every push, and the gateway spawns short-lived, idle-reaped per-user sidecars (subprocess locally, container in production) — updating an integration is a submodule bump, never a backend change.
- **Open WebUI as a single tool server** — one user-scoped, revocable API key + one OpenAPI spec URL covers *every* integration the user has connected, now and in the future. No per-server imports, ever.
- **Dashboard** — Overview hub with the Open WebUI tool-server connection and a live status flag; account & profile management; per-server observability (last used, live tests); organization tools for superusers.

## Design Language

The frontend follows a **"Retro Cozy"** design system — a 16-bit pixel-art
aesthetic: warm, muted, and nostalgic. A deep aubergine-brown night sky, soft
blush and bright-pink accents, earthy sage and amber, cream text. No neon, no
glassmorphism: chunky 2px borders, hard (unblurred) pixel shadows, squared
corners, `steps()` animations, and dithered/scanline textures.

- **Palette** — `night` surfaces (`base`/`deep`/`surface`/`raise`/`border`/`line`)
  with accents `eepy-blush` (primary), `eepy-pink` (highlight), `eepy-sage`
  (success/on), `eepy-amber` (warn/secondary), `eepy-lilac` (tertiary),
  `eepy-ember` (danger), and a warm cream `ink` text scale. Defined in
  [`frontend/tailwind.config.js`](frontend/tailwind.config.js).
- **Type** — three fonts via `next/font`: **Pixelify Sans** (`font-pixel`,
  headings/buttons/nav), **VT323** (`font-console`, logs, code, URLs — keep
  ≥13px), **Nunito** (`font-body`, prose).
- **Components** — reuse the classes in
  [`frontend/app/globals.css`](frontend/app/globals.css) instead of
  re-deriving: `.panel` / `.well` / `.card` surfaces, `.btn`
  (`.btn-blush|sage|amber|ghost|danger`), `.btn-icon`, `.input-pixel`,
  `.label-pixel`, `.chip` (tinted variants), `.led` squared status lights,
  `.pixel-caps` corner rivets, `.tex-dither` / `.tex-bands` textures,
  `.text-px` hard text shadows, `.lift` stepped hover.
- **Brand marks** — the sleepy pixel moon (`src/components/PixelMoon`) is the
  mascot and favicon; the shared `CozyBackdrop` renders the banded night sky
  with twinkling pixel stars behind every page.

Keep it consistent: when adding UI, pick from the existing tokens and
component classes. The full ruleset for agents lives in
[AGENTS.md](AGENTS.md) ("Retro Cozy" design system).

## Built-in Integrations

Each integration is an upstream MCP server we import as a git submodule under
`integrations/`, build into its own sidecar image in CI, and run as a short-
lived per-user sidecar. The tool list and behavior are maintained by the
original author — follow the link for the full, current list of tools.

| Integration | What it does | Upstream project |
|-------------|--------------|------------------|
| **HappyFox Help Desk** | Read and act on support tickets (triage, reply, update status) via your HappyFox account. | [Glitch3dPenguin/happyfox-mcp](https://github.com/Glitch3dPenguin/happyfox-mcp) |
| **eBay Sell** | 299 tools over eBay's Sell APIs: inventory, orders & fulfillment, promoted listings, seller analytics, messaging — sandbox or production. | [YosefHayim/ebay-mcp](https://github.com/YosefHayim/ebay-mcp) |

**Connecting to HappyFox** requires three values from your HappyFox account:
**domain**, **API key**, and **auth code** (found in *Settings → API* on your
HappyFox site). Write actions require your confirmation per the upstream spec.

**Connecting to eBay** requires your **Client ID** and **Client Secret** (App
ID / Cert ID from the [eBay Developer
Portal](https://developer.ebay.com/my/keys)) plus an **environment** choice
(`sandbox` or `production`). Optionally, the RuName redirect URI and a user
refresh token unlock the higher rate limits (10k–50k req/day). Unofficial
third-party project — you remain responsible for eBay's API terms.

### More on the way

New integrations are added as admin-approved templates imported from their own
upstream repos. Because the Open WebUI export is a single unified spec, new
integrations appear in existing agent connections automatically — no re-import,
no second connection.

## Open WebUI Integration

Eepy Host is designed to be **one** external tool server for your agent, not one per integration:

1. **Create a key** — In the Eepy dashboard, open the **Open WebUI** section on the **Overview** page (it shows your live connection status at a glance) and generate a Tool API Key (`eekey_…`). The plaintext is shown once; only a SHA-256 hash is stored. The key is user-scoped: it unlocks every integration *you* have connected.
2. **Copy the URL** — `https://<your-host>/api/mcp` is what you paste into Open WebUI (leave it exactly as copied — Open WebUI appends `/openapi.json` itself). The spec it fetches is a public, secret-free OpenAPI 3.0 document describing the entire Eepy tool surface (tools namespaced as `/{template}/{tool}`).
3. **Import in Open WebUI** — Settings → Tools → add an external Tool Server → paste the URL from step 2 → Bearer auth with your key. Done.

> **CORS note:** Open WebUI calls the API from *its* browser origin, so the
> backend answers preflights from **any origin by default** (the API is
> Bearer-token authenticated only — no cookie sessions — so a wildcard origin
> cannot leak cross-origin data). Set `CORS_ORIGINS` (comma-separated list) in
> the backend environment to pin exact origins instead.

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
git clone --recurse-submodules https://github.com/Kulik-Labs-Development/Eepy-Host.git
cd Eepy-Host/deploy
cp stack.env.example stack.env
# edit stack.env: set a strong SECRET_KEY and generate a Fernet key:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker compose --env-file stack.env up -d
```

> **Portainer:** import `deploy/docker-compose.yml` as a stack from the
> repository (or paste its contents) and paste the contents of your filled-in
> `stack.env` into the **Environment** section of the stack editor. The file is
> intentionally named `stack.env` — not `.env` — to keep it obvious which
> secrets belong to the stack.
>
> **Note on MCP sidecar containers:** when users' integrations run as
> containerized MCP servers, the backend spawns short-lived, loopback-only
> sidecar containers on demand (named `eepy-mcp-*`, labelled
> `eepy-host.sidecar=true`). They are idle-reaped (default 5 min) and are
> **auto-cleaned on every backend restart** — if you ever see an `eepy-mcp-*`
> container in Portainer's container list, it is an on-demand sidecar, not
> part of the stack; a fresh backend boot sweeps any stale ones away.

| Service | URL |
|---------|-----|
| Frontend (Next.js) | http://localhost:8067 |
| Backend API (FastAPI) | http://localhost:8068 |
| Swagger docs | http://localhost:8068/docs |
| Unified OpenAPI spec (Open WebUI) | http://localhost:8068/api/mcp/openapi.json |

### Option 2 — Local development

```bash
# 1. Database
docker compose -f deploy/docker-compose.yml --env-file deploy/stack.env up -d db

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Load DATABASE_URL, SECRET_KEY, MCP_ENCRYPTION_KEY from the stack file:
set -a; source ../deploy/stack.env; set +a
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
| `EEPY_MCP_INSTANCE_BACKEND` | How `mcp-server` runtime templates run: `docker` (compose default, pulls the integration image per user) or `subprocess` (local process). |
| `EEPY_MCP_DOCKER_HOST` | Address used to reach sidecar containers' loopback ports. Compose sets this to `host.docker.internal` automatically. |
| `EEPY_MCP_INSTANCE_IDLE_TIMEOUT` | Seconds before an idle MCP sidecar is reaped (default `300`). |
| `NEXT_PUBLIC_API_URL` | Backend base URL used by the frontend |

See [deploy/stack.env.example](deploy/stack.env.example) for the full reference.

### Testing & CI

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs on every push/PR to `main`:

- **Backend:** `ruff check` (lint) + `pytest` (auth/JWT, credential encryption, and end-to-end tests for the MCP sidecar bridge against a fake stdio MCP server — no live database or Docker required).
- **Frontend:** ESLint (`next/core-web-vitals`) + `tsc --noEmit`.

Run locally:

```bash
# Backend (no DB needed for the unit test suite)
cd backend
pip install -r requirements.txt pytest ruff
ruff check .
pytest tests/ -q

# Frontend
cd frontend
npm install
npm run lint
npx tsc --noEmit
```

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
| `POST /superuser/mcp/templates/{id}/discover` | Capture the template's upstream `tools/list` schemas | SUPERUSER |
| `PATCH /superuser/mcp/templates/{id}/runtime` | Set a template's sidecar spec + approval flags | SUPERUSER |
| `GET /api/mcp/openapi.json` | Unified OpenAPI spec for Open WebUI (also served at `/api/mcp/openapi.json/openapi.json` for Open WebUI's URL auto-append) | public |
| `POST /api/mcp/api-keys` | Add a user-scoped, revocable tool key (existing keys are never replaced) | JWT |
| `GET /api/mcp/api-keys` | List keys (hash-only; prefixes only) | JWT |
| `DELETE /api/mcp/api-keys/{id}` | Revoke a key; `?hard=true` deletes the entry entirely | JWT |
| `POST /api/mcp/api-keys/{id}/reveal` | Re-view a key's plaintext after re-entering the account password | JWT |

## Security Model

- **Encryption at rest.** Integration credentials are encrypted with Fernet (single master key from `MCP_ENCRYPTION_KEY`) before being written to PostgreSQL. Only ciphertext is ever persisted.
- **Memory-only decryption.** Credentials are decrypted inside the request handler and dropped at the end of the request. Plaintext never reaches logs, disk, or API responses.
- **Backend-enforced RBAC.** Every privileged route checks the JWT role server-side; client-side role checks are presentation only.
- **Scoped, revocable tool keys.** External integrations (Open WebUI) authenticate with narrow `eekey_` keys that work on proxy routes only, resolve to a single user, and can be killed instantly. Keys are stored as a hash plus a Fernet-encrypted copy, so the owner can re-view one in the dashboard only after re-entering their account password.
- **Admin-gated integrations.** No template is usable until a superuser approves it — the library is curated, not open.

Security vulnerabilities should be reported privately — see [SECURITY.md](SECURITY.md).

## Project Structure

```
├── frontend/                 # Next.js (App Router) + Tailwind ("Retro Cozy" pixel UI)
│   ├── app/
│   │   ├── auth/             # Unified sign-in / sign-up portal
│   │   └── dashboard/
│   │       ├── page.tsx      # Overview: Open WebUI tool server + status flag
│   │       ├── servers/      # Active integrations + browsable library
│   │       ├── account/      # Profile & identity management
│   │       ├── organization/ # Superuser org hub
│   │       ├── debug/        # Live console log
│   │       └── settings/
│   ├── context/AuthContext.tsx
│   ├── lib/api.ts
│   └── src/components/       # MCPConnectionWizard, OpenWebUIExportPanel,
│                             #   PixelMoon, CozyBackdrop
├── backend/
│   ├── main.py               # FastAPI app, router mounting, template seeding,
│   │                         #   superuser routes, superuser bootstrap
│   ├── auth.py               # JWT encode/decode (PyJWT)
│   ├── database.py           # engine/session (DATABASE_URL from env)
│   ├── run_migrations.py     # idempotent schema bootstrap
│   ├── api/
│   │   ├── mcp_endpoints.py  # ALL MCP routes: proxy (routes by runtime),
│   │   │                     #   config lifecycle, tool keys, OpenAPI spec
│   │   └── mcp_bridge.py     # modular sidecar bridge: spawn/reuse per-user
│   │                         #   MCP sidecars (subprocess or docker), idle reaper
│   ├── models/
│   │   └── mcp_models.py     # Templates, user configs, tool keys,
│   │                         #   mcp_sidecars (durable sidecar tracking)
│   ├── utils/
│   │   ├── crypto.py         # Fernet credential encryption
│   │   └── logging_setup.py  # shared logger config
│   ├── alembic/              # Migration structure
│   └── requirements.txt
├── integrations/             # upstream MCP server repos, as git submodules
│   ├── Dockerfile.happyfox   #   CI builds the submodule into the sidecar image
│   ├── Dockerfile.ebay       #   CI builds the submodule into the sidecar image
│   ├── happyfox-mcp/         #   → Glitch3dPenguin/happyfox-mcp (submodule)
│   └── ebay-mcp/             #   → YosefHayim/ebay-mcp (submodule)
└── deploy/
    ├── docker-compose.yml    # db + backend + frontend (no secrets in the file)
    └── stack.env.example     # secret reference — copy to stack.env and fill in
```

## Adding a New Integration

Two runtimes exist — prefer `mcp-server` (the modular path; no per-integration
code in this repo):

1. **`runtime=mcp-server` (recommended)** — bring the integration's MCP server repo into `integrations/` as a git submodule, add a `Dockerfile.<name>` next to it (build context = repo root) plus a build step in `.github/workflows/main.yml`, and register an `MCPTemplate` with its `runtime_config` (image, `env_mapping` of user credential fields → upstream env vars, `test_tool`) and its `config_schema`. Approve it (`approved_by_admin=True`, `enabled_global=True`), then as superuser connect it once and call `POST /superuser/mcp/templates/{id}/discover` to capture the upstream's real tool schemas. **Updating the integration later = update the submodule ref and push** — CI rebuilds the sidecar image from exactly that commit; re-run discovery after the bump.
2. **`runtime=native` (legacy/reference)** — add the template's tool map to
   `TEMPLATE_REGISTRY` in `backend/api/mcp_endpoints.py`. Only HappyFox uses
   this path today (kept for rollback).

Either way, the connect wizard renders from `config_schema`, and because the
OpenAPI export is unified, the new tools appear in every user's existing Open
WebUI connection automatically — no re-import.

## Development Notes

A few hard-learned conventions for this codebase:

- **Absolute imports in the backend.** `backend/main.py` runs as a top-level module under Uvicorn, so relative imports (`from .models…`) fail with `ImportError`. Always import absolutely (`from models…`, `from api…`).
- **Never log credential values.** Handlers may log *which* template was connected or which tool ran — never the credential fields themselves.
- **Backend is the source of truth.** Frontend role checks are UX sugar; every protected endpoint enforces JWT + role server-side.
- **JSX edits.** When generating `.tsx` programmatically, verify the file compiles after the write — escaping artifacts break the Next.js build immediately.
- **Follow the design language.** The frontend is a 16-bit "Retro Cozy" pixel UI (warm night palette, chunky 2px borders, hard pixel shadows, stepped animations). Build from the existing tokens and component classes in `frontend/tailwind.config.js` + `frontend/app/globals.css` — see [Design Language](#design-language).

## Roadmap

- [x] Auth portal, JWT RBAC, organization hub
- [x] HappyFox integration (9 tools) + encrypted credential lifecycle
- [x] Unified MCP proxy + live connection testing
- [x] Single-connection Open WebUI tool server (user-scoped keys, unified spec)
- [x] Modular MCP sidecar runtime (`mcp-server` templates, idle-reaped per-user sidecars)
- [ ] Additional integrations (calendar, workspace chat, notes/databases)
- [ ] Usage analytics (per-template call volume, health)
- [ ] Template pricing tiers and billing

## Licensing

Eepy Host is proprietary software owned by **Kulik Labs Development**.

- **Personal / non-commercial use:** free. You may run, copy, modify, and share the code for private, educational, or evaluation purposes.
- **Commercial use: not permitted** under this license. You may not sell the software, build a business or paid service on top of it, or offer it to third parties for a fee (SaaS, white-label, consulting deliverables, etc.).
- **Commercial licenses** are available from Kulik Labs Development — see the repository for contact info.

See [LICENSE](LICENSE) for the full terms. Use of this repository constitutes acceptance of those terms.

## Contributing

This project currently follows a rapid-iteration workflow on `main`:

1. Prototype the UI, then wire the backend route.
2. Verify end-to-end (build + a live call through the proxy) before pushing.
3. Keep credential handling on the approved path: Fernet at rest, in-memory only.

Issues and PRs are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the
full guide (setup, testing, conventions) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
for community expectations. For security concerns, follow
[SECURITY.md](SECURITY.md) and report privately — never in a public issue or
pull request.

## License

Proprietary — all rights reserved. © Kulik Labs Development.

---

<p align="center"><em>Stay cozy, keep connecting.</em></p>
