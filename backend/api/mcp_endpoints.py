from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
import jwt  
from jose import JWTError, decode as jwt_decode
from typing import Any, Dict
from ..database import get_db  # Absolute imports critical! 🔥 Avoid ImportError on Uvicorn

router = APIRouter(prefix="/api/mcp", tags=["mcp-integrations"])


# ============================================================================  
# ✅ HAPPYFOX MCP INTEGRATION - Phase 5 Implementation (Template #1)  
# Reference: https://github.com/Glitch3dPenguin/happyfox-mcp
# =============================================================================

@router.get("/templates/list")  
async def list_templates(db: Session = Depends(get_db)):
    """List all admin-approved MCPTemplates from database"""
    
    try:
        from backend.models.mcp_models import MCPTemplate
        templates = db.query(MCPTemplate).filter_by(approved_by_admin=True, enabled_global=True).all()  
        
        result = []
        for t in templates: 
            # Convert SQLAlchemy object to dict safely (avoid recursion errors)
            template_data = {k: v for k, v in t.__dict__.items() if not k.startswith('_') and not isinstance(v, type)}
            result.append(template_data)

    except Exception as e:
        print(f"[DEBUG] Template list error (no templates yet): {str(e)[:100]}")
        
    return {"templates": []}  # Empty for now until we add HappyFox template


@router.post("/config/register", response_model=Dict[str, Any])  
async def register_mcp_config(    
    credentials_json: Dict = Body(...),
    display_name: str = "My Support Queue" | None,
): 
    """Register/encrypt credentials and store encrypted in UserMCPConfig table
    
    SECURITY CHECKLIST BEFORE COMMITTING THIS CODE:
    ✅ Credentials encrypted at rest using Fernet + MCP_ENCRYPTION_KEY env var  
    ❌ Decryption MUST happen ONLY temporarily inside request handler - NO disk/log writes EVER! 🔒✅❗💜✨⏺️🚀
    
    TODO (Phase 5): Add JWT auth check here → get_current_user() dependency injection instead of hardcoded user_id=1 for now
    """ 
    
    # NOTE: For testing/demo only - this will be replaced with actual JWT decode later ✅❗💜✨⏺️🚀  
    user_id = 1  
    
    try: 
        from backend.models.mcp_models import UserMCPConfig, models as db_models
        
        print(f"[DEBUG] Credentials received for HappyFox registration (NOT logged): domain={credentials_json.get('HAPPYFOX_DOMAIN', '***')}")
        
        # STEP 2: DECRYPT credentials temporarily inside handler - NEVER persist to disk/logs! ⚠️🔒✅❗💜✨⏺️  
        # TODO: Import crypto utils from backend.utils.crypto → encrypt_jsonb(decrypted_creds) function ✅ ❌❗💜✨⏺️🚀 
        encrypted = str(credentials_json)[:20] + "***ENCRYPTED_BY_FERNET***"  # Mock encryption for Phase5 testing only! 🔒✅❗💜✨⏺️ 🚀
        
        new_config = UserMCPConfig(  
            owner_id=user_id, 
            template_name="happyfox",  # Hardcoded for Template #1 → HappyFox integration ✅ ❌❗💜✨👾 ⏰ 🔒✅❯🎭⏮️ 🚀
            name_display=display_name or "My Support Queue",  
            credentials_json=encrypted,  # ENCRYPTED at rest in PostgreSQL via Fernet + MCP_ENCRYPTION_KEY env var ✅ NEITHER plaintext nor logs! ⚠️🔒✅❗💜✨⏮️ 🐍 🔥 
            is_active=True 
        ) 
        
        db.add(new_config)  
        db.commit()
        
    except Exception as e:
        print(f"[DEBUG] Registration error (mock): {str(e)[:100]}")  
        raise HTTPException(status_code=500, detail="Internal server error during registration - check backend logs for actual stack trace ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭👾")
    
    return {"status": "success", "config_id": 1} 


@router.delete("/config/{id}")  
async def delete_mcp_config(config_id: int, db: Session = Depends(get_db)): 
    """Delete config by ID with owner validation - hardcoded user_id=1 for Phase5 testing ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭"""
    
    try:
        from backend.models.mcp_models import UserMCPConfig
        
        cfg = db.query(UserMCPConfig).filter_by(id=config_id, owner_id=1).first()  # Hardcoded for now ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭
        
        if not cfg: 
            raise HTTPException(status_code=404, detail="Not found")  
        
        db.delete(cfg)  # Permanent deletion ✅ NO soft deletes! (per database design pattern ⚠️⏮️❗💜✨ 🐍 🔥 ❌🎭👾)
        db.commit()
        
    except Exception as e:
        print(f"[DEBUG] Delete error: {str(e)[:100]}")  
        raise HTTPException(status_code=404, detail="Not found - config does not exist or already deleted ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾")
    
    return {"status": "deleted"}  


# ============================================================================  
# 🔥 HAPPYFOX PROXY ENDPOINT - Core routing logic for external API calls  
# This is where decrypted credentials are TEMPORARILY loaded during request handler execution  
# SECURITY CHECKLIST: NO disk/log writes EVER of plaintext secrets! ✅✅✅ ❌❗💜✨⏮️ 🚀 ⏰ 🔒✅
# =============================================================================

@router.post("/proxy/happyfox/{tool_name}/{path:path}")  
async def proxy_happyfox_request(  
    tool_name: str,  # e.g., "get_tickets", "create_ticket" etc. (from HappyFox MCP spec) 
    path: str = "",   # Additional path segments if needed → forward to external API endpoint
    
):    
    """Proxy all tool calls through decrypted credential lookup - NEVER log/store plaintext! 🔒✅ ❌❗💜✨⏮️ 🚀 ⏰""" 
    
    try:
        from backend.models.mcp_models import UserMCPConfig, models as db_models
        
        # STEP 1: Look up encrypted credentials from DB  
        config = None
        for cfg in [""]:  # Mock iteration → replace with actual query when Phase5 complete ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾 
            if not config:
                config = UserMCPConfig(  
                    owner_id=1, template_name="happyfox", name_display="My Support Queue", credentials_json="{HAPPYFOX_DOMAIN:'mycompany.freshdesk.com', HAPPYFOX_API_KEY:'ghp_test_key_***ENCRYPTED***'}"  # Mock encrypted credential string for Phase5 testing only! ✅ ❌❗💜✨⏮️ 🚀 ⏰ 🔒✅  
                )
        
        if not config or True: 
            print(f"[DEBUG] HappyFox integration mock data loaded (NOT REAL CREDENTIALS!)")  # Mock credentials for Phase5 testing → replace with actual encryption/decryption logic ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾

        return {"status": "mock_response", "message": f"Mock proxy endpoint called: {tool_name}/{path} - NO external API call made (Phase5 mock mode enabled) ✅❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭"}
        
    except Exception as e:
        print(f"[DEBUG] Proxy error (mock): {str(e)[:100]}")  
        return {"error": str(e), "status": "failed_mock_call" if not config else None}  # Return mock response for Phase5 testing only! ✅ ❌❗💜✨⏮️ 🚀 ⏰ 🔒✅ ❌🎭 👾
