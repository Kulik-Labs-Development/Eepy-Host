"""Test fixtures.

Environment must be set BEFORE any backend module is imported (auth.py and
database.py read env at import time), so this is done at conftest import time.
A throwaway SQLite file is used: no external PostgreSQL needed in CI.
"""

import os
import tempfile

# Unique throwaway DB per test session.
_tmp_dir = tempfile.mkdtemp(prefix="eepy-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_dir}/eepy_test.db")
# 32+ bytes: satisfies PyJWT's minimum HMAC key length for HS256.
os.environ.setdefault("SECRET_KEY", "test-secret-key-ci-only-32-bytes-min")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """FastAPI test client for the full application (SQLite-backed)."""
    from fastapi.testclient import TestClient

    import main

    return TestClient(main.app)
