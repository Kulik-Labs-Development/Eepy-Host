# 🌙 Eepy Host ✨

**The managed MCP gateway.**  
*A unified, cyber-cozy platform connecting AI agents to external tools and services.*

---

<div align="center">

![Void & Neon](https://github.com/Kulik-Labs-Development/Eepy-host/blob/main/glossy-zzz.png?raw=true)

*Deep voids. Soft glows. Zero container sprawl.*  
*MCP servers managed centrally, credentials encrypted end-to-end.*

</div>

---

## 🌐 The Vision: A SaaS MCP Bridge (Not Container Orchestration) ❌🔥✅

Eepy Host (`eepy.host`) is **NOT** a place to self-host multiple Docker containers. It's not infrastructure for "running your own MCP servers."

Instead, it's the **all-in-one managed integration layer** between LLM agents and real-world tools: Google Calendar, Slack Workspaces, Notion Databases, File Systems, Web Browsing APIs — all connected via a single backend proxy API that handles authentication securely in one place.

### How It Works (High Level) 📊
```
User Agent / OpenWebUI → Eepy Host (/api/mcp/proxy/*) → External Services
                           │
                    ┌──────┴───────┐
                    ▼              ▼
               Credentials DB  Template Registry ✅ approved by admin only
```

**The User Experience:** They don't deploy containers. They **"connect integrations"** — we handle the API plumbing, credential management (encrypted at rest), and unified proxy routing so their agent can actually use external tools securely. 🤝

---

## ✨ What's Live Now 🔥

### Authentication & Accounts
- [x] **Unified Auth Portal** — Single `/auth` endpoint handling login/signup with dynamic mode-switching
- [x] **"Vibe Sync" Confirmations** — Smooth signup flow with instant account creation feedback  
- [x] **JWT-based Security** — `python-jose` powered authentication with strict role hierarchy:

| Role | Access Level |
|------|-------------|
| 🟢 `USER` | Manage your own integrations, request new templates ✅ |
| 🔵 `SUPERUSER` | Admin gateway: approve requests, manage global template library ✅ MONETIZATION READY |

### The Dashboard Experience ☁️
- [x] **Account Profile Hub** — Identity management + avatar customization (Base64 Data URIs stored directly in Postgres 🗄️)
- [x] **The Void Console** ⚡ RAM-based circular buffer for real-time system observability — watch your stack breathe live  
- [x] **Organization Hub** 🔐 Superuser-only control panel: user directory, role escalation/delegation, account purging

### Design Philosophy 🎨
- **"Void & Neon" Aesthetic**: Deep space backgrounds (`bg-void`), soft neon glows on interaction
- **Accent Palette with Purpose**:
  - 💜 `eepy-lavender`: Primary actions (connections, confirmations)  
  - 🍑 `eepy-peach`: Warnings, syncing states, attention triggers  
  - 🌿 `eepy-mint`: Success states, health indicators

---

## 🔧 Technical Stack

| Layer | Technology | Notes for Architecture-Clarity ✅ |
|-------|------------|----------------------------------|
| **Frontend** | Next.js (App Router) + Tailwind CSS | React components with lucide-react icons, void color utilities only |
| **Backend** | FastAPI (Python 3.12+) | Single unified API endpoint `/api/mcp/proxy/*` routing all integrations |
| **Database** | PostgreSQL | ORM via SQLAlchemy, Base64 avatars + encrypted credentials in DB 🗄️ 🔐 |
| **Auth & Security** | JWT (`python-jose`) + bcrypt hashing + Fernet encryption (for MCP creds) | Strict RBAC enforced at API layer — frontend components conditionally rendered ✅ |
| **Deployment** | Docker Compose → Portainer/GHCR | Single unified backend deployment per instance, no container sprawl! 🚀 |

---

## 🎯 Phase 4: MCP Integration Hub (In Progress) 🔐🔥

> *Where we are right now — building the gateway.*
> 
> **NOT** user-deployable containers. This is a managed service where templates = integrations approved by admins, credentials encrypted in DB, and all API calls flow through one proxy endpoint 📡

### Status Overview:

| Feature | Priority | Notes |
|---------|----------|-------|
| MCP Template Library (Admin Approved) | 🔴 HIGH | 5-7 starter templates ready at launch ✅ monetization path open |
| Connection Wizard UI | 🔴 HIGH | Users "connect" integrations → save encrypted credentials in DB |
| Proxy Endpoint (`/api/mcp/proxy/*`) | 🟡 MEDIUM | Loads decrypted creds temporarily, routes request to external API ⚠️ SECURITY CRITICAL |
| Template Request Workflow | 🟢 LATER | User-requested integration → admin approval queue = monetization pipeline ✅ |

### Starter Templates Planned (First 3-5):
1. **Google Calendar** — Query events & manage time blocks  
2. **Slack Workspace Adapter** — Send/receive messages from connected workspace  
3. **Local File Browser** — Read/write files securely via agent → file system integration ⚠️ PRIVACY FOCUSED

---

## 🗺️ Full Roadmap (Aligned With SaaS Vision)

### ✅ Phase 1: Core Infrastructure
- [x] Multi-stage Docker builds optimized for unified backend image  
- [x] CI/CD pipeline via GitHub Actions → GHCR registry automation  
- [x] "Void & Cozy" Design System locked in with Tailwind utilities (bg-void, eepy-lavender variants)  
- [x] Base networking and service interconnectivity verified

### ✅ Phase 2: The Auth Shell
- [x] PostgreSQL user/schema creation + migrations baked into image build  
- [x] JWT authentication logic (`python-jose`) with bcrypt verification bytes truncation for storage efficiency  
- [x] RBAC middleware enforced at every `/superuser/*` route level — frontend components conditionally rendered via `AuthContext.user.role === 'SUPERUSER'` checks ✅  
- [x] High-vibe Login/Signup screens + password visibility toggles

### 🌙 Phase 3: Management & Oversight (🔥 LIVE NOW)
> *This is where we are right now — superpowers unlocked.*

- [x] **Superuser Dashboard** — Full visibility across all accounts, template management tools  
- [x] **Admin User Directory** — Browse, search, and manage users from one console ⚠️ MONETIZATION PIPELINE STARTS HERE ✅
- [x] **Role Escalation Workflows** — Promote/demote USER → SUPERUSER with permission inheritance tracking (user approval queue)  
- [x] **Account Purging System** — Delete accounts + cascade-remove associated resources (MCP server configs, credentials stored in encrypted JSONB columns 🗄️ 🔐)

### 💎 Phase 5: Monetization Hooks (+Future Features ✨)
> *The path to revenue when ready.*

- [ ] Template **pricing tiers** per-template configuration for admins ✅ FREE vs PREMIUM toggle  
- [ ] Usage analytics dashboard (track `last_used_at`, API call volume, integration health scores 📊) = premium tier justification  
- [ ] Stripe webhook integration for subscription billing (if/when you enable paid templates/pricing models later)

---

## ⚠️ Developer Nuances & "Gotchas" 

**New to the codebase? Read this first.** These are hard-learned lessons that will save hours:

### 1. The Absolute Import Rule (Backend) 🔥
> **CRITICAL:** Never use relative imports (`from .module import ...`) inside `backend/main.py`.  
> 
> Uvicorn launches the app as a top-level script → Python throws `ImportError: attempted relative import with no known parent package`.  
> 
> ✅ Always go absolute. Example:
```python
# GOOD (works)
from models.user import User

# BAD (will crash on deploy)  
from .models.user import User
```

### 2. The JSX Syntax Fragility 🚨
When using automated tools or shell scripts to rewrite `.tsx` files, there's a risk of introducing escaping artifacts (`\n`, `\"`) that break builds immediately.  

> **The Protocol:** Use quoted heredocs for file writes and always run post-write verification checks before committing anything near JSX blocks!

### 3. MCP Credential Security ⚠️ 🔐 CRITICAL  
All user credentials stored in PostgreSQL are **encrypted at rest** using Fernet symmetric encryption (single master key from env variable `MCP_ENCRYPTION_KEY`). Decryption only happens temporarily inside request handlers — never persisted to disk or logs!

⏺️ If you modify credential storage logic, verify these security controls first. No exceptions allowed on this stack 🔒

### 4. Role Hierarchy Enforcement 🛡️  
Every `/superuser/*` endpoint has middleware checking JWT payload roles — frontend components are wrapped in `AuthContext.user.role === 'SUPERUSER'` conditionals but **backend is the source of truth**. Never trust client-side only for access control! ✅

### 5. The MCP Proxy Is Single-Source-of-Truth For All Integrations 📡  
There's no containerization per integration anymore. If you want to add a new external service:
1. Add it as `MCPTemplate` in the library (admin approved only) 
2. Configure its config_schema form fields (API key? OAuth URL?)  
3. Implement proxy routing logic under `/api/mcp/proxy/{template_id}/...`

---

## 🤝 Contributing & Development Workflow

We move fast on this stack:
1. **Feature Request → Implementation:** Rapid prototype UI first, then wire up backend API
2. **Direct Main-Branching:** All work happens on `main` for maximum visibility and speed (no feature branches just yet)  
3. **Verification Cycle:** Every major change goes through `read_file → write_file → grep/test` pattern to ensure we didn't break anything critical

Want to join the cult? Drop a PR or message us in repo issues! 🔥🌙

---

<div align="center">

*Stay cozy, keep connecting.* 🌙  
Made with 💜 by **Kulik Labs Development**

</div>

### Quick Links
- [GitHub Repo](https://github.com/Kulik-Labs-Development/Eepy-Host)
- API Docs (Swagger): `http://localhost:8000/openapi.json` *once running*  
The Void Console — dashboard/void-console route when deployed 🔮

---

## 📌 Architecture Summary: Why This Design Wins? ✅🚀

| Aspect | Traditional "Self Host MCP Servers" ❌ | Eepy Host Approach ✅ |
|--------|-------------------------------------|----------------------|
| User Complexity | Deploy Docker containers → manage networking, credentials per-container | Single backend API — no container sprawl ⭐ |
| Resource Usage | One container *per* integration × number of users = massive overhead | Unified proxy with encrypted credential cache (memory-only) 🎯 |
| Security Model | Credentials spread across multiple container environments | Centralized encryption at rest in PostgreSQL + temporary decryption only ✅ 🔐 |
| Monetization Potential | Hard to charge for "hosting" alone | Template approvals, premium tiers, usage analytics = recurring revenue model 💰🤑 |

---
