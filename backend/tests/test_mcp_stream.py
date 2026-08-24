"""Tests for the native MCP (streamable-HTTP) endpoint at /api/mcp/mcp.

The endpoint is the "AI Platform connector": any MCP client (opencode,
Claude Desktop, ...) connects with a URL + Bearer token (session JWT OR
eekey_ Tool API Key) and gets tools/list + tools/call over the SAME
credential/bridge path as the REST proxy.

These tests speak raw JSON-RPC over the test client (the server runs in
stateless mode with JSON responses, so every request is self-contained).
"""

import json

import pytest


def _h(token: str) -> dict:
    # A real MCP client always accepts both media types; the server answers
    # application/json (stateless + json_response).
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _rpc(client, method: str, token: str, params: dict | None = None, rid: int = 1):
    payload = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post("/api/mcp/mcp", json=payload, headers=_h(token))


def _call(client, token: str, name: str, arguments: dict | None = None, rid: int = 1):
    return _rpc(client, "tools/call", token, {"name": name, "arguments": arguments or {}}, rid)


@pytest.fixture(scope="module")
def discovered(client, auth_user, fake_template_id):
    """Ensure the fake template has stored schemas (idempotent; the bridge
    tests already discovered it, but this file must not depend on that order)."""
    r = client.post(f"/superuser/mcp/templates/{fake_template_id}/discover",
                    headers={"Authorization": f"Bearer {auth_user['token']}"})
    assert r.status_code == 200, r.text
    return fake_template_id


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_mcp_stream_requires_auth(client, auth_user):
    r = client.post("/api/mcp/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1.0"}}},
                    headers={"Content-Type": "application/json",
                             "Accept": "application/json, text/event-stream"})
    assert r.status_code == 401, r.text

    r = _rpc(client, "initialize", "not-a-real-token",
             {"protocolVersion": "2025-06-18", "capabilities": {},
              "clientInfo": {"name": "test", "version": "1.0"}})
    assert r.status_code == 401, r.text


def test_mcp_stream_initialize_with_session_jwt(client, auth_user):
    r = _rpc(client, "initialize", auth_user["token"],
             {"protocolVersion": "2025-06-18", "capabilities": {},
              "clientInfo": {"name": "test", "version": "1.0"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, body
    assert body["result"]["serverInfo"]["name"] == "eepy-host"
    assert "tools" in body["result"]["capabilities"]
    assert body["result"]["instructions"]


def test_mcp_stream_initialize_with_tool_key(client, auth_user):
    """The eekey scope was widened to the MCP stream endpoint (proxy-equivalent)."""
    r = _rpc(client, "initialize", auth_user["eekey"],
             {"protocolVersion": "2025-06-18", "capabilities": {},
              "clientInfo": {"name": "test", "version": "1.0"}})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "eepy-host"


def test_mcp_stream_other_routes_still_jwt_or_scoped(client, auth_user, fake_template_id):
    """Widening the stream path must not widen eekey anywhere else."""
    assert client.get("/api/mcp/templates/list",
                      headers={"Authorization": f"Bearer {auth_user['eekey']}"}).status_code == 401
    # JWT works on the stream endpoint too (both auth paths coexist).
    assert _rpc(client, "initialize", auth_user["token"],
                {"protocolVersion": "2025-06-18", "capabilities": {},
                 "clientInfo": {"name": "test", "version": "1.0"}}).status_code == 200


# ---------------------------------------------------------------------------
# tools/list (per-user, stateless)
# ---------------------------------------------------------------------------
def test_mcp_stream_lists_only_active_connections(client, auth_user, fake_template_id, discovered):
    r = _rpc(client, "tools/list", auth_user["token"], {})
    assert r.status_code == 200, r.text
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}

    # The connected fake template is listed with its DISCOVERED schemas.
    for tool in ("list_items", "create_item", "bad_item", "check_env"):
        assert f"{fake_template_id}__{tool}" in tools, sorted(tools)
    create = tools[f"{fake_template_id}__create_item"]
    assert "name" in create["inputSchema"]["properties"]
    assert create["inputSchema"]["required"] == ["name"]
    assert tools[f"{fake_template_id}__list_items"]["inputSchema"]["properties"]["limit"]["type"] == "integer"

    # The status helper is always present.
    assert "eepy__status" in tools

    # Nothing the user has NOT connected (HappyFox is approved+enabled but
    # auth_user has no active connection to it).
    assert not any(n.startswith("happyfox__") for n in tools), sorted(tools)
    assert not any(n.startswith("ebay__") for n in tools)


def test_mcp_stream_stateless_list_without_initialize(client, auth_user, fake_template_id, discovered):
    """Stateless mode pre-initializes each request's server session: a fresh
    tools/list with no prior initialize must work (any replica can serve it)."""
    r = _rpc(client, "tools/list", auth_user["eekey"], {})
    assert r.status_code == 200, r.text
    assert any(t["name"] == f"{fake_template_id}__list_items" for t in r.json()["result"]["tools"])


def test_mcp_stream_lists_empty_for_user_without_connections(client, fake_template_id):
    import random

    username = f"mcplist{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "mcp-list-pass-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "mcp-list-pass-1"})
    token = r.json()["access_token"]

    r = _rpc(client, "tools/list", token, {})
    assert r.status_code == 200, r.text
    names = [t["name"] for t in r.json()["result"]["tools"]]
    assert names == ["eepy__status"], names  # only the built-in helper


