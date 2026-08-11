# 📋 PHASE 4 IMPLEMENTATION PLAN - HappyFox MCP Template #1

**Status:** Ready for Development ✅  
**Template Name:** HappyFox Ticket Management 🔧  
**Repository:** https://github.com/Glitch3dPenguin/happyfox-mcp (original author/maintainer: Glitch3dPenguin)  

---

## 1. EXECUTIVE SUMMARY

This document outlines the implementation plan for adding **HappyFox MCP Server** as Template #1 in Eepy Host's managed SaaS gateway architecture. This is NOT a per-user container deployment - instead, we will create encrypted credential storage and route all HappyFox tool calls through a centralized proxy endpoint (`/api/mcp/proxy/happyfox/*`).

### Key Architecture Principles
- **Single unified backend** handling all MCP integrations via `/proxy/{template_id}/*` routes
- **Credentials stored as Fernet-encrypted JSONB columns in PostgreSQL**, decrypted only temporarily during request handlers
- **No per-user Docker containers** - this is a SaaS model, not self-hosting infrastructure
- **Admin approval required** before users can connect any template (monetization gate)

---

## 2. DATABASE SCHEMA CHANGES NEEDED

### Files to Create/Modify:

#### `backend/models/mcp_models.py` ⚠️ CREATE NEW FILE

```python
from sqlalchemy import Column, Integer, String, JSON, Boolean, DateTime, ForeignKey, Enum as SQLEnum
import enum

class MCPTemplate(Base):
    """Admin-approved template library entries - users cannot add custom templates directly"""
    __tablename__ = 'mcp_templates'
    
    id: int (PK)                    # slug string like "happyfox" for routing purposes
    name: str                       # Display name, e.g. "HappyFox Ticket Management 🔧✅"
    
    description: str                # Human-readable capabilities summary
    
    config_schema: JSON             # Form field specifications for credential entry:
                                    {
                                      "type": "object", 
                                      "properties": {
                                        "HAPPYFOX_DOMAIN": {"type": "string", "required": true},  
                                        "HAPPYFOX_API_KEY": {"type": "password", "required": true, }, 
                                        "HAPPYFOX_AUTH_CODE": {"type": "password", "required": true}
                                      }
                                    }
    
    image_tag: str                  # Docker container reference (if needed for backend proxy calls)  
                                   # Example value from HappyFox repo: ghcr.io/glitch3dpenguin/happyfox-mcp
    
    approved_by_admin: bool         # Admin approval gate before users can connect this template ✅
    
    enabled_global: bool            # Feature flag - admin enables/disables templates centrally 🔐  
    
class UserMCPServerConfig(Base):   # ONE entry per user + template combo (no "instance" concept)  
    __tablename__ = 'user_mcp_configs' 
    
    id: int (PK)
    owner_id: ForeignKey(User.id)         # Which user? ✅ USER_ROLE required to manage their own
    
    template_name: str              # Foreign key reference as string for flexibility ("happyfox", etc.)    
    name_display: str               # User-given label like "My Support Queue" or default from MCPTemplate.name
    
    credentials_json: JSONB         # ENCRYPTED using Fernet + MCP_ENCRYPTION_KEY env var ✅ ⚠️ NEVER PLAINTEXT
        # Stores all API key/secrets per user's input during connection wizard flow 🔒🔑

class MCPTemplateRequest(Base):   # User-requested integration workflow = monetization pipeline start point 💰⏺️ 
    __tablename__ = 'mcp_template_requests' 
    
    id: int (PK)
    requester_id: ForeignKey(User.id)         # Who requested this? 🔒👤

    requested_name: str             # What the user wants added to library ✅💜  
    description_purpose: TEXT       # Why they need it, use case for admin approval/rejection
    
    status: Enum('pending', 'approved', 'rejected')  # Admin workflow states 🛡️⏺️

```

#### `alembic/versions/001_add_mcp_templates.py` ⚠️ CREATE NEW MIGRATION FILE  
Auto-generated Alembic migration to add these three new tables + foreign key constraints. Run after creating the models file ✅📦🔧

---

## 3. BACKEND ENDPOINTS TO IMPLEMENT

### Files to Create/Modify:
#### `backend/api/mcp_endpoints.py` ⚠️ CREATE NEW FILE (or update existing if `/api/` routes already exist)

