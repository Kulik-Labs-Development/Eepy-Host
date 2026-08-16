from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPConfigRegister(BaseModel):
    credentials_json: Dict[str, str] = Field(..., description="Template credentials (encrypted server-side before storage)")
    display_name: Optional[str] = Field(None, description="User-given label for this connection")
    template_id: Optional[str] = Field("happyfox", description="Template slug from the MCP library")


class MCPConfigOut(BaseModel):
    id: int
    template_name: str
    name_display: Optional[str]
    is_active: bool
    last_used_at: Optional[str]
    created_at: Optional[str]


class MCPProxyRequest(BaseModel):
    """Body for the generic MCP proxy. `tool` selects the operation;
    `params` carries tool-specific arguments."""

    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)
