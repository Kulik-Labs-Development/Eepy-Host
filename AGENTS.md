Eepy Host - System Blueprint and Agent Instructions

## Project Overview

Eepy Host is a SaaS MCP gateway platform designed specifically for Model Context Protocol servers. It provides an all-in-one managed integration layer between LLM agents and real-world tools including Google Calendar, Slack Workspaces, Notion Databases, File Systems, and Web Browsing APIs connected via a single backend proxy API that handles authentication securely in one place.

Core Architecture Principle: Users do not deploy containers; they connect integrations - we handle API plumbing, credential management (encrypted at rest), and unified proxy routing so their agent can use external tools without operational overhead.

## Setup Commands

### Prerequisites
```bash
python 3.12+ required for backend development
Node.js 18+ recommended for frontend work
PostgreSQL 15+ running locally or via Docker container
```

### Backend Development
```bash
cd /home/user/eepy-host/backend  
pip install -r requirements.txt pipenv pytest python-dotenv sqlalchemy asyncpg uvicorn fastapi python-jose[cryptography] cryptography alembic pydantic==2.0.* 
DATABASE_URL="postgresql://eepy_admin:[ROTATED_POSTGRES_PASSWORD]@db:5432/eepy_host" MCP_ENCRYPTION_KEY=your-actual-secret-key-here-change-in-production-blahblah== python run_migrations.py  
uvicorn main:app --reload --host 0.0.0.0 --port 8000
curl http://localhost:8000/health  
```

### Frontend Development
```bash
cd /home/user/eepy-host/frontend 
pnpm install
pnpm dev
pnpm build && pnpm start
```

### Docker Deployment Commands
```bash 
docker compose up --build -d  
docker-compose ps   
docker logs backend-app -f      
```

## Code Style Guidelines

### Backend (Python/FastAPI)
1. **Absolute Import Rule CRITICAL:** Never use relative imports in `backend/main.py` due to Uvicorn running as top-level script. Use absolute imports instead.
2. Pydantic models should inherit from BaseModel with type hints and validation rules.
3. Wrap DB operations in try/except + return standardized HTTPException responses via middleware layer.
4. MCP credentials encrypted at rest via Fernet symmetric encryption; decrypted only temporarily inside request handlers - never persisted anywhere else, not even logs!

### Frontend (TypeScript/Next.js App Router)  
1. Component naming uses PascalCase convention  
2. Tailwind utility classes: no arbitrary CSS values unless absolutely necessary
3. Lucide React icons only for visual elements  

## Testing Instructions
```bash  
cd /home/user/eepy-host/backend 
pytest tests/ --cov=. -v || echo "Tests failed"   
pnpm test
pnpm vitest run --reporter=verbose && pnpm lint    
```

Integration Checklist: Verify no relative imports, post-write grep checks for escaping issues, encryption logic unit tests.  

## Phase 4 Implementation Plan

### HappyFox Template Integration  
**Repository:** https://github.com/Glitch3dPenguin/happyfox-mcp 

Architecture Principles:
- Single unified backend handling all MCP integrations via `/proxy/{template_id}/*` routes 
- Credentials stored as Fernet-encrypted JSONB columns in PostgreSQL, decrypted only temporarily during request handlers  
- Admin approval required before users can connect any template (monetization gate)

### Database Schema Changes Needed  

Files to Create:
1. `backend/models/mcp_models.py` - MCPTemplate, UserMCPServerConfig, MCPTemplateRequest tables
2. Alembic migration script for new tables + foreign key constraints  

Table Definitions:  
```python 
class MCPTemplate(Base):
    __tablename__ = 'mcp_templates'
    id (PK), name, description, config_schema(JSON)  
    approved_by_admin(bool), enabled_global(bool)

class UserMCPServerConfig(Base):
    __tablename__ = 'user_mcp_configs'   
    id(PK), owner_id(ForeignKey(User.id)), template_name, credentials_json(ENCRYPTED JSONB)  

class MCPTemplateRequest(Base):  
    __tablename__ = 'mcp_template_requests'    
    id(PK), requester_id(ForeignKey(User.id)), requested_name, description_purpose(TEXT), status(Enum:pending|approved|rejected) 
```

