"""Regression tests for the avatar upload size cap (abuse protection)."""

import random

# Minimal valid 1x1 transparent PNG (CRCs verified).
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082"
)


def _auth_user(client) -> str:
    username = f"avatar{random.randint(10000, 99999)}"
    r = client.post("/auth/signup", json={
        "username": username, "email": f"{username}@example.com", "password": "avatar-password-1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "avatar-password-1"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_avatar_upload_accepts_small_image(client):
    token = _auth_user(client)
    r = client.post("/user/avatar",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("avatar.png", TINY_PNG, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["profile_picture"].startswith("data:image/png;base64,")


def test_avatar_upload_rejects_oversized_file(client):
    from main import MAX_AVATAR_BYTES

    token = _auth_user(client)
    oversized = TINY_PNG + b"x" * (MAX_AVATAR_BYTES - len(TINY_PNG) + 1)
    assert len(oversized) == MAX_AVATAR_BYTES + 1
    r = client.post("/user/avatar",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("avatar.png", oversized, "image/png")})
    assert r.status_code == 413, r.text

    # Nothing was stored: the profile still has no picture.
    r = client.get("/user/profile", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["profile_picture"] is None


def test_avatar_upload_rejects_non_image(client):
    token = _auth_user(client)
    r = client.post("/user/avatar",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("evil.txt", b"not an image", "text/plain")})
    assert r.status_code == 400, r.text
