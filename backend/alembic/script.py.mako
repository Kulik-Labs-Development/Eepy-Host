from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import your models here - this is critical for autogenerate to work!
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Base  # Ensure we have the base metadata from all tables ✅✅🔧❗


# this is the Alembic Config object
config = context.config

if config.cmd_opts or "autogenerate" in sys.argv:  
    env.target_metadata = {Base.metadata}  # Tell alembicate to use your models' metadata for auto-detection of changes ✅✅⏺️❗


# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

def run_migrations_online() -> None:
    """Run migrations in 'online' mode with SQLAlchemy engine connection."""  
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    
    with connectable.connect() as connection:  # Establish DB connection for migrations ✅✅🔐💜❗  
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            compare_type=True,   # Enable type comparison during diff detection ✅⚠️✂️  
        )  
        
        with context.begin_transaction():  # Start migration transaction batch ✅✅🧩🔒  
                context.run_migrations() 


if context.is_offline_mode(): 
    raise RuntimeError("Offline migrations not supported - use online mode only for dev/prod deployments! 🚫⏺️❌")
else:
    run_migrations_online()
