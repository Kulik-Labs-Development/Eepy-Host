from datetime import timedelta

from auth import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


def test_password_hash_round_trip():
    hashed = get_password_hash("s3cret-password")
    assert hashed != "s3cret-password"
    assert verify_password("s3cret-password", hashed) is True


def test_password_wrong_rejected():
    hashed = get_password_hash("s3cret-password")
    assert verify_password("wrong-password", hashed) is False


def test_password_invalid_hash_returns_false():
    assert verify_password("anything", "not-a-valid-bcrypt-hash") is False


def test_password_72_byte_limit():
    long_pw = "p" * 100
    hashed = get_password_hash(long_pw)
    assert verify_password(long_pw, hashed) is True


def test_jwt_round_trip():
    token = create_access_token({"sub": "alice", "role": "user"})
    payload = decode_access_token(token)
    assert payload["sub"] == "alice"
    assert payload["role"] == "user"


def test_jwt_custom_expiry_round_trip():
    token = create_access_token({"sub": "bob"}, expires_delta=timedelta(minutes=5))
    payload = decode_access_token(token)
    assert payload["sub"] == "bob"


def test_jwt_garbage_returns_none():
    assert decode_access_token("not.a.jwt") is None
    assert decode_access_token("") is None
