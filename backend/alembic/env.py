import os

script_location = os.path.dirname(__file__) or "."

env = {
    "sqlalchemy.url": "postgresql://eepy_admin:[ROTATED_POSTGRES_PASSWORD]@db:5432/eepy_host"
}

target_metadata = None  # Will be set by Alembic autogenerate logic from your models import

