# 🌙 Eepy Host: Project Blueprint & System Guide

**Project Repository:** https://github.com/Kulik-Labs-Development/Eepy-Host

---

## 🔐 Max's Github PAT (DEVELOPMENT ONLY - NEVER EXPOSE TO REPO)

⚠️ **CRITICAL SECURITY RULE**: This token is for Portainer GitOps operations only. Never write this into any project file or README that gets committed!
- User: `Glitch3dPenguinPersonal`  
- Access Token: (stored in local env / secret manager, never exposed)

---

## 🌐 The Vision: A SaaS MCP Gateway (NOT Container Orchestration) 🔥❌🚀

**Eepy Host** (`eepy.host`) is **not** a self-hosted platform for users to deploy multiple Docker containers. 

Instead, it's the **all-in-one managed integration layer** between LLM agents and real-world tools: Google Calendar, Slack Workspaces, Notion Databases, File Systems, Web Browsing APIs — all connected via a single backend proxy API that handles authentication securely in one place.

### Core Architecture Principle
```
User Agent / OpenWebUI → Eepy Host (/api/mcp/proxy/*) → External Services
                           │
                    ┌──────┴───────┐
                    ▼              ▼
               Encrypted Creds  Admin-Approved 
             in Postgres DB    Template Library ✅
```

**The User Experience:** They don't deploy containers. Users **"connect integrations"** — we handle API plumbing, credential management (encrypted at rest), and unified proxy routing so their agent can use external tools securely without operational overhead. 🤝

### Cyber-Cozy Philosophy
- Deep void backgrounds with soft neon glows on interaction 💜🍑🌿  
- Zero container sprawl = single backend image per deployment  
- Privacy-first credential storage (encrypted at rest, decrypted in-memory only) 🔐  

---

## 🛠️ Technical Stack & Architecture Notes

### Frontend (The Interface - Next.js App Router + Tailwind CSS)
| Feature | Implementation Details |
|---------|----------------------|
| **Routing** | `/auth`, `/mcp/library`, `/dashboard/void-console`, superuser paths (`/superuser/*`) all use App Router file-based routing |
| **Styling** | Custom void color palette utilities: `bg-void` (deep space), text variants with soft glows on hover states using Tailwind arbitrary values and custom config colors |
| **Icons** | Lucide React for consistent visual language — no emoji-heavy icons, clean monochrome with accent fill variants |

### Backend (The Engine - FastAPI + SQLAlchemy)
| Feature | Implementation Details ✅ Current State |
|---------|----------------------------------------|
| **Architecture Pattern** | Single unified backend image. All MCP integrations handled via centralized proxy endpoint `/api/mcp/proxy/{template_id}/...` — NOT per-container orchestration! 📡🔥 |
| **Database** | PostgreSQL managed via SQLAlchemy ORM + Alembic migrations for schema updates |
| **Auth System** | JWT (JSON Web Tokens) using `python-jose`. Strict role hierarchy enforced at API middleware level: USER → SUPERUSER. All `/superuser/*` endpoints return 403 without proper JWT token verification ✅ 🔐 |
| **Credentials Storage** | User MCP credentials stored as encrypted JSONB columns in PostgreSQL (`credentials_json`) using Fernet symmetric encryption with single master key from `MCP_ENCRYPTION_KEY` env var ⚠️ CRITICAL: never persist plaintext to disk or logs! |

### Deployment Strategy (Docker Compose → Portainer/GHCR)
- Single unified backend image built via multi-stage Docker builds ✅ 
- Frontend + backend both containerized but deployed as separate services in one network (`eepy-network`) 🚀
- **NO per-user server containers** — we don't run 10s of MCP instance pods. The proxy handles everything centrally.

---

## 🚀 Current Implementation State (What's Live NOW) 🔥🌙

### ✅ Phase 1: Core Infrastructure (Complete)
| Feature | Status Notes |
|---------|-------------|
| Multi-stage Docker builds | Built and verified for both frontend/backend images ✅ |
| CI/CD pipeline via GitHub Actions → GHCR registry automation | Fully operational, new commits auto-build & push 🚀 |
| "Void & Cozy" Design System locked in with Tailwind utilities (bg-void, eepy-lavender variants) | All core components use these utility classes ✅🎨 |
| Base networking and service interconnectivity verified | DB ↔ backend → frontend all communicate successfully on `eepy-network` ✅ |

### ✅ Phase 2: The Auth Shell (Complete)  
| Feature | Status Notes |
|---------|-------------|
| PostgreSQL user/schema creation + migrations baked into image build | Alembic auto-runs at startup, schema initialized automatically ✅🗄️ |
| JWT authentication logic (`python-jose`) with bcrypt verification bytes truncation for storage efficiency | Passwords hashed once on signup; session tokens verified via algorithm HS256 ✅ |
| RBAC middleware enforced at every `/superuser/*` route level — frontend components conditionally rendered via `AuthContext.user.role === 'SUPERUSER'` checks | Access control is dual-layered: backend rejects unauthorized requests; UI hides super-user-only content client-side ⚠️ never trust only the frontend! 🔐 |
| High-vibe Login/Signup screens + password visibility toggles | Unified `/auth` endpoint handles both modes with smooth dynamic switching and instant "vibe sync" confirmations ✅💜🍑🌿 |