| Method | Route | Description | RBAC Required? | Notes ✅ |
|--------|-------|-------------|----------------|----------|
| `GET`  | `/api/mcp/templates/list`    | List all approved + enabled templates with their config schemas (public read or user login required at most) | ❌ No auth / USER+ if you want to gate library browse ✅🔒 | Returns static JSON from MCPTemplate table where `approved_by_admin = true AND enabled_global = true` 🔐💜 |
| `POST` | `/api/mcp/config/register`   | User saves encrypted credentials for template they own access to (via config_schema form) | ⚠️ USER+ required ✅🛡️⏺️ | Encrypts user input via Fernet + MCP_ENCRYPTION_KEY env var, stores in `credentials_json` column 🔒✅❗ |
| `DELETE` | `/api/mcp/config/{config_id}` | Remove stored config (decrypted creds purged from DB immediately on delete) ⚠️ ENCRYPTED DELETE ON DESTROY ✅🔐💜 | OWNER only check via owner_id FK in UserMCPServerConfig table 🔒❗ |
| `POST` | `/api/mcp/request/template`   | Submit new template request for admin approval = monetization pipeline start point 💰⏺️✅ | USER+ required ✅🛡️⚠️ | Inserts into MCPTemplateRequest table with status='pending' 🔐💜✨|
| **THE CORE ROUTE → All HappyFox calls flow through this proxy endpoint:** Ⓛ⤇  |||||  
| `GET/POST` `/api/mcp/proxy/happyfox/{tool_name}/{rest_of_path}` | Load user's encrypted credentials from DB, decrypt temporarily in memory only ✅, route authenticated call to external service, stream response back without persisting tokens or data ⏺️🔒✅⚠️ SECURITY CRITICAL 🔐💜❗ | OWNER of config required + check via owner_id FK before any read/write operation ❌ NEVER expose another user's credentials! 🛡️✨|

**Proxy Endpoint Logic Flow Example (HappyFox):** ✅  
```python
@router.post("/proxy/happyfox/{tool_name}")  # tool_name = list_tickets, add_ticket_update, etc. 
async def happyfox_proxy(
    tool_name: str, 
    params: dict,           # From user request body or URL path parameters 🔐✅💜  
) -> Response:    
    user_id = JWT.decode_current_token().user.id          # Get current authenticated USER ID ✅🛡️⏺️
    
    config = UserMCPServerConfig.query.filter(
        by(template_name == "happyfox", owner_id=user_id).first()  # Find encrypted creds from DB 🔒✅❗
    ) 
    
    if not config:
        raise HTTPException(status_code=403, detail="No HappyFox configuration found for this user ❌") 
        
    decrypted_creds = fernet.decrypt(config.credentials_json.encode('utf8'))   # Decrypt in MEMORY only ✅⚠️🔐💜 NEVER TO DISK!!! 
                            # Result is JSON string: {"HAPPYFOX_DOMAIN": "...", "HAPPYFOX_API_KEY": "...", ...}
    
    domain = json.loads(decrypted_creds)["HAPPYFOX_DOMAIN"]  
    api_key = decrypted["HAPPYFOX_API_KEY"]   
    auth_code = decrypted["HAPPYFOX_AUTH_CODE"]  

    base_url = f"https://{domain}/api/1.1/json/"           # Build HappyFox v1.1 JSON API endpoint ✅

    if tool_name == "list_tickets":
        response = requests.post(base_url + "/ticket/list", json=params, auth=(api_key,))  # Call external service 🔒✅❗  
        
    elif tool_name == "add_ticket_update" or other write tools: 
        ⚠️ MUST return draft for user confirmation FIRST ✅ (per HappyFox spec requirement) 🛡️💜✨
        
    ... handle all remaining MCP tools from repo
    
    # IMPORTANT: NEVER log decrypted credentials to logs! Only use temporarily during handler execution 🔒✅❗⏺️

```

---

## 4. FRONTEND COMPONENTS TO BUILD

### Files to Create/Modify:  
#### `frontend/src/app/mcp/library/page.tsx` ⚠️ CREATE NEW PAGE (or update existing /mcp directory)  

**Goal:** Display template cards for all approved templates in a grid/list view ✅🖼️💜