# ---------------------------------------------------------------------------
# tools/call (bridge routing + error surfacing)
# ---------------------------------------------------------------------------
def test_mcp_stream_call_tool_with_jwt(client, auth_user, fake_template_id, discovered):
    r = _call(client, auth_user["token"], f"{fake_template_id}__list_items", {"limit": 2})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    text = result["content"][0]["text"]
    assert "api=fake-key-123" in text          # the user's decrypted creds reached the sidecar
    assert "token=fake-token-456" in text
    assert "items=item-1,item-2" in text


def test_mcp_stream_call_tool_with_tool_key(client, auth_user, fake_template_id, discovered):
    r = _call(client, auth_user["eekey"], f"{fake_template_id}__list_items", {"limit": 1})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    assert "api=fake-key-123" in result["content"][0]["text"]


def test_mcp_stream_upstream_error_is_error_result(client, auth_user, fake_template_id, discovered):
    """Upstream tool errors surface as isError MCP results (not transport errors)."""
    r = _call(client, auth_user["token"], f"{fake_template_id}__bad_item")
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is True
    assert "Error 500: upstream exploded" in result["content"][0]["text"]


def test_mcp_stream_unknown_tool_is_error_result(client, auth_user, fake_template_id, discovered):
    r = _call(client, auth_user["token"], f"{fake_template_id}__no_such_tool")
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is True
    assert "Unknown tool" in result["content"][0]["text"]


def test_mcp_stream_unconnected_template_is_error_result(client, auth_user, discovered):
    """Per-call the user must have an ACTIVE connection (same rule as the proxy)."""
    r = _call(client, auth_user["token"], "happyfox__list_tickets")
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is True
    assert "No active happyfox connection" in result["content"][0]["text"]


def test_mcp_stream_unknown_template_is_error_result(client, auth_user):
    r = _call(client, auth_user["token"], "not-a-template__some_tool")
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is True
    assert "Unknown template" in result["content"][0]["text"]


def test_mcp_stream_malformed_tool_name_is_error_result(client, auth_user):
    r = _call(client, auth_user["token"], "no_double_underscore_here")
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is True
    assert "Invalid tool name" in result["content"][0]["text"]


def test_mcp_stream_status_tool(client, auth_user, fake_template_id, discovered):
    r = _call(client, auth_user["token"], "eepy__status")
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    summary = json.loads(result["content"][0]["text"])
    connected = {c["template"]: c["tools"] for c in summary["connected_integrations"]}
    assert connected == {fake_template_id: 4}, summary


# ---------------------------------------------------------------------------
# Protocol hygiene
# ---------------------------------------------------------------------------
def test_mcp_stream_unknown_method_is_jsonrpc_error(client, auth_user):
    r = _rpc(client, "prompts/list", auth_user["token"], {})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" in body, body  # JSON-RPC error, not an HTTP failure
    assert body["error"]["code"] != 0


def test_mcp_stream_json_response_content_type(client, auth_user, discovered):
    r = _rpc(client, "tools/list", auth_user["token"], {})
    assert r.headers["content-type"].startswith("application/json")
