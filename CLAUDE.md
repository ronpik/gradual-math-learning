# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An adaptive math-practice system (1st-grade addition, sums ≤ 10) built as a **uv
workspace monorepo**. A pure-Python engine adapts difficulty to keep a learner in
a ~85% success zone; a FastAPI service wraps it with sessions; two CLIs and a
React web client are front-ends.

`docs/adaptive-practice-spec.md` is the **authoritative algorithm spec** (formulas,
defaults, §8 config table). Read it before touching engine math. Note: the
implementation has intentionally diverged from the spec on **mastery** — it is now
"3 correct answers under 10s" (`EngineConfig.mastery_streak=3`,
`mastery_time_limit=10.0`), not the spec's streak-of-7/score-threshold. **`EngineConfig`
defaults are the source of truth**, not the prose in the spec.

## Commands

```bash
# Python workspace (common-lib, cli, backend, client)
uv sync                                          # install all Python packages

uv run math-practice                             # interactive offline CLI (direct-lib, no server)
uv run math-practice-client [--auto N --seed S]  # HTTP-client CLI (needs a running backend)
uv run uvicorn math_practice_backend.app:app --reload   # run the API

# Engine tests are plain-assert scripts (NOT pytest), run directly (no DB):
uv run --package math-practice python packages/common-lib/tests/test_smoke.py
uv run --package math-practice python packages/common-lib/tests/test_state.py

# Backend tests are pytest and POSTGRES-ONLY (not SQLite): a testcontainers
# harness spins an ephemeral postgres:16-alpine (tmpfs + durability off) once
# per session, runs `alembic upgrade head`, and isolates each test in a
# rolled-back transaction. Needs Docker running (or set
# MATH_PRACTICE_TEST_DATABASE_URL to a reachable Postgres to skip the container):
uv run --package math-practice-backend --extra dev --extra postgres \
    python -m pytest packages/backend/tests -q

# Web client (separate JS toolchain; needs Node 20+ / npm)
cd packages/web-client-static
npm install
npm run dev        # Vite dev server, proxies /v1 -> http://127.0.0.1:8000
npm run typecheck  # tsc --noEmit
npm run build      # tsc -b && vite build  -> dist/
```

`web-client-static` is a JS/TS package and is **excluded** from the uv workspace
(`pyproject.toml` `[tool.uv.workspace] exclude`); manage it with `npm`, never `uv`.

## Architecture

### Engine (`packages/common-lib`, import `math_practice`)
Four decoupled components behind one `PracticeEngine` facade (`engine.py`):
`DifficultyScorer` (static `b` per exercise) → `AbilityTracker` (latent θ, Elo/1-PL,
time-aware trial score) → `SelectionPolicy` (softmax peaked at 85% predicted
success; nothing is ever removed from the pool) → `MasteryTracker` (progress signal
only; never affects selection). All tunables live in the single frozen
`EngineConfig`. The pool/curriculum is derived from `MAX_SUM`.

**The persistence seam — `EngineState` (`state.py`):** `PracticeEngine.snapshot()`
→ `EngineState` (θ, config copy, per-exercise mastery, `last_shown`) and
`PracticeEngine.from_state()` rebuild a behaviourally identical engine. The backend
**does not hold live engine objects** — it stores `EngineState` and rehydrates a
fresh engine on every request. This is what makes the storage backend swappable.

### Backend (`packages/backend`, import `math_practice_backend`)
Strict one-directional layering — **respect these boundaries when editing**:

```
routes*.py (Pydantic schemas) → mappers.py → domain.py (dataclasses)
  → service.py (SessionService) → repositories.py (SessionRepository ABC)
  → models.py (SQLAlchemy ORM)
```

- **Dataclasses are the internal currency.** Pydantic appears ONLY in `schemas.py`/
  routes; SQLAlchemy ORM rows ONLY in `models.py`/`repositories.py`. `service.py`
  imports neither — it speaks `domain.py` dataclasses + `math_practice` value objects.
- `SessionService` orchestrates: load → rehydrate engine via `from_state` →
  mutate → `snapshot()` → save, under a per-session lock. It also owns the
  **24h sliding expiry** (refreshed on every request; expired sessions raise and are
  purged; a background sweeper reclaims abandoned ones).
