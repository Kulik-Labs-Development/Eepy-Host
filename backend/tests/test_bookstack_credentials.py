"""BookStack UX: the API token travels as ID + SECRET fields and is joined to
token_id:token_secret server-side (the sidecar's wire form); the legacy
combined field is still accepted; an empty pair on an EDIT keeps the stored
token; the prefill route returns only current non-secret schema keys."""

import random

from utils.crypto import decrypt_credentials


def _user(client):
    """A fresh signed-in user (the rate limiter resets per test)."""
    username = f"booktest{random.randint(100000, 999999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "book-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "book-password-1"})
    assert r.status_code == 200, r.text
    return {"token": r.json()["access_token"], "username": username}


def _register(client, token, creds):
    return client.post(
        "/api/mcp/config/register",
        headers={"Authorization": f"Bearer {token}"},
        json={"template_id": "bookstack", "credentials_json": creds},
    )


def _blob(username: str):
    from database import SessionLocal, User
    from models.mcp_models import UserMCPConfig

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        row = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user.id, UserMCPConfig.template_name == "bookstack")
            .first()
        )
        if row:
            db.expunge(row)
        return row
    finally:
        db.close()


def _creds(username: str) -> dict:
    row = _blob(username)
    assert row is not None
    return decrypt_credentials(row.credentials_json)


URL = "https://docs.example.com/api"


def test_register_id_and_secret_are_joined(client):
    u = _user(client)
    r = _register(client, u["token"], {
        "BOOKSTACK_URL": URL,
        "BOOKSTACK_TOKEN_ID": "12",
        "BOOKSTACK_TOKEN_SECRET": "s3cret",
    })
    assert r.status_code == 200, r.text
    creds = _creds(u["username"])
    assert creds["BOOKSTACK_TOKEN"] == "12:s3cret"
    assert "BOOKSTACK_TOKEN_ID" not in creds
    assert "BOOKSTACK_TOKEN_SECRET" not in creds
    assert creds["BOOKSTACK_URL"] == URL


def test_register_legacy_combined_token_still_accepted(client):
    u = _user(client)
    r = _register(client, u["token"], {"BOOKSTACK_URL": URL, "BOOKSTACK_TOKEN": "12 : s3cret"})
    assert r.status_code == 200, r.text
    assert _creds(u["username"])["BOOKSTACK_TOKEN"] == "12:s3cret"


def test_register_half_a_pair_is_rejected(client):
    u = _user(client)
    r = _register(client, u["token"], {"BOOKSTACK_URL": URL, "BOOKSTACK_TOKEN_ID": "12"})
    assert r.status_code == 400
    assert "both" in r.json()["detail"].lower()


def test_register_empty_pair_without_stored_token_is_rejected(client):
    u = _user(client)
    r = _register(client, u["token"], {
        "BOOKSTACK_URL": URL,
        "BOOKSTACK_TOKEN_ID": "",
        "BOOKSTACK_TOKEN_SECRET": "",
    })
    assert r.status_code == 400


def test_register_empty_pair_on_edit_keeps_stored_token(client):
    u = _user(client)
    r = _register(client, u["token"], {
        "BOOKSTACK_URL": URL,
        "BOOKSTACK_TOKEN_ID": "7",
        "BOOKSTACK_TOKEN_SECRET": "longsecret",
    })
    assert r.status_code == 200, r.text
    r = _register(client, u["token"], {
        "BOOKSTACK_URL": URL,
        "BOOKSTACK_TOKEN_ID": "",
        "BOOKSTACK_TOKEN_SECRET": "",
    })
    assert r.status_code == 200, r.text
    assert _creds(u["username"])["BOOKSTACK_TOKEN"] == "7:longsecret"


def test_prefill_returns_only_current_non_secret_fields(client):
    u = _user(client)
    r = _register(client, u["token"], {
        "BOOKSTACK_URL": URL,
        "BOOKSTACK_TOKEN_ID": "7",
        "BOOKSTACK_TOKEN_SECRET": "longsecret",
    })
    assert r.status_code == 200, r.text
    r = client.get("/api/mcp/config/bookstack/credentials/prefill",
                   headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200, r.text
    # The URL comes back (string, in the current schema). The joined token
    # does not (off-schema after the ID/SECRET split), and no secret ever does.
    assert r.json()["prefill"] == {"BOOKSTACK_URL": URL}


def test_prefill_404_without_a_config(client):
    u = _user(client)
    r = client.get("/api/mcp/config/bookstack/credentials/prefill",
                   headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 404


def test_prefill_degrades_to_empty_on_decrypt_failure(client):
    u = _user(client)
    r = _register(client, u["token"], {
        "BOOKSTACK_URL": URL,
        "BOOKSTACK_TOKEN_ID": "7",
        "BOOKSTACK_TOKEN_SECRET": "longsecret",
    })
    assert r.status_code == 200, r.text
    from database import SessionLocal, User
    from models.mcp_models import UserMCPConfig

    # Corrupt the blob: the route must degrade to an empty prefill, not 500.
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == u["username"]).first()
        row = (
            db.query(UserMCPConfig)
            .filter(UserMCPConfig.owner_id == user.id, UserMCPConfig.template_name == "bookstack")
            .first()
        )
        row.credentials_json = "not-a-fernet-token"
        db.commit()
    finally:
        db.close()
    r = client.get("/api/mcp/config/bookstack/credentials/prefill",
                   headers={"Authorization": f"Bearer {u['token']}"})
    assert r.status_code == 200
    assert r.json()["prefill"] == {}
