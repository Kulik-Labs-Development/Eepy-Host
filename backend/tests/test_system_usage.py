"""Unit tests for api.system_usage — the pure computation + classification
helpers. fetch_usage itself is covered by the live Portainer probes that
pre-dated this page; these lock the math and the platform/sidecar split so
a future refactor can't silently break either. No DB, no network."""

from api.system_usage import (
    classify_containers,
    compute_cpu_percent,
    compute_memory,
    compute_network,
    sidecar_expiry,
)
from database import SessionLocal  # noqa: E402  (env is set by conftest at import time)

# --- CPU ------------------------------------------------------------------

def test_cpu_percent_delta_math():
    # cpu delta 1e7 ns, system delta 1e10 ns, 8 online cpus
    # -> 100 * (1e7 / 1e10) * 8 = 0.8 (% of one core, Docker convention)
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 100_000_000},
            "system_cpu_usage": 1_000_000_000_000,
            "online_cpus": 8,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 90_000_000},
            "system_cpu_usage": 990_000_000_000,
        },
    }
    assert compute_cpu_percent(stats) == 0.8


def test_cpu_percent_one_full_core_is_100():
    # One container pinned at exactly one full core of an 8-core box reads
    # 100% under Docker's per-core convention (cpu delta = 1/8 of system).
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 10_000_000_000},
            "system_cpu_usage": 80_000_000_000,
            "online_cpus": 8,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 0},
            "system_cpu_usage": 0,
        },
    }
    assert compute_cpu_percent(stats) == 100.0


def test_cpu_percent_degenerate_zero_delta():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 100,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 100,
        },
    }
    assert compute_cpu_percent(stats) is None


def test_cpu_percent_missing_precpu_stats():
    stats = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 100,
        },
    }
    assert compute_cpu_percent(stats) is None


# --- Memory ---------------------------------------------------------------

def test_memory_working_set_subtracts_cache():
    stats = {"memory_stats": {"usage": 1000, "limit": 2000, "stats": {"cache": 250}}}
    assert compute_memory(stats) == {
        "usage_bytes": 1000,
        "working_set_bytes": 750,
        "limit_bytes": 2000,
    }


def test_memory_no_cache_working_equals_usage():
    stats = {"memory_stats": {"usage": 1000, "limit": 2000, "stats": {}}}
    assert compute_memory(stats)["working_set_bytes"] == 1000


def test_memory_missing_limit_is_zero():
    stats = {"memory_stats": {"usage": 1000}}
    assert compute_memory(stats) == {
        "usage_bytes": 1000,
        "working_set_bytes": 1000,
        "limit_bytes": 0,
    }


# --- Network --------------------------------------------------------------

def test_network_sums_all_interfaces():
    stats = {
        "networks": {
            "eth0": {"rx_bytes": 100, "tx_bytes": 10},
            "eth1": {"rx_bytes": 200, "tx_bytes": 20},
        }
    }
    assert compute_network(stats) == {"rx_bytes": 300, "tx_bytes": 30}


def test_network_no_networks_is_zero():
    assert compute_network({}) == {"rx_bytes": 0, "tx_bytes": 0}


# --- Classification ---------------------------------------------------------

def _c(name: str) -> dict:
    return {"id": name, "name": name, "state": "running", "status": "Up", "created": 0}


def test_classify_sidecar_exact_name_wins_over_prefix():
    containers = [
        _c("eepy-backend"),
        _c("eepy-frontend"),
        _c("eepy-db"),
        _c("eepy-mcp-abc"),
        _c("kipple-api-1"),
    ]
    platform, sidecars = classify_containers(containers, {"eepy-mcp-abc"})
    assert [c["name"] for c in platform] == ["eepy-backend", "eepy-frontend", "eepy-db"]
    assert [c["name"] for c in sidecars] == ["eepy-mcp-abc"]


def test_classify_excludes_other_stacks():
    containers = [_c("eepy-backend"), _c("kipple-api-1"), _c("immich-app")]
    platform, sidecars = classify_containers(containers, set())
    assert [c["name"] for c in platform] == ["eepy-backend"]
    assert sidecars == []

# --- Sidecar idle expiry ------------------------------------------------

def test_sidecar_expiry_running_carries_a_deadline():
    assert sidecar_expiry(1000.0, "running", idle_timeout=300.0) == (1000.0, 1300.0)


def test_sidecar_expiry_non_running_keeps_stamp_no_deadline():
    assert sidecar_expiry(1000.0, "gone", idle_timeout=300.0) == (1000.0, None)
    assert sidecar_expiry(None, "gone", idle_timeout=300.0) == (None, None)




# --- Per-user endpoint (GET /user/sidecars) ------------------------------

def _signup_user(client, prefix):
    import random

    username = f"{prefix}{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com",
        "password": "user-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={
        "username": username, "password": "user-password-1"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _delete_settings_row():
    from models.system_settings import SystemSettings

    db = SessionLocal()
    try:
        db.query(SystemSettings).filter(SystemSettings.id == 1).delete()
        db.commit()
    finally:
        db.close()


def test_user_sidecars_no_platform_source_400(client):
    """A regular user with NO platform data source (no settings row, no
    superuser Portainer config) gets the same 400 not_configured body as
    the superuser page - and never the caller's own connection."""
    _delete_settings_row()
    token = _signup_user(client, "usageslice")
    r = client.get("/user/sidecars", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "not_configured"


def test_user_sidecars_uses_the_platform_settings_row(client):
    """With a settings row (here a bogus one pointing at a closed port on a
    public host), the user endpoint resolves the PLATFORM source and fails
    at the Portainer step with 502 - not 400 (source IS configured) and not
    the caller's own MCP config."""
    from models.system_settings import SystemSettings
    from utils.crypto import encrypt_secret

    _delete_settings_row()
    db = SessionLocal()
    try:
        db.add(SystemSettings(
            id=1, backend="portainer",
            portainer_url="https://93.184.216.34:9",  # closed port on a public host: refuses fast
            portainer_api_key_enc=encrypt_secret("bogus-platform-key"),
            environment_id="20"))
        db.commit()
    finally:
        db.close()
    token = _signup_user(client, "usageslice2")
    try:
        r = client.get("/user/sidecars", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 502, r.text
    finally:
        _delete_settings_row()

