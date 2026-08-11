Eepy Host - Compact System Context (Phase 4+)

PROJECT: Eepy Host at https://github.com/Kulik-Labs-Development/Eepy-Host  
STATUS: Phase 4 MCP Integration Hub in progress; backend foundation complete. Immediate next steps begin after context summary creation and push confirmation.  

CORE VISION: A managed SaaS MCP gateway — NOT a container orchestration platform. Users connect integrations (Google Calendar, Slack Workspaces, Notion Databases); we handle API plumbing, credential management (encrypted at rest), unified proxy routing (/api/mcp/proxy/{template_id}/*) so their agent uses external tools securely without operational overhead.  

KEY ARCHITECTURE DECISIONS:  
- Single backend endpoint per integration; no user containers or container sprawl!  
- Credentials encrypted in PostgreSQL via Fernet symmetric encryption (master key from env); decrypted only temporarily inside request handlers - NEVER persisted to disk/logs  
- Admin approval required before any template appears in library → monetization pipeline starts here  

TECHNICAL STACK: Next.js frontend (Tailwind, Void & Neon aesthetic with eepy-lavender/eepy-peach/eepy-mint accents), FastAPI backend (PostgreSQL via SQLAlchemy + Fernet crypto), JWT authentication (python-jose) with strict USER/SUPERUSER role hierarchy. Frontend uses Lucide React icons; UI follows "console feel" convention.  

CURRENT STATE: Unified auth portal, dashboard hub (profile management, void console observability, organization admin tools for superusers). Backend foundation ready (models/mcp_models.py, utils/crypto.py, alembic migration structure committed to main at commit 5c96397). HappyFox template integration defined in Phase4 plan as first production-ready example.  

CRITICAL DEVELOPER NUANCES:  
1) Absolute import rule NEVER use relative imports inside backend/main.py (Uvicorn runs it top-level → ImportError otherwise) ALWAYS go absolute!
2) JSX syntax fragility When rewriting .tsx files via automated tools, escaping artifacts break builds immediately USE quoted HEREDOCs + post-write verification checks
3) Credential security ALL MCP credentials encrypted at rest; decryption happens only in memory during handler execution — no logs/disk writes ever. SECURITY CRITICAL 🔐  
4) Role hierarchy enforcement Every /superuser/* endpoint has middleware checking JWT roles; frontend components wrap with AuthContext.user.role === SUPERUSER but backend is source of truth - never trust client-side for access control!  

WORKFLOW PREFERENCE: Direct main-branching (no feature branches yet); rapid prototyping → implementation verification cycle. Communication style professional/factual, minimize emoji usage in documentation unless aesthetic requirement validated by code review first.  