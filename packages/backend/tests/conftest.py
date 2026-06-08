"""Pytest harness: Postgres-only backend tests via testcontainers.

Backend tests run against a **real PostgreSQL** (the production target), not
SQLite — only Postgres validates the native ``uuid`` / ``jsonb`` / ``enum`` /
``citext`` schema and the ``ON DELETE CASCADE`` foreign keys.

Speed strategy:

* **One ephemeral container** for the whole session (or a remote DB via
  ``MATH_PRACTICE_TEST_DATABASE_URL``), tuned for in-memory speed: its data
  directory lives on a tmpfs (RAM) and durability is disabled
  (``fsync=off``/``synchronous_commit=off``/``full_page_writes=off``).
* **Schema once** per session via ``alembic upgrade head``.
* **Transaction-per-test rollback** (SQLAlchemy 2.0 savepoint-join): each test
  gets a pristine database in sub-millisecond time. The repositories commit
  internally; ``join_transaction_mode="create_savepoint"`` turns those commits
  into savepoint releases inside one outer transaction that is rolled back on
  teardown — so no app code changes and tests never see each other's writes.

Because the per-test connection is shared, tests must issue their requests
**sequentially** (they do). The background sweeper's 600s interval never fires
during a test, so it is harmless.

The psycopg v3 driver is used throughout (``postgresql+psycopg://``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"


def _to_psycopg_url(url: str) -> str:
    """Rewrite a Postgres URL to use the psycopg (v3) SQLAlchemy driver."""
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + url[len("postgresql+psycopg2://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Yield a psycopg-scheme URL for the test Postgres.

    Uses ``MATH_PRACTICE_TEST_DATABASE_URL`` when set (CI / remote DB); otherwise
    starts an ephemeral ``postgres:16-alpine`` testcontainer tuned for in-memory
    speed and stops it on teardown. Postgres-only is intentional: if Docker /
    testcontainers is unavailable, fail loudly with guidance.
    """
    remote = os.environ.get("MATH_PRACTICE_TEST_DATABASE_URL")
    if remote:
        yield _to_psycopg_url(remote)
        return

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError as exc:  # pragma: no cover - dependency guard
        pytest.fail(
            "testcontainers is required for the Postgres-only backend tests "
            "(install with `--extra dev`), or set "
            "MATH_PRACTICE_TEST_DATABASE_URL to a reachable Postgres. "
            f"Import failed: {exc}"
        )

    try:
        container = (
            PostgresContainer("postgres:16-alpine", driver="psycopg")
            # Data dir on tmpfs (RAM) so the DB never touches disk, and
            # durability off — safe for ephemeral test data, much faster. The
            # tmpfs mount is passed straight through to docker-py's ``run``.
            .with_kwargs(tmpfs={"/var/lib/postgresql/data": "size=512m"})
            .with_command(
                "-c fsync=off "
                "-c synchronous_commit=off "
                "-c full_page_writes=off"
            )
        )
        container.start()
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.fail(
            "Could not start a Postgres testcontainer (is Docker running?). "
            "Backend tests are Postgres-only; set "
            "MATH_PRACTICE_TEST_DATABASE_URL to use an external Postgres. "
            f"Error: {exc}"
        )

    try:
        yield _to_psycopg_url(container.get_connection_url())
    finally:
        container.stop()


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(postgres_url: str) -> Iterator[str]:
    """Point the app at the test DB and run ``alembic upgrade head`` once.

    Sets ``MATH_PRACTICE_DATABASE_URL`` to the test URL (so settings, the app's
    module engine/session factory, and Alembic all resolve to the same DB),
    rebuilds the app's default engine/session factory to that URL, clears the
    settings cache, then applies the migration baseline a single time for the
    whole session.
    """
    os.environ["MATH_PRACTICE_DATABASE_URL"] = postgres_url

    # Make settings + the app's module-level engine/session_factory resolve to
    # the test DB so the non-overridden path (and the migration) are consistent.
    from math_practice_backend import db
    from math_practice_backend.settings import get_settings

    get_settings.cache_clear()
    db.engine.dispose()
    db.engine = create_engine(postgres_url, future=True)
    db.session_factory = sessionmaker(bind=db.engine, future=True)

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    command.upgrade(cfg, "head")

    yield postgres_url

    db.engine.dispose()


@pytest.fixture(scope="session")
def engine(postgres_url: str, apply_migrations: str) -> Iterator[Engine]:
    """A session-scoped SQLAlchemy engine on the migrated test DB."""
    eng = create_engine(postgres_url, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> Iterator[sessionmaker]:
    """Per-test session factory bound to a rolled-back outer transaction.

    Opens one connection, begins a transaction, and builds a sessionmaker bound
    to that connection with ``join_transaction_mode="create_savepoint"`` so the
    repositories' internal ``commit()`` calls become savepoint releases inside
    the outer transaction. Installs it as the global provider override; on
    teardown the override is cleared and the outer transaction is rolled back —
    giving each test a pristine DB in sub-millisecond time.
    """
    from math_practice_backend.dependencies import set_session_factory_override

    connection: Connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        future=True,
        expire_on_commit=False,
    )
    set_session_factory_override(factory)
    try:
        yield factory
    finally:
        set_session_factory_override(None)
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(session_factory: sessionmaker) -> Iterator["TestClient"]:
    """A TestClient whose request handlers use the per-test session factory.

    Entered as a context manager so the FastAPI lifespan runs (it eagerly builds
    the shared singletons, which now resolve to the override). Dependency
    overrides are cleared on teardown.
    """
    from fastapi.testclient import TestClient

    from math_practice_backend.app import app

    with TestClient(app) as test_client:
        try:
            yield test_client
        finally:
            app.dependency_overrides.clear()


@pytest.fixture()
def fake_auth(client: "TestClient") -> Iterator["TestClient"]:
    """A ``client`` with the auth provider overridden by ``FakeAuthProvider``.

    The fake parses ``"fake:<uid>[:<email>]"`` bearer tokens, so auth tests need
    no real Firebase. The override is removed on teardown by the ``client``
    fixture clearing ``dependency_overrides``.
    """
    from math_practice_backend.app import app
    from math_practice_backend.auth import FakeAuthProvider
    from math_practice_backend.dependencies import get_auth_provider

    app.dependency_overrides[get_auth_provider] = lambda: FakeAuthProvider()
    yield client


if False:  # pragma: no cover - typing only
    from fastapi.testclient import TestClient  # noqa: F401
