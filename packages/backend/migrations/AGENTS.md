# AGENTS.md — backend migrations (Alembic)

Alembic-managed schema. A **single baseline** (`d8efed1e2877`) applies to both
SQLite and Postgres from one file.

## Commands

```bash
# Apply (URL from MATH_PRACTICE_DATABASE_URL or settings):
uv run --package math-practice-backend alembic -c packages/backend/alembic.ini upgrade head

# Autogenerate against an EMPTY DB so emitted types are the portable model types:
rm -f /tmp/gen.db
MATH_PRACTICE_DATABASE_URL=sqlite+pysqlite:////tmp/gen.db \
  uv run --package math-practice-backend \
  alembic -c packages/backend/alembic.ini revision --autogenerate -m "msg"
```

## Conventions

- `env.py` resolves the URL from `MATH_PRACTICE_DATABASE_URL` (else
  `settings.database_url`); configured with `compare_type=True` and
  `render_as_batch=True`. `alembic.ini` paths anchor to `%(here)s`;
  `path_separator = os`.
- Migrations MUST use **dialect-portable** types so one file runs on both
  dialects: `sa.Uuid`, `sa.JSON().with_variant(JSONB, "postgresql")`,
  `sa.Enum(...)`, `sa.String().with_variant(CITEXT, "postgresql")`,
  `sa.BigInteger().with_variant(Integer, "sqlite")`.
- The `citext` extension is created under a `dialect.name == "postgresql"` guard;
  native enum types are dropped in `downgrade()`.

## Boundaries

### Always Do
- Verify a new revision `upgrade head`s on **both** SQLite and a real Postgres.

### Never Do
- Emit a Postgres-only type (`postgresql.UUID/JSONB/CITEXT`) for a column that
  must stay portable — use `.with_variant(...)`.
- Hand-edit an already-applied baseline without resetting dev DBs. Regenerating
  the baseline requires: `docker compose down -v && docker compose up -d` then
  `alembic upgrade head` (dev data is ephemeral).