### 🌙 Phase 3: Management & Oversight (LIVE NOW) 🔥⚡
| Feature | Status Notes |
|---------|-------------|
| **Superuser Dashboard** — Full visibility across all accounts, template management tools | Admin can see every user's MCP configs without accessing their credentials directly ✅📊 |
| **Admin User Directory** — Browse, search, manage users from one console ⚠️ MONETIZATION PIPELINE STARTS HERE | User directory supports filtering by role/status + bulk actions for admins 🤝💰 |
| **Role Escalation Workflows** — Promote/demote USER → SUPERUSER with permission inheritance tracking (user approval queue) | Superusers can escalate any user but must document why in admin notes field ⚠️ always track changes ✅ |
| **Account Purging System** — Delete accounts + cascade-remove associated resources (MCP server configs, credentials stored in encrypted JSONB columns 🗄️ 🔐) | Account deletion permanently removes all data from DB including credential blobs; no soft deletes for security compliance ❌🔒 |

### 💎 Phase 4: MCP Integration Hub (IN PROGRESS - BUILDING NOW) 🔥⚙️
| Feature | Priority | Notes on Architecture ✅ Current Plan |
|---------|----------|------------------------------------|
| MCP Template Library (Admin Approved Only) | 🔴 HIGH | Pre-populated database with 5-7 starter templates for launch. Users can't self-add custom servers — this is the monetization gate! ✅💰 |
| Connection Wizard UI (`/mcp/library` → config form save encrypted creds to DB per user) | 🔴 HIGH | Users "connect" integrations instead of deploying containers: pick template + fill credential schema = saved encrypted JSONB field in `user_mcp_configs` table ⚙️🗄️ |
| Proxy Endpoint (`/api/mcp/proxy/{template_id}/...`) Loads decrypted creds temporarily, routes request to external API ⚠️ SECURITY CRITICAL 📡 | 🟡 MEDIUM | Single unified route that reads encrypted credentials from Postgres → decrypts in memory during handler execution only → proxies authenticated call out to service (GCal, Slack, Notion) → streams response back. No tokens persisted anywhere after request completes ✅🔐⚠️ SECURITY FIRST! |
| Template Request Workflow (user-requested integration → admin approval queue = monetization pipeline ✅) | 🟢 LATER | Users submit form for new template add to library. Admins approve/reject + optionally charge for custom implementation work ⏳💰📋 |

**Starter Templates Planned (First 3-5):**
1. **Google Calendar** — Query events & manage time blocks via OAuth2 token stored in DB ✅ 
2. **Slack Workspace Adapter** — Send/receive messages from connected workspace using bot tokens 🔐  
3. **Local File Browser** — Read/write files securely via agent → file system integration ⚠️ PRIVACY FOCUSED

---

## 🗺️ Full Roadmap (Aligned With SaaS Vision & Monetization Path) ✅🤑

### 💎 Phase 5: Monetization Hooks (+Future Features ✨)
> *The path to revenue when we're ready.*

| Feature | Goal Notes | Priority Level 🔴/🟡/🟢 | Status |
|---------|-----------|------------------------|--------|
| Template **pricing tiers** per-template configuration for admins ✅ FREE vs PREMIUM toggle | Admins can set `price_tier: 'FREE'` or `'PREMIUM'` on MCPTemplate models. Free tier = basic integrations, premium = advanced features (rate limiting bypassed) + analytics 📊 | 🔴 HIGH (when ready to monetize) | ⏳ Not Started Yet - Planning Now ✅🤑💰 |
| Usage analytics dashboard (track `last_used_at`, API call volume, integration health scores 📈) = premium tier justification | Every MCP config tracks last-used timestamp + request count per user. Admin panel will show usage heatmaps for billing decisions 💳✅🚨 | 🔴 HIGH when monetization begins ⏳💰🤑 |
| Stripe webhook integration for subscription billing (if/when you enable paid templates/pricing models later) | If we charge premium tier access or custom template requests → integrate payment gateway. For now, all free while building trust with user base ✅⚠️ NOT IMPLEMENTED YET ⏳📦💸 | 🟢 FUTURE PLANNING - Wait for Phase 4 MVP stabilization first ✅✅🔥

---

## 🔐 MCP Security & Credential Handling (CRITICAL ARCHITECTURE RULE) ⚠️🔒🔑

### ALL user credentials stored in PostgreSQL must follow these rules:
1. **Encrypted at rest** using Fernet symmetric encryption (`MCP_ENCRYPTION_KEY` from env var). No plaintext ever written to disk! 🔐⚡❌
2. Decryption happens ONLY temporarily inside request handlers — never persists anywhere else, not even logs 📋🔒  
3. If modifying credential storage logic → verify these security controls FIRST before committing anything related to MCP config handling ✅✅

