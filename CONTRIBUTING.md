# Contributing to Eepy Host

Thanks for your interest! Eepy Host is proprietary software owned by Kulik
Labs Development (see [LICENSE](LICENSE)). Issues and pull requests are
welcome under the rules below.

## Ways to contribute

- **Report a bug** — open an issue using the
  "Eepy Host issue (bug report)" template.
- **Request an integration** — open an issue using the
  "Request a new MCP integration" template to suggest an app or service you
  would like MCP access to.
- **Submit a pull request** — for code changes (see the checklist in
  [PULL_REQUEST_TEMPLATE.md](PULL_REQUEST_TEMPLATE.md)).
- **Report a security vulnerability** — follow
  [SECURITY.md](SECURITY.md). Never report vulnerabilities in public issues
  or pull requests.

By submitting a change, you agree that it may be used, modified, and
redistributed under the repository's [license](LICENSE) by Kulik Labs
Development. No CLA is required.

## Workflow

- The maintainers work directly on `main` in a rapid prototype → verify →
  push cycle. External contributors should branch from `main` and open a
  pull request.
- Commit messages follow the Conventional Commits style:
  `fix(proxy): ...`, `feat(auth): ...`, `docs(readme): ...`.
- CI runs on every push and PR: `ruff check` + `pytest` for the backend,
  ESLint + `tsc --noEmit` for the frontend. Do not push with CI red.

## Local setup

```bash
git clone --recurse-submodules https://github.com/Kulik-Labs-Development/Eepy-Host.git
cd Eepy-Host
```

The submodule checkout matters: `integrations/` holds the upstream MCP
server repos the gateway wraps. A plain clone leaves them empty.

Then follow [README.md → Getting Started](README.md#getting-started) for the
backend (Python 3.12+, venv, `stack.env` with `DATABASE_URL` / `SECRET_KEY` /
`MCP_ENCRYPTION_KEY`) and the frontend (Node 18+, `npm install`).

## Testing

```bash
# Backend (throwaway SQLite DB — no live Postgres or Docker needed)
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

Before pushing any change that touches request handling, verify it
end-to-end: start the stack, make a live call through the proxy (or the
dashboard's connection test), and confirm the upstream data comes back.

## Conventions

### Backend (Python / FastAPI)

- **Absolute imports in `backend/main.py`.** Uvicorn runs it as a top-level
  script, so relative imports fail. Always `from api... import ...`.
- **Never log, persist, or echo decrypted credentials.** Handlers may log
  *which* template or tool ran — never the credential values.
- **Server-side RBAC is non-negotiable.** Frontend role checks are cosmetic;
  every privileged endpoint must enforce the JWT role server-side.
- **Event-loop rule.** Synchronous work inside an `async def` endpoint
  blocks every in-flight request. Sync-only endpoints are plain `def`;
  blocking work inside genuinely async endpoints goes through
  `asyncio.to_thread`.

### Frontend (Next.js / TypeScript)

- Follow the **"Retro Cozy"** design system: reuse the palette tokens and
  component classes in `frontend/tailwind.config.js` and
  `frontend/app/globals.css` (`.panel`, `.btn-*`, `.chip`, `.led`, ...)
  instead of re-deriving styles. No raw `text-gray-*`, no blurred glows.
- Lucide React icons only.
- After any programmatic edit of a `.tsx` file, re-run the build — escaping
  artifacts break Next.js immediately.

### Integrations

- Integration code lives in **upstream repos as git submodules** under
  `integrations/` — never vendor it into this backend. The gateway owns one
  generic bridge (`backend/api/mcp_bridge.py`).
- A new integration = add the submodule + `integrations/Dockerfile.<name>` +
  a CI build step in `.github/workflows/main.yml` + an `MCPTemplate` seed
  (`runtime=mcp-server`, `config_schema`, `runtime_config`) + admin approval
  and tool discovery. The full runbook is in
  [AGENTS.md](AGENTS.md) ("Adding a New Integration").
- Updating an integration = bump the submodule ref and push; CI rebuilds the
  sidecar image from that exact commit. Re-run discovery after the bump.

## Documentation

If your change alters the architecture, adds/removes endpoints or env vars,
or changes a convention above, update [README.md](README.md) and
[AGENTS.md](AGENTS.md) in the same PR. AGENTS.md is the single source of
truth for project state — stale docs are a bug.