```tsx
export default function MCPLibraryPage() {    
    // Fetch from GET /api/mcp/templates/list endpoint, filter to show only approved+enabled ones ✅✅  
    const [templates, setTemplates] = useState([]);  
    
    useEffect(() => {     
        fetch('/api/mcp/templates/list').then(res => res.json()).then(data => setTemplates(data)) 
    }, []) 
    
    return (      
      <div className="p-8 bg-void min-h-screen">          
          {/* Hero section with title and description */}  
          <h1 className="text-3xl font-bold text-eepy-lavender mb-6">Connect Integrations 🔧✅</h1>           
          {templates.map((template) => (            
             // Template card that users click → opens connection wizard ✅🖼️💜              
              <button key={template.id} onClick={() => Router.push(`/mcp/connect/${template.slug}`)}>               
                 <div className="bg-void-surface border void-border p-6 rounded-lg hover:shadow-eepy-lavender/50 transition-all">                  
                     <h2 className="text-xl font-semibold text-white">{template.name}</h2>                 
                       {template.description}           
               </div>             
         {/* HappyFox card will be first visible here once template is approved in DB ✅💜🔥 */}   
     )}  
  ); }
```

#### `frontend/src/components/MCPConnectionWizard.tsx` ⚠️ CREATE NEW REUSABLE COMPONENT

**Goal:** Multi-step form where users pick a template + enter encrypted credentials for that service ✅📝💜  

```tsx
// Usage: imported from /mcp/connect/[template_id] page or dynamically mounted as component  
interface MCPConnectionWizardProps {     
  templateSlug: string;        // e.g., "happyfox"  
  onSubmit(credentials: object): void    // Call backend POST /api/mcp/config/register ✅✅🔒💜    
}  

export function MCPConnectionWizard({templateSlug, onSubmit}: MCPConnectionWizardProps) {      
  const [formData, setFormData] = useState({...});       
    
// Dynamically build form based on config_schema from template object returned by GET endpoint above ✅💜❗  
return (     
    <div className="bg-void-surface border void-border p-8 rounded-lg">         
       {/* Step indicator */}           
       {Object.keys(formData).map(field => (            
           // Render each field type per schema: 'string' = text input, 'password' = masked password ✅🔒✨        
             <input             
                key={field}                 
                 name={field}                
                  onChange={(e) => setFormData({...formData, [field]: e.target.value})}              
                     className="bg-void border void-border p-3 rounded"     
            />           
       ))}    
     {/* Submit button → calls onSubmit() which POSTs encrypted credentials to backend ✅✅🔐💜 */ }          
         <button onClick={() => {onSubmit(formData)}}>                    
                Connect Integration 🔧✅  
           </button>            
    `);  }
```

#### Page Routes: ⏺️❗
- `/mcp/library` → Template grid list view ✅🖼️💜 (HappyFox card visible once template is approved)  
- `/mcp/connect/happyfox` → Opens connection wizard for HappyFox integration specifically ✅⚙️✅

---

## 5. BACKEND SECURITY & CREDENTIAL ENCRYPTION STRATEGY ⏺️❗🔒

### Files to Create/Modify:
#### `backend/utils/crypto.py` ⚠️ CREATE OR UPDATE EXISTING UTILITY FILE  

**CRITICAL:** All user MCP credentials stored in PostgreSQL must be encrypted at rest using Fernet symmetric encryption + single master key from environment variable. Decryption only happens temporarily inside request handlers — never persisted to disk or logs!

```python
from cryptography.fernet import Fernet   
import os   

# Single global instance initialized once when backend starts ✅⏺️❗🔒  
MCP_ENCRYPTION_KEY = os.environ.get('MCP_ENCRYPTION_KEY', 'default-dev-key-change-in-production-please') 

if not MCP_ENCRYPTION_KEY.startswith(b''):   # Ensure key is proper bytes format from environment variable ✅💜❗ 
    fernet_instance = Fernet(MCP_ENCRYPTION_KEY)  
else:    
    raise ValueError("MCP_ENCRYPTION_KEY must be set as 44-byte Base64 encoded string (Fernet requirement)")

# Helper function for encryption: takes raw dict/object, returns encrypted bytes/string ✅✅🔐💜  
def encrypt_credentials(credentials_json_dict: object) -> str:     
    """Encrypt user credentials before storing to DB - NEVER store plaintext! ⚠️❗"""      
     json_string = json.dumps(credentials_json_dict).encode('utf8')
      return fernet_instance.encrypt(json_string).decode()   # Return Base64-encoded encrypted bytes ✅✅❗