> **WARNING:** This is the single most critical system-wide constraint on this stack. No exceptions allowed! 🔥❌🚨⏺️

---

## ⚙️ Development Workflow (How We Move Here) 🚀💜

We move fast but never break what works:
1. **Feature Request → Implementation:** Rapid prototype UI first, then wire up backend API support ✅  
2. **Direct Main-Branching:** All work happens on `main` for maximum visibility and speed (no feature branches just yet) ⚡💜🔥
3. **Verification Cycle:** Every major change goes through `read_file → write_file → grep/test` pattern to ensure we didn't break anything critical 🔍✅

---

## 🧩 Developer Gotchas & System-Wide Constraints (READ BEFORE CODE!) ⚠️📘❗

### 1. The Absolute Import Rule (Backend) 🔥
> **CRITICAL:** Never use relative imports (`from .module import ...`) inside `backend/main.py`.  
Uvicorn launches the app as a top-level script → Python throws `ImportError: attempted relative import with no known parent package` ❌💀🔒  

✅ The Fix: Always go absolute. Example:
```python
# GOOD (works on deployment ✅)
from models.user import User

# BAD (will crash hard when deployed 🔥❌)  
from .models.user import User  # NEVER do this! ⚠️⛔🚨
```

---

### 2. The JSX Syntax Fragility 📝➡️🐞
When using automated tools or shell scripts to rewrite `.tsx` files, there's a high risk of introducing escaping artifacts (`\n`, `\"`) into the code that immediately break builds on next compile cycle ⚠️💥❌

**The Protocol:** Use quoted heredocs for file writes and always run post-write verification checks before committing anything near JSX blocks:
```bash
# ✅ GOOD - uses cat <<'EOF', no expansion occurs, escaping stays intact
cat > /path/to/file.tsx << 'EOF'
  Your component code here... without escaped \\n or \" characters! 🚀✅
EOF

# ❌ BAD - allows variable interpolation and escape sequences to leak into JSX blocks 😱⛔🐞
```
After every file write, verify no `\n` (literal backslash-n in source) appears inside string literals meant for runtime evaluation ✅ `grep '\\\\n' .tsx | wc -l # should be 0! 🔍✅

---

### 3. Role Hierarchy Enforcement 🛡️🔒
Every `/superuser/*` endpoint has middleware checking JWT payload roles — frontend components are wrapped in `AuthContext.user.role === 'SUPERUSER'` conditionals but **backend is the source of truth**. Never trust client-side only for access control! ✅

⚠️ Double-check: if you bypass a UI check, can an API call still be blocked? Yes → good design. If no, add middleware enforcement to backend routes immediately 🔒✅🛡️💜

---

### 4. The Aesthetic Standard (Cyber-Cozy Design System) 🎨✨
Eepy Host isn't just a tool; it's *a vibe*. When adding new UI:
- ❌ No harsh whites or standard grays → reach for `void-surface` and `void-border` utilities instead ✅🚫⏺️  
💜 **Accent Colors = Intent**:
  - Lavender (`eepy-lavender`) → primary actions (deployments, confirmations, "yes" states)
  - Peach (`eepy-peach`) → warnings/syncing states/attention triggers ⚠️🍑⏳
- ✅ **Mint** = success states, health indicators, all systems go! 🌿✅💚

Maintain the console feel by using `font-console` utility class on any data-display elements that users want to read in monospace for quick scanning/analysis ⌨️📊⚡

---

### 5. The MCP Proxy Is Single-Source-of-Truth For All Integrations 📡💜❗
There's no containerization per integration anymore! If you're adding a new external service to Eepy Host:
1. Add it as `MCPTemplate` in the library (admin approved only — users can't self-add ❌) ✅🔐⚠️  
2. Configure its config_schema form fields (API key? OAuth URL? Secret?) ⏺️✅💜
3. Implement proxy routing logic under `/api/mcp/proxy/{template_id}/...` following encryption-in-DB pattern 📡✅🔒

---

## 🔍 Knowledge Base & Internal Resources ✅🗂️

### Where to Find Information:
| Resource | Location/Notes | How To Access/use ✅ |
|----------|---------------|---------------------|
| **Knowledge Bases** | Query via `query_knowledge_files` and `search_memory_paths` in conversations 🔍💜📁 | Search for files by name or semantic query describing what you're looking for 🤖⚡✅ |

---

## ✅ Developer Notes & Reminders (Read Me First!) ⏺️❗📘

### Before You Push Code:
- [ ] Verify no relative imports exist in `backend/main.py` ✅  
- [ ] Post-write file verification run via grep to ensure escaping didn't leak into JSX blocks 🔍⚠️✅  
- [ ] If modifying MCP credential storage → double-check encryption logic and test decryption flow manually 🗝️🔒💜  
- [ ] All superuser routes have middleware protection ✅ ⏺️❓

---

*Stay cozy, keep connecting.* 🌙💜🚀**
*Made with ❤️ by **Kulik Labs Development***

