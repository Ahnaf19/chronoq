"""Alembic environment configuration for Chronoq telemetry database."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override URL from environment if available
db_url = os.environ.get("CHRONOQ_PREDICTOR_STORAGE", config.get_main_option("sqlalchemy.url"))
if db_url and db_url.startswith("sqlite:///"):
    # Alembic needs sqlalchemy-style URL
    pass


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(url=db_url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = create_engine(db_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
