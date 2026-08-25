# Security Policy

Eepy Host routes users' live SaaS credentials through a gateway, so we take
security reports seriously. This document explains how to report a
vulnerability and summarizes how the project approaches security.

## Supported versions

| Version | Supported |
|---------|-----------|
| `main` (current) | Yes |

Eepy Host does not cut numbered releases — the deployed gateway always runs
the current `main` branch (self-hosters pin a specific image build).
Security fixes land on `main` and are redeployed to the hosted service
promptly.

## Reporting a vulnerability

**Do not open a public issue or pull request for a security vulnerability.**

Report it privately using GitHub's private vulnerability reporting:

1. Open the [Eepy Host repository](https://github.com/Kulik-Labs-Development/Eepy-Host).
2. On the **Issues** tab, click **Report a vulnerability** (you must be
   signed in; the option appears under the issue creation menu).
3. Submit the report — a private thread is opened for discussion with the
   maintainers.

### What to include

- A description of the vulnerability and the affected component (backend
  API, proxy, sidecar bridge, frontend, deployment).
- Steps to reproduce or a proof of concept. Prefer a local
  `docker compose` instance with throwaway data over the hosted service.
- The commit or image version you observed it on (self-hosted).
- Any mitigations you are aware of.

### What will not be accepted

- Reports that require an operator's own secrets to be misconfigured (e.g.,
  a weak `SECRET_KEY` in a self-hosted deployment).
- DoS or stress testing against the hosted service.
- Unattended scans or probes of production without prior contact.

## Response process

- **Acknowledgment** — within 3 business days of the report.
- **Triage** — we will tell you whether the report is accepted, and if not,
  why.
- **Fix** — we target a fix on `main` within 14 days of acknowledgment;
  complex issues may take longer and we will keep you posted.
- **Disclosure** — after the fix is deployed, you will be credited in a
  release note unless you ask not to be.

## How we approach security

A high-level summary (the authoritative detail lives in
[AGENTS.md](AGENTS.md)):

- **Credentials encrypted at rest** (Fernet, single master key) in
  PostgreSQL; decrypted only in memory for the duration of a request and
  dropped afterward. Plaintext never reaches logs, disk, or API responses.
- **Scoped, revocable tool keys.** External clients (Open WebUI, MCP
  clients) authenticate with `eekey_` keys that work only on the MCP proxy,
  native MCP stream, and connection-test routes — never on account or admin
  endpoints — and can be revoked instantly.
- **Server-enforced RBAC.** Every privileged route validates the JWT role
  server-side; frontend role checks are presentation only.
- **Rate limiting** on auth routes (proxy-aware so a reverse proxy does not
  collapse all clients into one limit key).
- **SSRF guard** on the legacy native proxy path: the backend only dials
  https URLs whose resolved IPs are globally public (no loopback, RFC1918,
  link-local, or cloud metadata addresses).
- **Request body cap** (default 8 MB) enforced before routing, protecting
  unauthenticated routes from oversized bodies.
- **Dependency audits** — `pip-audit` and `npm audit` (including dev deps)
  after any dependency bump.
- **Sidecar containment** — per-user MCP sidecars run with CPU/memory
  limits, a minimal environment allowlist (the backend's own secrets never
  leak in), on an isolated docker network with no published ports, are
  idle-reaped, and are swept for orphans on every backend boot.
- **Frontend** — no user-HTML rendering, strict Content-Security-Policy,
  and `frame-ancestors 'none'`.

These controls are exercised by the backend test suite (including a
security-audit regression suite) and by the CI pipeline.
