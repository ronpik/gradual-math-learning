# AGENTS.md — backend tests (Postgres-only)

Backend tests run against **real PostgreSQL** (the production target), not
SQLite — only Postgres validates the native uuid/jsonb/enum/citext schema and
`ON DELETE CASCADE`.

## Commands

```bash
# Needs Docker (testcontainers auto-spins an ephemeral postgres:16-alpine):
uv run --package math-practice-backend --extra dev --extra postgres \
    python -m pytest packages/backend/tests -q

# Skip the container — point at an existing Postgres (psycopg v3 scheme):
MATH_PRACTICE_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db \
  uv run --package math-practice-backend --extra dev --extra postgres \
  python -m pytest packages/backend/tests -q

# single test
... python -m pytest packages/backend/tests/test_pg_native.py::test_isolation_same_id_first -q
```

## How isolation works (conftest.py)

- One ephemeral container per **session** (tmpfs data dir + `fsync=off`
  `synchronous_commit=off` `full_page_writes=off`), schema via `alembic upgrade
  head` **once**.
- Each test runs inside an outer transaction with
  `sessionmaker(join_transaction_mode="create_savepoint")`, rolled back on
  teardown → pristine DB in sub-ms. The repos commit internally; savepoint-join
  turns those commits into savepoint releases (**no production code change**).
- Fixtures: `session_factory` (per-test txn; installs the DI override via
  `dependencies.set_session_factory_override`), `client` (TestClient under
  lifespan), `fake_auth` (FakeAuthProvider override), `engine`, `postgres_url`.

## Boundaries

### Always Do
- Add backend tests using `client` / `session_factory` / `fake_auth`.
- Use the psycopg v3 scheme (`postgresql+psycopg://`).

### Never Do
- Introduce a SQLite fallback in the backend test path.
- Swap production `commit()` for `flush()` — the savepoint-join provides rollback.
- Fire concurrent requests within one test (the savepoint connection is shared;
  tests must be sequential).
