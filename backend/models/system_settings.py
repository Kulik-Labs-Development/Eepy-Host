from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from database import Base


def _utcnow():
    return datetime.now(UTC)


class SystemSettings(Base):
    """SINGLE ROW (id=1): where the System Usage page reads container stats from.

    `backend` picks the driver: "portainer" (the current default) or "arcane"
    (the planned successor, same row shape). The *_api_key_enc columns hold
    Fernet tokens - NEVER plaintext at rest, and NEVER returned in any API
    response (the settings endpoints surface only the *_api_key_set booleans,
    i.e. the truthiness of the stored tokens). environment_id is a STRING
    (Portainer ints arrive stringified in some paths; Arcane ids are "0"/"1"):
    NULL = auto (single visible environment).
    """

    __tablename__ = 'system_settings'

    id = Column(Integer, primary_key=True, default=1)  # single-row table (always 1)
    backend = Column(String(16), nullable=False, default="portainer")  # "portainer" | "arcane"

    portainer_url = Column(Text, nullable=True)
    portainer_api_key_enc = Column(Text, nullable=True)  # Fernet token of the API key (never plaintext)
    portainer_tls_verify = Column(Boolean, nullable=False, default=True)

    arcane_url = Column(Text, nullable=True)
    arcane_api_key_enc = Column(Text, nullable=True)  # Fernet token of the API key (never plaintext)

    environment_id = Column(String(32), nullable=True)  # string env id; NULL = auto-pick the single environment
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, onupdate=_utcnow)
