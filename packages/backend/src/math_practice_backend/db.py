"""Database engine, session factory, and ORM declarative base.

Builds a SQLAlchemy 2.0 engine from :attr:`Settings.database_url`. The default
URL is a shared in-memory SQLite database: ``StaticPool`` plus
``check_same_thread=False`` keep a single underlying connection alive and usable
across threads, so the schema and data persist for the process lifetime.

Switching to file SQLite or Postgres later only requires changing the URL (the
SQLite-specific connect args are applied only for SQLite URLs).
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .settings import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base class for all backend ORM models."""


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
    """Create all ORM tables if they do not already exist.

    Args:
        eng: engine to create the schema in; defaults to the module-level
            :data:`engine`.
    """
    Base.metadata.create_all(eng or engine)
