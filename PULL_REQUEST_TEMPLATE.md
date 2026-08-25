## What

<!-- One or two sentences: what does this PR change, and why? Link the issue it fixes, if any. -->

## Type

- [ ] Backend (API / proxy / sidecar bridge)
- [ ] Frontend (dashboard UI)
- [ ] New or updated integration (submodule bump / new template)
- [ ] Deploy / CI
- [ ] Docs
- [ ] Security

## Changes

<!-- Bulleted list of the meaningful changes. -->

## Testing

- [ ] Backend: `ruff check .` and `pytest tests/ -q` pass
- [ ] Frontend: `npm run lint` and `npx tsc --noEmit` pass (if touched)
- [ ] Verified end-to-end: a live call through the proxy (or the dashboard connection test) returns upstream data

## Notes

- UI changes follow the **Retro Cozy** design system (existing tokens and
  component classes in `tailwind.config.js` + `globals.css`); attach
  screenshots for significant visual changes.
- If this changes the architecture, endpoints, env vars, or a documented
  convention, **README.md and AGENTS.md are updated in this PR**.
- **No credentials, keys, or secrets** in the diff, in logs, or in test
  fixtures — credential handling stays on the approved path (Fernet at rest,
  in-memory decryption only).

> Security: do not open a pull request that discloses a vulnerability —
> follow [SECURITY.md](SECURITY.md) and report privately.
