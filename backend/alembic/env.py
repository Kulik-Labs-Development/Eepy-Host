import os

# Connection URL is always sourced from the DATABASE_URL environment variable.
# alembic.ini ships only a placeholder; no credentials live in the repo.
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL environment variable is required to run migrations.")

script_location = os.path.dirname(__file__) or "."

env = {
    "sqlalchemy.url": os.getenv("DATABASE_URL")
}

target_metadata = None  # Will be set by Alembic autogenerate logic from your models import
