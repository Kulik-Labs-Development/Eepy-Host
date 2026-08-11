from pydantic import BaseModel, Field


# MCPTemplate schemas (for template library browsing and admin management)
class TemplateConfigSchema(BaseModel):
    name_display: str = Field(..., description="User-given label for this integration")
    
    def to_template_schema(self, config_fields: dict):
        """Generate form field schema from input data"""
        return {
            "type": "object",
            "properties": config_fields,
            "required": [field_name for field_name in config_fields if not Field(default=None)] 
        }


class MCPTemplateResponse(BaseModel):
    id: str  # slug identifier (e.g., "happyfox")  
    name: str
    description: str
    
    config_schema: dict = Field(..., description="Form specification for credential entry fields")
    
    approved_by_admin: bool
    enabled_global: bool


class MCPTemplateRequestInput(BaseModel):
    requested_name: str = Field(..., min_length=2)
    description_purpose: str = Field(..., min_length=10)  # Minimum length for meaningful admin review


# UserMCPConfig schemas (for connection wizard and credential management)

class MCPCredentialsSchema(BaseModel):
    """Base schema template - individual integrations will override with their own specific fields"""
    
    def get_form_fields(self, integration_name: str) -> dict:
        # Override in subclasses for each MCP service's actual requirements (HappyFox needs 3+ fields etc.)
        return {}


class HappyFoxyCredentials(MCPCredentialsSchema):
    """Specific credentials schema for HappyFox MCP server - ENCRYPTED at rest ⚠️🔒"""
    
    HAPPYFOX_DOMAIN: str = Field(..., min_length=1)  # e.g., "mycompany.happyfox.com" or .net
    
    HAPPYFOX_API_KEY: str = Field(...)  # Password field (masked in UI 🔐💜✅)  
    HAPPYFOX_AUTH_CODE: str = Field(...) # Password field (masked in UI 🔒🔑❗⚠️


# Admin-only schemas for template approval/rejection workflow

class TemplateApprovalInput(BaseModel):
    approve: bool  # True to add to library, False to reject  
    admin_notes: str | None = Field(None, min_length=0)  # Optional feedback if rejected ✅📋💜✨


# Proxy endpoint input schemas (for MCP tool routing - specific per template type)

class MCPToolRequest(BaseModel):
    """Base schema for all proxy tool calls"""
    
    params: dict = Field(..., description="Tool-specific parameters passed through to external API")  # 🔒✅⏺️❗


# HappyFox-specific tool schemas (will be expanded as we implement each MCP capability)

class ListTicketsParams(BaseModel):
    status_filter: str | None = None  
    search_query: str | None = None  
    page_size: int = Field(default=20, ge=1, le=100)  # Context-safe limit ✅✨⏺️


class AddTicketUpdateParams(BaseModel):
    ticket_id: int = Field(..., gt=0) 
    text: str = Field(...)  
    is_private_note: bool = False  # Flag for internal staff notes only ❌ NOT sent to contact 🛡️✅💜  
    status_change_id: int | None = None  # Optional status change in same call ✅🔧✨
