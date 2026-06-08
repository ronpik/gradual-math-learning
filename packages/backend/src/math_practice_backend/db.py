"""Database engine, session factory, and ORM declarative base.

Builds a SQLAlchemy 2.0 engine from :attr:`Settings.database_url`. The default
URL is a shared in-memory SQLite database: ``StaticPool`` plus
``check_same_thread=False`` keep a single underlying connection alive and usable
across threads, so the schema and data persist for the process lifetime.

Switching to file SQLite or Postgres later only requires changing the URL (the
SQLite-specific connect args are applied only for SQLite URLs).
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

#: Stable constraint/index naming convention so Alembic ``--autogenerate``
#: yields deterministic, identical names across SQLite and Postgres. Without
#: this, unnamed constraints get backend-specific (or no) names, and batch
#: ALTERs on SQLite cannot reliably reference them.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base class for all backend ORM models.

    The shared :class:`~sqlalchemy.MetaData` carries :data:`NAMING_CONVENTION`
    so every implicit constraint/index name is deterministic across backends.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Create a SQLAlchemy :class:`Engine` from settings.

    For SQLite URLs a :class:`StaticPool` and ``check_same_thread=False`` are
    used so an in-memory database is shared across threads/connections.

    Args:
        settings: configuration to read ``database_url`` from; defaults to the
            process-wide :func:`get_settings`.

    Returns:
        A configured, ready-to-use :class:`Engine`.
    """
    settings = settings or get_settings()
    url = settings.database_url
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    return create_engine(url, future=True)


#: Process-wide engine and session factory. Bound to the default settings;
#: ``init_db`` (and the app lifespan) operate against these.
engine: Engine = create_db_engine()
session_factory: sessionmaker = sessionmaker(bind=engine, future=True)


def init_db(eng: Engine | None = None) -> None:
    """Provision the schema on startup, dialect-aware.

    For **SQLite** URLs (the in-memory/file dev path and the test suite) the
    tables are created in-process via ``Base.metadata.create_all`` so no
    migration step is needed. For every **other** backend (Postgres) the schema
    is owned by Alembic — ``alembic upgrade head`` is expected to have run at
    deploy time — so this function does *not* create tables and leaves the
    database untouched.

    Either way the chosen path is logged.

    Args:
        eng: engine to provision; defaults to the module-level :data:`engine`.
    """
    eng = eng or engine
    if eng.dialect.name == "sqlite":
        logger.info(
            "init_db: SQLite backend (%s) — creating schema via "
            "Base.metadata.create_all",
            eng.url,
        )
        Base.metadata.create_all(eng)
    else:
        logger.info(
            "init_db: non-SQLite backend (%s) — skipping create_all; "
            "schema is managed by Alembic (run 'alembic upgrade head')",
            eng.dialect.name,
        )
