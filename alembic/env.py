"""Alembic environment.

The database URL comes from `Settings`, not from `alembic.ini`, so migrations
run against whatever `DATABASE_URL` is configured — SQLite here, PostgreSQL or
MySQL in production, from the same revision files.
"""

from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.db import create_app_engine

# Importing the package registers every model on the metadata. A model module
# that is never imported reads to autogenerate as a dropped table.
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# `alembic.ini` leaves the URL blank, so this normally resolves to the app's own
# setting. An explicit `-x`/config override still wins, which is how the test
# suite points a run at a throwaway database.
DATABASE_URL = config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL for the configured URL without connecting."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = create_app_engine(DATABASE_URL)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
