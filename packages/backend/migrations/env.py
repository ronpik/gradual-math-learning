"""Alembic migration environment for the math-practice backend.

Resolves the target database from the same source the application uses — the
``MATH_PRACTICE_DATABASE_URL`` environment variable, falling back to
``settings.database_url`` — so a single migration stack targets in-memory/file
SQLite (dev/tests) and Postgres (deploy) with no hardcoded ``alembic.ini`` URL.

``target_metadata`` is ``Base.metadata``; importing ``math_practice_backend.models``
registers every ORM table on that metadata so ``--autogenerate`` sees the full
schema. ``compare_type=True`` detects column-type changes and
``render_as_batch=True`` makes SQLite ALTERs run in batch (copy-and-move) mode.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models module registers every table on Base.metadata.
from math_practice_backend import models  # noqa: F401
from math_practice_backend.db import Base
from math_practice_backend.settings import get_settings

# Alembic Config object, providing access to alembic.ini values.
config = context.config

# Configure Python logging from the alembic.ini file, if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata that ``--autogenerate`` compares the database against.
target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the database URL from the env var or application settings."""
    return os.environ.get("MATH_PRACTICE_DATABASE_URL") or get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI connection)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live DBAPI connection)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
