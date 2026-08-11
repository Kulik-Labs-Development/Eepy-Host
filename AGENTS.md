# Agent Instructions for Eepy-Host Project

## Setup Commands

### Prerequisites
```bash
python 3.12+ required for backend development
Node.js 18+ recommended for frontend work
PostgreSQL 15+ running locally or via Docker container
```

### Backend Development
```bash
# From /backend directory:
cd /home/user/eepy-host/backend

# Install Python dependencies (includes FastAPI, SQLAlchemy, cryptography, alembic)
pip install -r requirements.txt pipenv pytest python-dotenv sqlalchemy asyncpg uvicorn fastapi python-jose[cryptography] cryptography alembic pydantic==2.0.* 

# Run database migrations manually against your dev PostgreSQL instance:
DATABASE_URL="postgresql://eepy_admin:[ROTATED_POSTGRES_PASSWORD]@db:5432/eepy_host" \
MCP_ENCRYPTION_KEY=your-actual-secret-key-here-change-in-production-blahblah== \
python run_migrations.py

# Start the development server with hot-reload enabled ✅🔥⚡ 
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Verify health check endpoint responds before proceeding 👍✅✨  
curl http://localhost:8000/health
```

### Frontend Development
```bash
cd /home/user/eepy-host/frontend 

pnpm install # or npm install if you prefer package manager consistency ✅⚙️❗💜🔒  

# Start Next.js development server with App Router hot-reload enabled 💻✨  
pnpm dev

# Build static export for production deployment (if needed):
pnpm build && pnpm start
```

### Docker Deployment Commands ⚓🐳✅
```bash 
# From repository root:
docker compose up --build -d # Start all containers on eepy-network with multi-stage builds ✅⏺️❗💜 🔄  

docker-compose ps   # Verify both frontend/backend services running healthy and connected to PostgreSQL container  👍👾✅

docker logs backend-app -f      # Follow live backend app server output for debugging errors 🔒📊❌
```

## Code Style Guidelines

### Backend (Python / FastAPI) 🐍💜⚙️❗  
1. **Absolute Import Rule CRITICAL:** Never use relative imports (`from .module import ...`) inside `backend/main.py`. Uvicorn runs the app as a top-level script → Python throws `ImportError: attempted relative import with no known parent package` ❌🔥💀

   ```python
    # ✅ GOOD - works on deployment without issues 🚀✨   
    from models.mcp_models import MCPTemplate
   
    # ❌ BAD - will crash hard when deployed outside dev server context ⛔⏺️❗
    from .models.mcp_models import MCPTemplate  # NEVER do this! 🔥📉💻  
   ```

2. **Pydantic Model Usage:** All request/response schemas should inherit from `BaseModel` and include type hints with optional validation rules (min_length, regex patterns etc.) ✅⏺️❗✅  
3. **Error Handling Pattern:** Wrap all database operations in try/except blocks + return standardized HTTPException responses using FastAPI middleware layer (`backend/api/common.py`) for consistent error message formatting 📋🛡️💜✨

4. **Fernet Encryption Requirements (MCP Credentials Only):** All MCP user credentials stored in PostgreSQL `user_mcp_configs.credentials_json` column must be encrypted at rest via Fernet symmetric encryption with single master key from environment variable `MCP_ENCRYPTION_KEY`. Decryption happens ONLY temporarily inside request handlers — never persists anywhere else, not even logs! ⚠️❗🔒💜⏺️

   ```python  
    # Example usage in proxy handler for HappyFox tool calls ✅✅🔐✨
    from utils.crypto import encrypt_credentials, decrypt_credentials
   
     @router.post("/mcp/proxy/happyfox/{tool_name}") async def happyfox_proxy(tool_name: str, params: dict):   
        decrypted_creds = decrypt_credentials(row.credentials_json)  # Decrypt in MEMORY only during this request ❌ NEVER TO DISK! 🔒⏺️❗💜 
         return external_api_call(decrypted_creds["HAPPYFOX_API_KEY"], ...)  
   ```

