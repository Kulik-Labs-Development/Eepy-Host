# 🌙 Eepy Host ✨

**Powerful infrastructure, wrapped in a soft blanket of simplicity.**  
*The ultimate playground for the Vibe Coder.*

---

<div align="center">

![Void & Neon](https://github.com/Kulik-Labs-Development/Eepy-Host/blob/main/eepy-host/glossy-zzz.png?raw=true)

**Cyber-cozy hosting made for MCP servers.**  
*Deep voids. Soft glows. Zero friction.*

</div>

---

## 🌌 The Vision

Eepy Host (`eepy.host`) is a specialized hosting platform designed specifically for **Model Context Protocol (MCP) servers**. 

We're building the "**playground for the Vibe Coder**"—a space where developers can host and manage their MCP servers without the friction of traditional cloud infrastructure. Our philosophy? **"Cyber-Cozy"**: high-tech, high-performance engine wrapped in an interface that feels calm, focused, and aesthetic (think: deep voids, soft neon glows, and zero visual noise).

Pair it with self-hosted LLM interfaces like Open WebUI for a **fully private AI stack**. 🔒

---

## ✨ What's Live Now 🚀

### Authentication & Accounts
- [x] **Unified Auth Portal** — Single `/auth` endpoint handling login/signup with dynamic mode-switching
- [x] **"Vibe Sync" Confirmations** — Smooth signup flow with instant account creation feedback
- [x] **JWT-based Security** — `python-jose` powered authentication with strict role hierarchy:

| Role | Access Level |
|------|-------------|
| 🟢 `USER` | Manage your own servers & profile |
| 🔵 `SUPERUSER` | Full "God Mode" visibility, user management, organization oversight |

### The Dashboard Experience ☁️
- [x] **MCP Server Management** — Deploy and configure MCP servers with ease
- [x] **Account Profile Hub** — Identity management + avatar customization (Base64 Data URIs stored directly in Postgres 🗄️)
- [x] **The Void Console** ⚡ RAM-based circular buffer for real-time system observability — watch your stack breathe live
- [x] **Organization Hub** 🔐 Superuser-only control panel: user directory, role escalation/delegation, account purging

### Design Philosophy 🎨
- **"Void & Neon" Aesthetic**: Deep space backgrounds (`bg-void`), soft neon glows on interaction
- **Accent Palette with Purpose**:
  - 💜 `eepy-lavender`: Primary actions (deployments, confirmations)
  - 🍑 `eepy-peach`: Warnings, syncing states, attention triggers  
  - 🌿 `eepy-mint`: Success states, health indicators, "all systems go" vibes
- **Console Feel**: Utility classes for monospace rendering throughout the UI

---

## 🔧 Technical Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| **Frontend** | Next.js (App Router) + Tailwind CSS | React components with `lucide-react` icons, custom void color utilities |
| **Backend** | FastAPI (Python 3.12+) | Async-ready endpoints serving MCP server logic |
| **Database** | PostgreSQL | ORM via SQLAlchemy, Base64 avatars stored directly in DB (no S3 dependency) |
| **Auth** | JWT (`python-jose`) + bcrypt hashing | Strict RBAC enforced at API layer |
| **Deployment** | Docker Compose → Portainer/GHCR | Multi-stage builds optimized for lightweight containers |

---

## 🚀 Quick Start via Docker

```bash
# Spin up the stack in one command (all ports configured out-of-the-box)
docker compose pull && docker compose up -d
```

**Access Points:**
- Frontend: `http://localhost:3000` 💜 (The Void UI opens with soft neon glow)
- Backend API: `http://localhost:8000/openapi.json` 📊 (Swagger docs live here by default)
- Database: PostgreSQL on port 5432 inside the network bridge

> ℹ️ Default credentials in `docker-compose.yml` — **change them for production!**  
> Backend expects `DATABASE_URL`, `SECRET_KEY`. Frontend reads `NEXT_PUBLIC_API_URL`.

---

## 🗺️ Roadmap & Current Focus

### ✅ Phase 1: Core Infrastructure (Complete)
- [x] Multi-stage Docker builds optimized for both frontend/backend
- [x] CI/CD pipeline via GitHub Actions → GHCR registry automation
- [x] "Void & Cozy" Design System locked in with Tailwind utilities
- [x] Base networking and service interconnectivity verified

### ✅ Phase 2: The Auth Shell (Complete)  
- [x] PostgreSQL user/schema creation + migrations baked into image build
- [x] JWT authentication logic (`python-jose`) with bcrypt verification bytes truncation for storage efficiency
- [x] RBAC middleware enforced at every `/superuser/*` route level ✅ frontend components conditionally rendered via `AuthContext.user.role` checks
- [x] High-vibe Login/Signup screens + password visibility toggles

### 🌙 Phase 3: Management & Oversight (🔥 LIVE NOW)  
> *This is where we are right now — superpowers unlocked.*

- [x] **Superuser Dashboard** — Full visibility across all accounts, role management tools
- [x] **Admin User Directory** — Browse, search, and manage users from one console
- [x] **Role Escalation Workflows** — Promote/demote USER → SUPERUSER with permission inheritance tracking  
- [x] **Account Purging System** — Delete accounts + cascade-remove associated resources (MCP servers, configs)

### 🧪 Phase 4: MCP Configuration Engine (In Progress)
- [ ] Pre-programmed server library (starter pack of popular MCP adapters)
- [ ] User settings input forms for API tokens/secrets storage  
- [ ] Dummy/placeholder server integration for UI testing without external dependencies
- [ ] Server health monitoring dashboards

### 💎 Future Dreams ✨
- Real-time metrics graphs in The Void Console
- Webhook integrations (Discord, Slack) for deployment notifications
- Marketplace of shareable MCP configurations
- Terraform provider for Eepy Host infrastructure provisioning

---

## ⚠️ Developer Nuances & "Gotchas" 

**New to the codebase? Read this first.** These are hard-learned lessons that will save hours:

### 1. The Absolute Import Rule (Backend) 🔥
> **CRITICAL:** Never use relative imports (`from .module import ...`) inside `backend/main.py`.  
> 
> **Why:** Uvicorn launches the app as a top-level script → Python throws `ImportError: attempted relative import with no known parent package`.  
> **The Fix:** Always go absolute. Example:
```python
# ✅ GOOD (works)
from models.user import User

# ❌ BAD (will crash on deploy)
from .models.user import User
```

### 2. The JSX Syntax Fragility 🚨
When using automated tools or shell scripts to rewrite `.tsx` files, there's a risk of introducing escaping artifacts (`\n`, `\"`) that break builds immediately.  
> **The Protocol:** Use quoted heredocs for file writes and always run post-write verification checks before committing anything near JSX blocks!

### 3. Role Hierarchy Enforcement 🛡️
Every `/superuser/*` endpoint has middleware checking JWT payload roles — frontend components are wrapped in `AuthContext.user.role === 'SUPERUSER'` conditionals, but **backend is the source of truth**. Never trust client-side only for access control!

### 4. The Aesthetic Standard 🎨  
This isn't just a tool — it's *a vibe*. When adding UI:
- No harsh whites or generic grays → reach for `void-surface` and `void-border` utilities
- Lavender = primary actions (deploy, create) | Peach = warnings/syncing states | Mint = success/health 
- Maintain the "console" aesthetic with utility font classes (`font-console`)

---

## 🤝 Contributing & Development Workflow

We move fast on this stack:  
1. **Feature Request → Implementation:** Rapid prototype UI first, then wire up backend API
2. **Direct Main-Branching:** All work happens on `main` for maximum visibility and speed (no feature branches just yet)
3. **Verification Cycle:** Every major change goes through `read_file → write_file → grep/test` pattern to ensure we didn't break anything critical

Want to join the cult? Drop a PR or message us in repo issues! 🔥

---

<div align="center">

*Stay cozy, keep deploying.* 🌙  
Made with 💜 by **Kulik Labs Development**

</div>

### Quick Links
- [GitHub Repo](https://github.com/Kulik-Labs-Development/Eepy-Host)
- [API Docs (Swagger)](http://localhost:8000/openapi.json) *once running*  
- The Void Console — `dashboard/void-console` route when deployed 🔮

---