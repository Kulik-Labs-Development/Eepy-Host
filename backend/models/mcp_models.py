from sqlalchemy import Column, Integer, String, JSON, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum


Base = declarative_base()


class MCPTemplate(Base):
    """Admin-approved MCP server templates in the library. Users cannot add custom servers directly."""
    
    __tablename__ = 'mcp_templates'

    id = Column(String, primary_key=True)  # slug identifier (e.g., "happyfox")
    name = Column(String, nullable=False)  # Display name for UI
    description = Column(Text, nullable=False)  # Human-readable capabilities
    
    config_schema = Column(JSON, nullable=False)  # Form field specs: {type, properties, required}
    
    image_tag = Column(String, nullable=True)  # Docker reference if needed (e.g., ghcr.io/glitch3dpenguin/happyfox-mcp)
    
    approved_by_admin = Column(Boolean, default=False, nullable=False)  # Admin approval gate ✅
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
    
    credentials_json = Column(JSON, nullable=False)  # ENCRYPTED using Fernet + MCP_ENCRYPTION_KEY env var ⚠️ NEVER PLAINTEXT 🔒
    
    is_active = Column(Boolean, default=True, nullable=False)         # Toggle on/off without deleting config ❌ NO SOFT DELETES! ✅⏺️❗
    last_used_at = Column(DateTime, nullable=True)                     # Usage tracking for monetization later 💰📊✅
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


class MCPTemplateRequest(Base):
    """User-requested integration pipeline: start of monetization flow when approved."""
    
    __tablename__ = 'mcp_template_requests'

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey('users.id'), nullable=False)  # Who requested this? 🔒✅⏺️
    
    requested_name = Column(String, nullable=False)  # What the user wants added to library ✅💜  
    description_purpose = Column(Text, nullable=False)  # Why they need it (use case for admin review/rejection)
    
    status = Column(String, default='pending', nullable=False)  # Enum: 'pending', 'approved', 'rejected' 🛡️⏺️
    
    admin_notes = Column(Text, nullable=True)              # Optional feedback if rejected ✅📋💜✨
