"""CORS + Open WebUI compatibility.

Open WebUI (a browser app) fetches the spec AND calls the proxy from ITS OWN
origin, so preflights must pass for arbitrary self-hosted origins. Open WebUI
also appends "/openapi.json" to whatever URL the user pastes, so the spec must
be served at the doubled path too. (Regression: production returned
"OPTIONS /api/mcp/openapi.json/openapi.json" 400 + a missing
Access-Control-Allow-Origin on the preflight from https://ai.shuvi.io.)
"""

EXTERNAL_ORIGIN = "https://ai.shuvi.io"


def _preflight(method="GET", request_headers=None):
    headers = {
        "Origin": EXTERNAL_ORIGIN,
        "Access-Control-Request-Method": method,
    }
    if request_headers:
        headers["Access-Control-Request-Headers"] = request_headers
    return headers


def test_preflight_passes_for_external_origin(client):
    r = client.options("/api/mcp/openapi.json", headers=_preflight())
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == "*"


def test_preflight_passes_for_proxy_post_with_authorization(client):
    """The actual tool-call path: POST + Authorization must be prefetched OK,
    or Open WebUI's chat-side tool calls die in the browser."""
    r = client.options(
        "/api/mcp/proxy/happyfox/list_tickets",
        headers=_preflight(method="POST", request_headers="authorization,content-type"),
    )
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == "*"
    assert "post" in r.headers.get("access-control-allow-methods", "").lower()
    allow_headers = r.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allow_headers
    assert "content-type" in allow_headers


def test_spec_get_from_external_origin_carries_cors_headers(client):
    r = client.get("/api/mcp/openapi.json", headers={"Origin": EXTERNAL_ORIGIN})
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.json()["openapi"].startswith("3.0")


def test_openwebui_appended_spec_path_serves_same_spec(client):
    """Open WebUI appends /openapi.json to the pasted URL, so a user who pasted
    the spec URL (per the older instructions) gets the spec back at the
    doubled path instead of a 400/404."""
    canonical = client.get("/api/mcp/openapi.json").json()
    appended = client.get(
        "/api/mcp/openapi.json/openapi.json", headers={"Origin": EXTERNAL_ORIGIN}
    )
    assert appended.status_code == 200, appended.text
    assert appended.headers["access-control-allow-origin"] == "*"
    spec = appended.json()
    assert spec["openapi"].startswith("3.0")
    assert set(spec["paths"]) == set(canonical["paths"])