- **Server grades, client times:** answer endpoints take `{answer, elapsed_seconds}`;
  the server computes correctness. A full trial log is persisted.

**Two API surfaces (do not mix them):**
- `/v1/sessions/*` — admin/diagnostic; exposes engine internals (θ, mastery counts).
- `/v1/play/*` — **student-safe**; returns only `correct`, `questions_done`,
  `module_completion_percent`, `streak`, accuracy, timing. It must NEVER leak θ,
  mastery/total counts, score `s`, or predicted success `E`. The web client uses
  only `/v1/play`. When adding student-facing data, extend the `Student*` schemas
  and `routes_play.py`, not the admin surface.

**Storage:** in-memory SQLite via SQLAlchemy 2.0 + `StaticPool` (`db.py`). Data is
**ephemeral** and the in-memory store is **not shared across processes**, so the
server must run **single-worker** until pointed at file SQLite/Postgres via
`MATH_PRACTICE_DATABASE_URL`. Settings use the `MATH_PRACTICE_` env prefix
(`SERVE_WEB`, `WEB_DIR`, `CORS_ALLOW_ORIGINS`, `SESSION_TTL_HOURS`, ...). Note the
**backend tests do NOT use SQLite** — they run against a real Postgres (the
production target) via testcontainers; the `tests/conftest.py` harness installs a
per-test session-factory override through `dependencies.set_session_factory_override`
(the providers call `get_session_factory()` directly, so a FastAPI
`dependency_overrides` on it alone would not redirect the repositories). The psycopg
v3 driver is used, so test URLs are `postgresql+psycopg://`.

**Lifespan gotcha:** tables are created and the static `dist/` is mounted in the
FastAPI **lifespan**. So `TestClient(app)` must use the `with` context manager (or
run via uvicorn) — a bare `TestClient(app)` skips lifespan and yields
"no such table". The static mount is registered last so `/health` and `/v1/*` win.

### Front-ends
- `packages/cli` (`math-practice`) — offline, imports the engine directly; no server.
- `packages/client` (`math-practice-client`) — httpx CLI against the HTTP API.
- `packages/web-client-static` — React + Vite + TS SPA ("Math Meadow"). Talks only
  to `/v1/play`; measures answer time with `performance.now()`; persists `session_id`
  in `localStorage` for 24h resume. Design tokens in `src/styles`; never render or
  fetch engine internals. The backend serves the built `dist/` at `/` when present.

## Cross-cutting conventions

- The `cli`/`backend` depend on `common-lib` via uv **workspace sources** (path,
  no publish round-trip). The `client` and `web-client-static` are decoupled and
  reach the backend over HTTP only.
- `common-lib` is **stdlib-only** (no third-party runtime deps) — keep it that way.
- Changing engine behaviour means changing `EngineConfig` defaults and/or a single
  component; the four components and the front-ends stay untouched thanks to the
  facade + `EngineState` seam.

## Related agent instructions (AGENTS.md)

Vendor-neutral `AGENTS.md` files (read by Codex/Cursor/Copilot/etc.; this
`CLAUDE.md` is the Claude-native root) carry per-scope context. Consult the
relevant one when working in that area:

- `packages/common-lib/AGENTS.md` — engine library; stdlib-only rule; the
  `EngineState` snapshot/restore seam; plain-assert test scripts.
- `packages/backend/AGENTS.md` — layering & boundaries, the two API surfaces,
  identity/auth, storage; links to the two below.
- `packages/backend/migrations/AGENTS.md` — Alembic workflow; dialect-portable
  migration types; single-baseline regeneration caveat.
- `packages/backend/tests/AGENTS.md` — Postgres-only testcontainers harness,
  savepoint-rollback isolation, fixtures, DI test seam.
- `packages/cli/AGENTS.md` — offline direct-lib CLI.
- `packages/client/AGENTS.md` — httpx CLI over `/v1/play` (no engine import).
- `packages/web-client-static/AGENTS.md` — React/Vite SPA; play-only; Firebase;
  student-safe rendering rules.
