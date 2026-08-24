"""Test fixtures.

Environment must be set BEFORE any backend module is imported (auth.py and
database.py read env at import time), so this is done at conftest import time.
A throwaway SQLite file is used: no external PostgreSQL needed in CI.
"""

import os
import sys
import tempfile

# Unique throwaway DB per test session.
_tmp_dir = tempfile.mkdtemp(prefix="eepy-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_dir}/eepy_test.db")
# 32+ bytes: satisfies PyJWT's minimum HMAC key length for HS256.
os.environ.setdefault("SECRET_KEY", "test-secret-key-ci-only-32-bytes-min")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """FastAPI test client for the full application (SQLite-backed).

    Used as a context manager on purpose: that runs the app lifespan (the MCP
    stream session manager's run() context must be active for /api/mcp/mcp,
    and the sidecar reaper gets its startup hook), with ONE portal/loop for
    the whole session.
    """
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Shared MCP bridge fixtures (fake stdio sidecar template + connected user)
# ---------------------------------------------------------------------------
FAKE_CREDS = {"FAKE_DOMAIN_FIELD": "fake.example.com", "FAKE_API_KEY": "fake-key-123", "FAKE_AUTH_CODE": "fake-token-456"}


@pytest.fixture(scope="module")
def fake_template_id():
    """Register a fake mcp-server template directly in the DB."""
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    template_id = "fake-mcp-test"
    fake_path = os.path.join(os.path.dirname(__file__), "fake_mcp_server.py")
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="Fake MCP Test",
            description="Test-only template served by the fake stdio MCP server.",
            config_schema={
                "category": "Test",
                "type": "object",
                "properties": {
                    "FAKE_DOMAIN_FIELD": {"type": "string", "label": "Domain", "required": True},
                    "FAKE_API_KEY": {"type": "password", "label": "API Key", "required": True},
                    "FAKE_AUTH_CODE": {"type": "password", "label": "Auth Code", "required": True},
                },
                "required": ["FAKE_DOMAIN_FIELD", "FAKE_API_KEY", "FAKE_AUTH_CODE"],
            },
            runtime="mcp-server",
            runtime_config={
                "command": [sys.executable, fake_path],
                "env": {"PYTHONUNBUFFERED": "1"},
                "env_mapping": {
                    "FAKE_DOMAIN_FIELD": "FAKE_DOMAIN",
                    "FAKE_API_KEY": "FAKE_API_KEY",
                    "FAKE_AUTH_CODE": "FAKE_API_TOKEN",
                },
                "test_tool": {"name": "list_items", "arguments": {"limit": 1}},
            },
            approved_by_admin=True,
            enabled_global=True,
        )
        db.add(t)
        db.commit()
    finally:
        db.close()
    return template_id


@pytest.fixture(scope="module")
def auth_user(client, fake_template_id):
    """A superuser account with the fake template connected (JWT + tool key)."""
    import random

    from database import SessionLocal, User, UserRole

    username = f"bridgetest{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "bridge-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "bridge-password-1"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # Promote to superuser for the discovery tests.
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        u.role = UserRole.SUPERUSER
        db.commit()
    finally:
        db.close()

    r = client.post("/api/mcp/config/register",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"template_id": fake_template_id, "credentials_json": FAKE_CREDS})
    assert r.status_code == 200, r.text

    r = client.post("/api/mcp/api-keys",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": "bridge-test"})
    assert r.status_code == 200, r.text
    eekey = r.json()["key"]

    yield {"token": token, "eekey": eekey, "username": username}

    # Cleanup: kill any leftover sidecars.
    from api import mcp_bridge
    mcp_bridge.shutdown_all_instances()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the in-memory slowapi storage between tests.

    All test traffic shares one client identity ('testclient'), so without
    this the 5/hour signup limit fires on the 6th signup across the whole
    session and every later fixture setup 429s.
    """
    import main

    main.limiter.reset()
    yield
