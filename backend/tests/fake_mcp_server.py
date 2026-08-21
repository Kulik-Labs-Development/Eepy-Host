"""A minimal fake MCP server used by the sidecar-bridge tests.

Speaks stdio MCP (same protocol the real upstream servers speak). Reads
FAKE_API_KEY / FAKE_API_TOKEN from its environment - the bridge is expected
to have mapped the user's encrypted credentials into exactly those env vars,
which is the whole point of the modular path.
"""

import json
import os
import sys

API_VERSION = "1.0"

# Mirror the real upstream servers' transport selection (e.g. happyfox_mcp.py):
# an HTTP-mode server never speaks stdio. If the bridge selects the wrong
# (docker-oriented) static env for the subprocess backend, the sidecar exits
# immediately and the handshake test fails instead of passing silently.
if os.getenv("MCP_TRANSPORT", "stdio").lower() in ("streamable-http", "sse"):
    sys.stderr.write(f"fake-mcp-server: MCP_TRANSPORT={os.getenv('MCP_TRANSPORT')} is not supported on stdio; exiting\n")
    sys.exit(3)


def handle(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-mcp", "version": API_VERSION},
        }}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": "list_items", "description": "List fake items.",
             "inputSchema": {"type": "object", "properties": {
                 "limit": {"type": "integer", "description": "Max items."}},
                 "required": []}},
            {"name": "create_item", "description": "Create a fake item.",
             "inputSchema": {"type": "object", "properties": {
                 "name": {"type": "string", "description": "Item name."}},
                 "required": ["name"]}},
            {"name": "bad_item", "description": "Always fails (test error path).",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
            {"name": "check_env", "description": "List env var names (test helper).",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
        ]}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        if name == "list_items":
            if not os.environ.get("FAKE_API_KEY"):
                return {"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": "Error 401: missing credentials"}],
                    "isError": True}}
            limit = int(args.get("limit", 3))
            items = [f"item-{i}" for i in range(1, limit + 1)]
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": "api=" + os.environ["FAKE_API_KEY"]
                             + " token=" + os.environ.get("FAKE_API_TOKEN", "")
                             + " items=" + ",".join(items)}],
                "isError": False}}
        if name == "create_item":
            if "name" not in args:
                return {"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": "Error 400: 'name' is required"}],
                    "isError": True}}
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"created: {args['name']}"}],
                "isError": False}}
        if name == "bad_item":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": "Error 500: upstream exploded"}],
                "isError": True}}
        if name == "check_env":
            # Security test helper: report which env var names the sidecar sees.
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": " ".join(sorted(os.environ.keys()))}],
                "isError": False}}
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"unknown tool {name}"}}
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