5. **Database Transactions:** All data-modifying endpoints must use SQLAlchemy ORM sessions with explicit commit/rollback handling inside `with engine.connect()` block + error recovery for partial failures 📦✅⏺️❗💜🔐  

### Frontend (TypeScript / Next.js App Router) ⚡💻✨  
1. **Component Naming:** All React components use PascalCase naming convention ✅🧩⏺️❗💜
   ```typescript 
    // ✅ GOOD - clear intent about what this component does 🎯✅✨   
    ConnectionWizard.tsx, MCPLibraryPage.tsx
   
    # ❌ BAD - lowercase or camelcase breaks TypeScript strict mode ⚠️⛔📉  
    connection_wizard.tsx (# Never! Use PascalCase for everything)
   ```

2. **Tailwind Utility Classes:** No arbitrary CSS values unless absolutely necessary (e.g., dynamic color schemes). Stick to predefined void palette utilities: `bg-void`, text variants like `text-eepy-lavender` ✅🎨⚙️❗💜✨  
3. **Lucide Icons Only:** Use Lucide React icon library for all visual elements — no emoji-heavy icons or custom SVG paths unless required by design system 🔮💻✅

### Commit Message Format 📝⏺️❗
- Follow this exact structure: `[type] brief description` ✅🚀  
  Example commits from main branch history:
   ```bash 
    "Add MCP model definitions and Pydantic schemas for template library" ✅💜✨
    
    "Complete Phase 4 implementation plan with database migration scripts + encryption utilities 🌙⏺️❗💰🔧" 
    
    "# Rename to AGENTS.md: comprehensive system guide updated per external reference link ✅✅📘💻\n\n# Added MCP template schema definitions including config form field specs for HappyFox integration 💜✨📋  "
   ```

## Testing Instructions

### Backend Tests (Pytest) 🧪⚠️❗✅  
```bash  
cd /home/user/eepy-host/backend 

# Run all unit tests with coverage reporting enabled ✅⏺️💻🔒✨ 
pytest tests/ --cov=. -v || echo "Tests failed, review failures above ❌⛔"

## To run a single test file (e.g., for crypto utility verification):
pytest tests/test_crypto.py::test_encrypt_decrypt_roundtrip — verbose output shows success/failure immediately ✅✅🧪  
```

### Frontend Tests ⚡💻✨  
From repository root:  
pnpm test # Runs Vitest suite in watch mode by default (dev feedback loop) 🔄⏺️❗  

# For CI/CD pipelines, use non-watch execution:
pnpm vitest run --reporter=verbose && pnpm lint || echo "Build failed due to type checking errors ⚠️⛔📉"

## Integration Test Checklist ✅✅❗💜 (Before Deployment):
1. Verify no relative imports exist in `backend/main.py` 📋⏺️❌  
2. Post-write file verification via grep runs before every commit to ensure escaping didn't leak into JSX blocks 🔍🔒⚠️  
   ```bash 
    # Quick sanity check after writing any .tsx/.jsx files:
    grep -r '\\\\\\\\n' frontend/src/app/ | wc -l  # Should be zero (no literal backslash-n strings) ✅✅✨  

3. If modifying MCP credential storage logic → double-check encryption logic via unit tests in utils/crypto.py module 🧪🔐❗⏺️💜  
4. All superuser routes have middleware protection checked via functional test cases using fake JWT tokens with role='SUPERUSER' payload ⚙️✅😈  

## MCP Template Integration Workflow 💻✨⚠️

### Adding New External Service Templates 🛡️🔐💜
1. **Define DB Schema First:** Add `MCPTemplate` table row via database migration script ✅❗⏺️  
   ```bash 
    # Example for HappyFox integration (already implemented) 👍✅✨  
    CREATE TABLE mcp_templates (...);  -- Run in PostgreSQL manually or use run_migrations.py helper ⚙️📦💜  
