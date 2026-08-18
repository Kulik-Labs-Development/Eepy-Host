from typing import Any

from pydantic import BaseModel, Field


class MCPConfigRegister(BaseModel):
    credentials_json: dict[str, str] = Field(..., description="Template credentials (encrypted server-side before storage)")
    display_name: str | None = Field(None, description="User-given label for this connection")
    template_id: str | None = Field("happyfox", description="Template slug from the MCP library")


class MCPConfigOut(BaseModel):
    id: int
    template_name: str
    name_display: str | None
    is_active: bool
    last_used_at: str | None
    created_at: str | None


class MCPProxyRequest(BaseModel):
    """Body for the generic MCP proxy. `tool` selects the operation;
    `params` carries tool-specific arguments."""

    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
