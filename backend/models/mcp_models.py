from sqlalchemy import Column, Integer, String, JSON, Boolean, DateTime, ForeignKey, Text
from datetime import datetime

from database import Base


class MCPTemplate(Base):
    """Admin-approved MCP server templates in the library. Users cannot add custom servers directly."""

    __tablename__ = 'mcp_templates'

    id = Column(String, primary_key=True)  # slug identifier (e.g., "happyfox")
    name = Column(String, nullable=False)  # Display name for UI
    description = Column(Text, nullable=False)  # Human-readable capabilities

    config_schema = Column(JSON, nullable=False)  # Form field specs: {type, properties, required}

    image_tag = Column(String, nullable=True)  # Docker reference if needed (e.g., ghcr.io/glitch3dpenguin/happyfox-mcp)

    approved_by_admin = Column(Boolean, default=False, nullable=False)  # Admin approval gate
    enabled_global = Column(Boolean, default=True, nullable=False)       # Feature flag for global enable/disable

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


class UserMCPConfig(Base):
    """User configuration mappings: one entry per user + template combo. Credentials are ENCRYPTED at rest."""

    __tablename__ = 'user_mcp_configs'

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)  # Reference to User table

    template_name = Column(String, nullable=False)  # e.g., "happyfox", "gcal" etc. (FK reference as string for flexibility)

    name_display = Column(String, nullable=True)    # User-given label like "My Support Queue" or defaults from MCPTemplate

    credentials_json = Column(Text, nullable=False)  # Fernet-encrypted blob. NEVER plaintext at rest.

    is_active = Column(Boolean, default=True, nullable=False)         # Toggle on/off without deleting config
    last_used_at = Column(DateTime, nullable=True)                     # Usage tracking for monetization later

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


class MCPToolApiKey(Base):
    """Scoped, revocable API keys for Open WebUI / third-party tool integrations.

    A tool API key is:
      - Long-lived (no short-lived expiry) but scoped to ONE template for ONE user.
      - Accepted only on the /api/mcp/proxy/* routes (never on /user/*, /auth/*, /superuser/*).
      - Stored only as a SHA-256 hash. Plaintext is shown ONCE at creation and never persisted.
      - Revocable from the Eepy UI; a revoked key is rejected on the next call.

    This is what the user pastes as the Bearer token in Open WebUI's Tool Server
    connection. If it leaks, the blast radius is one user's one tool integration,
    not the entire Eepy account, and the owner can kill it instantly.
    """

    __tablename__ = 'mcp_tool_api_keys'

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    template_name = Column(String, nullable=False)  # e.g. 'happyfox' — key is scoped to this integration

    name = Column(String, nullable=False, default='Open WebUI')  # Label shown in the Eepy UI

    key_hash = Column(String, unique=True, index=True, nullable=False)  # sha256 of the plaintext key
    key_prefix = Column(String, nullable=False)  # First 8 chars of plaintext, for UI display (not secret)

    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class MCPTemplateRequest(Base):
    """User-requested integration pipeline: start of monetization flow when approved."""

    __tablename__ = 'mcp_template_requests'

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    requested_name = Column(String, nullable=False)
    description_purpose = Column(Text, nullable=False)

    status = Column(String, default='pending', nullable=False)  # 'pending' | 'approved' | 'rejected'
    admin_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