```

2. **Implement Proxy Endpoint:** Create new FastAPI router under `/api/mcp/proxy/{template_id}/...` that follows this pattern: ✅✅❗⏺️💰
   ```python 
    @router.post("/mcp/proxy/happyfox/{tool_name}") async def happyfox_proxy(tool_name, params):   
        # Step 1: Load encrypted credentials for authenticated user via owner_id FK join 📦🔒  
        row = db.query(UserMCPConfig).filter_by(owner_id=current_user.id template_name="happyfox").first() 
      
       if not row or not decrypt_credentials(row.credentials_json) exists(): raise HTTPException(403, "No HappyFox configuration found for your account ❌⛔🚫")  
        
         # Step 2: Decrypt only temporarily during this request execution (NEVER TO DISK/LOGS!) ✅✅❗💜✨
        decrypted_creds = decrypt_credentials(row.credentials_json)  # Returns dict → use values here then discard immediately 🔐⏺️  

3. **Update Connection Wizard UI:** Add new form fields to `/mcp/library` page for credential entry based on `config_schema` JSON definition stored in MCPTemplate model ✅✅📋💜✨  
   ```tsx 
    // Example: Dynamic render function that builds HappyFox connection wizard from template's config schema ⚙️🔧❗
    {Object.entries(template.config_schema.properties).map(([field_name, field_spec]: [string, any]) => (   
       <input key={field_name} name={field_name} type={field_spec.type === 'password' ? 'password':'text'} className="bg-void border void-border p-3 rounded" />  
    ))}  
   ```

### Admin Approval Workflow 🛡️⏺️✅
1. Users submit template requests via `MCPTemplateRequest` table (`status='pending'`) ✅📋💜✨  \n2. Superuser dashboard shows approval queue with optional admin notes for rejection/reason tracking ❌⚠️📝\n3. When approved → set MCPTemplate.approved_by_admin=true + enabled_global toggle on so users can connect via `/mcp/library` page ✅✅❗💜

## Security Gotchas (CRITICAL!) 🔐⏺️❗
1. **Encrypted Credential Storage:** All user credentials stored in PostgreSQL must be Fernet-encrypted before write operations; never persist plaintext anywhere (disk/logs/memory dumps excluded during handler execution) ⚠️🔒💜 ✅  
2. **Decryption Only In-Memory During Request Handlers:** Any decrypted credential data used for external API calls MUST NOT appear in logs, error messages or response payloads after request completion ❌⛔❗\n3. If modifying credential storage → verify encryption logic via unit tests + manual curl requests with mocked tokens before deployment ✅✅🧪🚀

## Project Overview 📦💻✨  
**Eepy Host (eepy.host)** is a SaaS MCP gateway platform designed specifically for Model Context Protocol servers — NOT self-hosted Docker container orchestration per-user. Instead, it's the **all-in-one managed integration layer between LLM agents and real-world tools**: Google Calendar Slack Workspaces Notion Databases File Systems Web Browsing APIs connected via single backend proxy API that handles authentication securely in one place.\n\n**Core Architecture Principle:** Users don't deploy containers; they "connect integrations" — we handle API plumbing, credential management (encrypted at rest), unified proxy routing so their agent can use external tools without operational overhead 🤝💜✨

## Additional Context For Agents 🧠⚙️
1. **Knowledge Base System:** Internal documentation stored via `query_knowledge_files()` and memory paths; search by filename or semantic query describing what you're looking for 🔍📁✅\n2. **Monetization Pipeline Template Approval workflow starts when users request custom integrations → admin review queue + optional pricing tier assignment 💰⏺️❗💜✨  \n3. Database Schema Reference: Run `DESCRIBE mcp_templates; DESCRIBE user_mcp_configs;` in PostgreSQL CLI to see full table structure for template library, encrypted credential storage etc. 📊🔐⚙️\n
