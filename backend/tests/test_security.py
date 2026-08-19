"""Regression tests for the security hardening pass (login flow)."""

import os

import jwt as pyjwt
import pytest
from pydantic import ValidationError

from auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    decode_access_token,
)
from schemas import UserCreate, UserLogin


class TestSignupSchema:
    def test_role_field_not_accepted(self):
        # SECURITY REGRESSION: UserCreate must never expose a role field —
        # accounts are always created as USER, so client-side privilege
        # escalation via POST /auth/signup {"role": "superuser"} is impossible.
        assert "role" not in UserCreate.model_fields
        model = UserCreate.model_validate(
            {"username": "alice", "email": "alice@x.com", "password": "longenough123", "role": "superuser"}
        )
        assert "role" not in model.model_dump()

    def test_password_minimum_length(self):
        with pytest.raises(ValidationError):
            UserCreate(username="alice", email="alice@x.com", password="short")

    def test_password_maximum_length(self):
        with pytest.raises(ValidationError):
            UserCreate(username="alice", email="alice@x.com", password="x" * 129)

    def test_email_must_be_valid(self):
        with pytest.raises(ValidationError):
            UserCreate(username="alice", email="not-an-email", password="longenough123")

    def test_username_charset(self):
        with pytest.raises(ValidationError):
            UserCreate(username="bad name!", email="alice@x.com", password="longenough123")

    def test_valid_signup(self):
        m = UserCreate(username="alice_smith", email="alice@x.com", password="longenough123")
        assert m.username == "alice_smith"

    def test_userlogin_has_no_role(self):
        assert "role" not in UserLogin.model_fields


class TestJwtHardening:
    def test_algorithm_pinned_hs256(self):
        # A 'none'-algorithm token must be rejected (algorithm-confusion protection).
        forged_none = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJldmlsIn0."
        assert decode_access_token(forged_none) is None
        assert decode_access_token("not.a.jwt") is None

    def test_token_carries_exp(self):
        token = create_access_token({"sub": "alice", "role": "user"})
        payload = pyjwt.decode(
            token, os.environ["SECRET_KEY"], algorithms=["HS256"], options={"verify_exp": False}
        )
        assert "exp" in payload
        assert payload["sub"] == "alice"
        assert ACCESS_TOKEN_EXPIRE_MINUTES == 1440
