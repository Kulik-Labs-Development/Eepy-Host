import os

os.environ.setdefault("DATABASE_URL", "postgresql://eepy:eepy@localhost:5432/eepy_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-ci-only")