### Backend Endpoints To Implement  
Files to Create:`backend/api/mcp_endpoints.py` 

Endpoints include listing templates (GET /api/mcp/templates/list), registering credentials with encryption (POST `/api/mcp/config/register`, deleting configs, submitting new requests for admin approval. Core proxy endpoint: `/api/mcp/proxy/happyfox/{tool_name}/{rest_of_path}` handles decrypted credential lookups in memory only during request execution - NEVER TO DISK/LOGS!  

### Frontend Components To Build  
Files to Create:
1. `frontend/src/app/mcp/library/page.tsx`  (template grid view) 
2. `frontend/src/components/MCPConnectionWizard.tsx` reusable component for credential entry form based on config_schema from backend API

Page Routes: `/mcp/library`, `/mcp/connect/happyfox` 

### Backend Security & Credential Encryption Strategy  
Files to Create:`backend/utils/crypto.py` with Fernet encrypt/decrypt functions. CRITICAL: all user MCP credentials encrypted at rest using single master key from env var; decrypted only temporarily inside request handlers - never persisted anywhere else, not even logs!

Security Checklist Before Launch:
- Verify encryption at rest (no plaintext in DB)  
- Decryption happens only in memory during handler execution -> NO disk writes or log output ever! 
All MCP tool responses sanitized for context safety? Yes. User confirmation required before write operations per HappyFox spec requirement? YES.  

### Admin Approval Workflow Endpoints
Files to Create:`backend/api/superuser/mcp_admin.py`  
POST `/api/superuser/templates/approve/{id}` - Approve user-requested template -> add to library, enable for all users (SUPERUSER role only) 
DELETE `/superuser/request/reject/{id}/notes`- Reject request with optional admin notes sent back  

### Implementation Sequence

Phase 4a Week 1: Database schema + migration files
- [ ] Create `backend/models/mcp_models.py` file  
[ ] Generate Alembic migration script via autogenerate flag 
[ ] Run migration on dev environment and verify schema is correctly created in PostgreSQL (check DB manually or use psql)  

Phase 4a Week2: Backend endpoints + crypto utils
- [ ] Create `backend/utils/crypto.py` with Fernet encryption/decryption helper functions  
IMPLEMENT GET `/api/mcp/templates/list`, POST `/api/mcp/config/register`, DELETE route and other CRUD operations on UserMCPServerConfig via owner_id FK checks  

Phase 4a Week3: Frontend library page + connection wizard UI
- [ ] Create frontend page `/mcp/library` showing template cards in grid layout (HappyFox appears first)  
[ ] Implement reusable MCPConnectionWizard component accepting config_schema from backend and dynamically building form fields based on field types (string vs password input toggle for credential visibility!)

Phase 4a Week4: HappyFox proxy endpoint logic + security testing
- [ ] Implement proxy endpoint routing under `/api/mcp/proxy/happyfox/{tool_name}`  
[ ] Test via manual curl requests with mocked decrypted credentials in memory (DO NOT use production API keys yet!)  

### Testing & Deployment Checklist

Before enabling HappyFox template for all users: 
Verify encryption at rest, test proxy endpoint with mocked data -> ensure no logs leak decrypted API keys/auth codes, confirm user confirmation required before write tools per spec requirement, validate frontend wizard displays masked password fields correctly.

Post-launch monitoring: track `last_used_at` timestamp + request counter in JSONB object for monetization decisions later.  

### Additional Context For Agents 

Knowledge base system via memory paths; search by filename or semantic query describing what you're looking for  
Monetization pipeline starts when users request custom integrations -> admin review queue with optional pricing tier assignment
Database schema reference: Run `DESCRIBE mcp_templates; DESCRIBE user_mcp_configs;` in PostgreSQL CLI to see full table structure
