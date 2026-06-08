# AGENTS.md — backend (`math_practice_backend`)

FastAPI service wrapping the engine with sessions, identity, and SQLAlchemy
persistence. Postgres-first (Alembic-managed), SQLite supported via URL.

## Commands

```bash
# Run the API (reads .env.local when present)
uv run uvicorn math_practice_backend.app:app --reload

# Tests — POSTGRES-ONLY via testcontainers (needs Docker):
uv run --package math-practice-backend --extra dev --extra postgres \
    python -m pytest packages/backend/tests -q

# Migrations (URL from MATH_PRACTICE_DATABASE_URL / settings):
uv run --package math-practice-backend \
    alembic -c packages/backend/alembic.ini upgrade head
```

## Boundaries

### Always Do
- Keep the **strict one-directional layering**:
  `routes*.py (Pydantic) → mappers.py → domain.py (dataclasses) → service.py → repositories.py (ABC) → models.py (ORM)`.
- Exchange **dataclasses** between internal components — never raw dicts.
- Run the backend test suite before committing.

### Ask First
- Schema or migration changes (regenerating the baseline forces a dev-DB reset).
- Adding dependencies; touching the DI singleton/test seam in `dependencies.py`.

### Never Do
- Leak engine internals on `/v1/play` (θ, mastery/total counts, score `s`,
  predicted success `E`) — extend the `Student*` schemas + `routes_play.py`.
- Import Pydantic in `service.py`/`repositories.py`, or SQLAlchemy/ORM in
  `service.py`/`routes*.py`, or Firebase/`google-auth` outside `auth.py`.

## Architecture

- **EngineState seam:** the service holds no live engine — it loads stored state,
  `PracticeEngine.from_state(...)`, mutates, `snapshot()`, saves, under a
  per-session lock. 24h sliding expiry; background `sweeper.py`.
- **Two API surfaces:** `routes.py` (`/v1/sessions/*`, admin — exposes internals)
  vs `routes_play.py` (`/v1/play/*`, student-safe). The web client uses only play.
- **Identity:** `auth.py` (`AuthProvider` ABC + `FirebaseAuthProvider` verifying
  ID tokens by project id, no service account; `FakeAuthProvider` for tests),
  `identity_service.py` (uid→user→learner + anonymous→login merge). Firebase
  tokens are optional; anonymous play is allowed.
- **Storage:** `db.py` builds the engine from `MATH_PRACTICE_DATABASE_URL`
  (SQLite uses StaticPool; Postgres uses Alembic). Native types are Postgres-first
  with portable variants (uuid/jsonb/enum/citext/bigint). `init_db` create_all is
  SQLite-only; Alembic owns Postgres. Settings use the `MATH_PRACTICE_` prefix
  and auto-load `.env` / `.env.local`.

## Detailed Guidance
- `migrations/AGENTS.md` — Alembic workflow, dialect-portable migration rules.
- `tests/AGENTS.md` — the Postgres testcontainers + savepoint-rollback harness.

## Tool-Specific Instructions
- Repo-root `CLAUDE.md` holds Claude Code-specific guidance and global architecture.
