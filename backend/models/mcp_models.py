from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text

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


class MCPUserToolKey(Base):
    """User-scoped, revocable API keys for external tool servers (e.g. Open WebUI).

    A single key authenticates the WHOLE Eepy tool surface for one user — every
    integration they have connected (HappyFox today, future templates tomorrow).
    Users make ONE connection in Open WebUI; new Eepy servers appear automatically
    with no re-import.

    Security:
      - Long-lived but narrow: accepted ONLY on /api/mcp/proxy/* and
        /api/mcp/config/* — never on /user/*, /auth/*, /superuser/*, billing, etc.
      - Per-call the proxy still requires the user to have an active connection to
        the requested template, so a key can only ever reach integrations the
        owner has actually connected.
      - Stored only as a SHA-256 hash; plaintext shown ONCE at creation.
      - Revocable from the Eepy UI; a revoked key is rejected on the next call.
    """

    __tablename__ = 'mcp_user_tool_keys'

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)

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