# Helper function for decryption: takes encrypted string from DB, returns decrypted dict in memory ONLY ✅⏺️💜🔒  
def decrypt_credentials(encrypted_string_from_db: str) -> object:      
    """Decrypt user credentials temporarily in memory during request handler execution only! ❌ Never to disk/logs"""     
     json_bytes = fernet_instance.decrypt(encrypted_string.encode('utf8'))   
         return json.loads(json_bytes.decode())  # Dict returned, but NEVER persisted anywhere else ✅⚠️❗🔒

```

**Security Checklist Before Launch:** ⏺️❌⚠️  
- [ ] Verify all `credentials_json` columns are Fernet encrypted at rest (single master key from env var) ✅✅💜  
- [ ] Decryption only happens in memory during request handler execution → NO disk writes or log output ever! 🔒🔐💜❗⏺️
- [ ] All MCP tool responses sanitized for context safety? Yes, HappyFox `list_tickets` already returns compact summaries ✅✅✨  
- [ ] User confirmation required before any write operations to external service (per HappyFox spec requirement)? YES per repo documentation 🛡️💜🔥

---

## 6. STARTER TEMPLATE CONFIGURATION: HAPPYFOX DETAILS 📊⏺️✅  

### MCP Tools Supported from Original Repository ✅  
**Read Operations:**
- `list_tickets()` — compact table with titles/metadata only (context safe) ✅✨⚠️
- `get_ticket_details(ticket_id)` — structured metadata + opening message for single ticket 🔒💜🔧  
- `get_ticket_messages(ticket_id, limit=N?)` — full conversation thread up to N most recent messages ⏺️✅❗  
- `list_statuses()` — all available statuses in user's HappyFox account with IDs ✅⚠️
- `list_staff()` — all staff/agents with their names and ID numbers 🔒💜📞  
- `get_ticket_attachments(ticket_id)` — list attachments (filenames, sizes, MIME types + direct download URLs) 📎✅✨

**Write Operations:** ⏺️❌⚠️ ALL REQUIRE USER CONFIRMATION FIRST per repo spec!
- `add_ticket_update(...)` — post public reply or private note to ticket ✅🛡️💜 (optional status change in same call)  
- `create_ticket()` — open new support ticket with message + optional metadata 📝✅⚠️
- `rename_ticket(id, new_subject)` — retitle vague subjects like "Help!!" → meaningful titles 💬✨❗  
- `change_ticket_status(id, status_id)` — change only status (close/hold/etc.) ✅🔧💜

### Environment Variables Required From Users 📋⏺️✅
| Variable | Type | Description | Required? | Example Value |
|----------|------|-------------|-----------|---------------|
| `HAPPYFOX_DOMAIN` | string | Your HappyFox subdomain, e.g. "mycompany.happyfox.com" or .net for EU accounts ✅🔒❗✅  
| HAPPYFOX_API_KEY | password (masked in UI) | API key from account settings page on HappyFox portal 📋⚠️ | Yes 🔑💜✅  | `a1b2c3d4e5f6g7h8i9j0`
| `HAPPYFOX_AUTH_CODE` | password (masked in UI) | Auth code from account settings page on HappyFox portal 📋⚠️  
| Yes 🔑💜✅  | `x1y2z3a4b5c6d7e8f9g0h1i2j3k4l5m6`

### Default Transport Mode for Eepy Host Users ✅ ⏺️🔒
**Default:** `streamable-http` (recommended per original repo documentation)  
Users can optionally choose SSE transport later if needed - but HTTP is easier to route through centralized proxy endpoint architecture ✅✅❗💜

---

## 7. ADMIN APPROVAL WORKFLOW ENDPOINTS ⏺️💰🔐

### Files to Create/Modify:
#### `backend/api/superuser/mcp_admin.py` ⚠️ CREATE NEW FILE (or update existing /superuser/* routes)  

| Method | Route | Description | RBAC Required? | Notes ✅  
--------|-------|-------------|----------------|---------| 
| `POST`   | `/api/superuser/templates/approve/{id}`     | Approve user-requested template → add to library, enable for all users 💰⏺️✅🔐💜 | ⚠️ SUPERUSER role only ✅❗  
| DELETE  | `/superuser/request/reject/{id}/notes`       | Reject request with optional admin notes sent back to requester (for transparency/feedback loop) 🛡️⚠️    ❌ NO REASON REQUIRED if you prefer silence for security/compliance reasons ⏺️💜✅|  

**Database Changes Needed:** `MCPTemplateRequest.status = 'approved'` after approval, or `'rejected'` with notes stored ✅📋❗

---

## 8. IMPLEMENTATION SEQUENCE (EXECUTE STEP-BY-STEP) ✅⚙️

### Phase 4a Week 1: Database Schema + Migration Files 🏛️✅
**Tasks to complete before writing any other code:**  
[ ] Create `backend/models/mcp_models.py` file with three new table definitions: MCPTemplate, UserMCPServerConfig, MCPTemplateRequest ✅🔒⚠️❗ 
[ ] Generate Alembic migration script via `alembic revision --autogenerate -m "Add MCP template tables"` ✅✅💜  
[ ] Run migration on dev environment and verify schema is correctly created in PostgreSQL (check DB manually or use psql) 🔍📦⚠️

### Phase 4a Week 2: Backend Endpoints + Crypto Utils ⏺️❗🔐
**Tasks to complete before touching any UI code:**  
[ ] Create `backend/utils/crypto.py` with Fernet encryption/decryption helper functions ✅✅💜🔒⚠️ ❗NEVER LOG DECRYPTED CREDENTIALS! 🛡️✨⏺️❌    
[ ] Implement GET `/api/mcp/templates/list` endpoint returning list of approved+enabled templates from MCPTemplate table ✅✅💜  
[ ] Implement POST `/api/mcp/config/register` for user credential storage with encryption at DB insert time (encrypted JSONB column) 🔒🔐⚠️❗  
[ ] Implement DELETE route and all other basic CRUD operations on UserMCPServerConfig via owner_id FK checks ✅✅💜

### Phase 4a Week 3: Frontend Library Page + Connection Wizard UI 🖼️✨
**Tasks to complete before implementing proxy endpoint logic:**  
[ ] Create frontend page `/mcp/library` showing template cards in grid layout (HappyFox appears first) ✅🔧⚠️❗💜   
[ ] Implement reusable MCPConnectionWizard component accepting config_schema from backend + dynamically building form fields based on field types (string vs password input toggle for credential visibility!) 🔒✅✨
[ ] Wire up submit button to call POST `/api/mcp/config/register` with user-entered credentials ✅✅🔐💜⚠️

### Phase 4a Week 4: HappyFox Proxy Endpoint Logic + Security Testing ⏺️❗📡
**Tasks critical for launch readiness:**  
[ ] Implement proxy endpoint routing under `/api/mcp/proxy/happyfox/{tool_name}` ✅✅💜 ❗SECURITY CRITICAL 🔒⚠️  
[ ] Test HappyFox tool list_tickets, get_ticket_details via manual curl requests with mocked decrypted credentials in memory (do NOT use production API keys yet!) 🧪🔐❗

---

## 9. TESTING & DEPLOYMENT CHECKLIST ✅ ⏺️❌⚠️  

**Before enabling HappyFox template for all users:**  
[ ] Verify encryption at rest: confirm decrypted credentials are never persisted to disk via code review + grep 🔍✅🔒⚠️    
[ ] Test proxy endpoint with mocked data → ensure no logs leak decrypted API keys/auth codes 🛡️❌💜⏺️
[ ] Confirm user confirmation required for all write tools (add_ticket_update, create_ticket) per HappyFox spec requirement ✅✅✨  
[ ] Validate frontend wizard correctly displays masked password fields and unmasked text input toggles for each credential field 🔒👁️❗

---

## 10. POST-LAUNCH MONITORING & METRICS ⏺️💰📊  

Once HappyFox is live on Eepy Host, track these metrics for monetization decisions later:
- `last_used_at` timestamp per UserMCPServerConfig row ✅⚠️  
[ ] Every request increments counter in same JSONB object (usage volume tracking) 📈💰✅

--- 

## NEXT STEPS FOR DEVELOPMENT 💬🔧❗  

**Recommended approach:** I will now build each phase sequentially via real-time chat:
1. First, we'll create `backend/models/mcp_models.py` + Alembic migration ✅ (Phase 4a Week 1)  
2. Once you approve the schema and review code → proceed to backend endpoints section ✅✅💜⏺️❗

Let me know when you're ready for Phase 4 Week 1 implementation tasks, and I'll provide complete file contents with inline comments as we build this together! 🚀🔧✨  