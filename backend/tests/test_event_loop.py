"""Event-loop regression guards.

Rule: any route/dependency that only does synchronous work (SQLAlchemy,
crypto, subprocess/docker API) MUST be a plain `def` so FastAPI runs it in
the threadpool — an `async def` doing sync I/O blocks the event loop and
serializes the whole app under load. The async endpoints that remain are
only the ones that genuinely await non-blocking I/O (MCP bridge sessions,
httpx upstream calls, request body streaming).
"""

import inspect
import os
import random
import sys

import pytest


def _assert_sync(module, names: list[str]) -> None:
    for name in names:
        fn = getattr(module, name)
        assert not inspect.iscoroutinefunction(fn), (
            f"{module.__name__}.{name} must be a sync `def` (threadpool) — "
            f"async def with sync I/O blocks the event loop"
        )


def test_main_endpoints_and_deps_are_sync():
    import main

    _assert_sync(main, [
        "root", "health",
        "get_current_user", "get_superuser",
        "signup", "login",
        "get_profile", "update_profile", "upload_avatar",
        "list_all_users", "get_system_logs", "update_user_role",
        "reset_user_password", "delete_user_by_admin", "update_user_details",
        "update_mcp_template_runtime",
    ])


def test_mcp_endpoints_and_deps_are_sync():
    from api import mcp_endpoints

    _assert_sync(mcp_endpoints, [
        "get_current_user", "get_current_user_or_key", "get_proxy_context",
        "create_tool_api_key", "list_tool_api_keys", "revoke_tool_api_key",
        "list_templates", "register_mcp_config", "list_my_configs",
        "delete_mcp_config", "mcp_proxy_url", "unified_openapi_spec",
    ])


def test_bridge_async_entry_points_offload_blocking_work():
    """The async bridge entry points must delegate blocking work (spawns,
    kills, liveness, docker) via asyncio.to_thread — verified by source so a
    regression to a direct blocking call fails the suite."""
    from api import mcp_bridge

    for fn in (mcp_bridge.spawn_instance, mcp_bridge.acquire_instance,
               mcp_bridge.bridge_call, mcp_bridge.discover_tools_for_template):
        src = inspect.getsource(fn)
        assert "to_thread" in src, f"{fn.__name__} must offload blocking work via asyncio.to_thread"


def test_truly_async_endpoints_stay_async():
    """These await non-blocking I/O (bridge sessions / httpx) — flipping them
    to sync `def` would break the awaits."""
    import main
    from api import mcp_endpoints

    assert inspect.iscoroutinefunction(mcp_endpoints.mcp_proxy)
    assert inspect.iscoroutinefunction(mcp_endpoints.test_mcp_connection)
    assert inspect.iscoroutinefunction(main.discover_mcp_tools)
    assert inspect.iscoroutinefunction(mcp_endpoints._proxy_mcp_server)
    assert inspect.iscoroutinefunction(mcp_endpoints._proxy_native)


@pytest.fixture()
def loop_fake_template(client):
    """A stdio fake-server template for the hot-path functional guard."""
    from database import SessionLocal
    from models.mcp_models import MCPTemplate

    template_id = "loop-fake-template"
    fake_path = os.path.join(os.path.dirname(__file__), "fake_mcp_server.py")
    db = SessionLocal()
    try:
        existing = db.query(MCPTemplate).filter(MCPTemplate.id == template_id).first()
        if existing:
            db.delete(existing)
            db.commit()
        t = MCPTemplate(
            id=template_id,
            name="Loop Fake",
            description="Event-loop regression template (fake stdio server).",
            config_schema={
                "type": "object",
                "properties": {"FAKE_API_KEY": {"type": "password", "label": "API Key", "required": True}},
                "required": ["FAKE_API_KEY"],
            },
            runtime="mcp-server",
            runtime_config={
                "command": [sys.executable, fake_path],
                "env_mapping": {"FAKE_API_KEY": "FAKE_API_KEY"},
                "test_tool": {"name": "list_items", "arguments": {"limit": 1}},
            },
            approved_by_admin=True,
            enabled_global=True,
        )
        db.add(t)
        db.commit()
    finally:
        db.close()
    yield template_id
    from api import mcp_bridge
    mcp_bridge.shutdown_all_instances()


def _mk_user(client, prefix: str) -> str:
    username = f"{prefix}{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "loop-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "loop-password-1"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_proxy_hot_path_works_through_sync_dependency(client, loop_fake_template):
    """Functional guard: the get_proxy_context dependency (threadpool) still
    serves the hot proxy path end-to-end (auth + template + creds + bridge)."""
    token = _mk_user(client, "loopproxy")
    r = client.post("/api/mcp/config/register",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"template_id": loop_fake_template,
                          "credentials_json": {"FAKE_API_KEY": "fake-key-123"}})
    assert r.status_code == 200, r.text

    r = client.post(f"/api/mcp/proxy/{loop_fake_template}/list_items",
                    headers={"Authorization": f"Bearer {token}"}, json={"limit": 1})
    assert r.status_code == 200, r.text
    assert "api=fake-key-123" in r.json()["data"]

    # Connection test route goes through the same dependency.
    r = client.post(f"/api/mcp/config/{loop_fake_template}/test",
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


def test_profile_patch_accepts_full_name_body(client):
    """Contract guard for the Pydantic-body update_profile (frontend sends
    {"full_name": ...}, including null)."""
    token = _mk_user(client, "loopprofile")

    r = client.patch("/user/profile",
                     headers={"Authorization": f"Bearer {token}"},
                     json={"full_name": "Loop Guard"})
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Loop Guard"

    # null = no-op (frontend sends null when the field was never set)
    r = client.patch("/user/profile",
                     headers={"Authorization": f"Bearer {token}"},
                     json={"full_name": None})
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Loop Guard"
