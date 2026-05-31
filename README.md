# math-learn

An adaptive math-practice system built as a [uv](https://docs.astral.sh/uv/)
workspace monorepo. The engine adapts addition practice to a learner's ability
using an Elo / 1-PL model, a time-aware trial score, temperature-based item
selection, and per-exercise mastery tracking.

## Layout

```
math-learn/
├── pyproject.toml                 # uv workspace root (members = packages/*)
└── packages/
    ├── common-lib/                # "math-practice": shared engine library
    │   └── src/math_practice/
    │       ├── config.py          # EngineConfig (tunable hyper-parameters)
    │       ├── models.py          # Exercise + build_curriculum
    │       ├── difficulty.py      # difficulty scoring
    │       ├── ability.py         # ability (theta) tracking
    │       ├── selection.py       # item selection policy
    │       ├── mastery.py         # per-exercise mastery
    │       └── engine.py          # PracticeEngine orchestration
    ├── cli/                       # "math-practice-cli": terminal front-end
    │   └── src/math_practice_cli/
    │       └── app.py             # console entry point (main)
    ├── backend/                   # "math-practice-backend": FastAPI HTTP service
    │   └── src/math_practice_backend/
    │       ├── settings.py        # pydantic-settings configuration
    │       ├── clock.py           # Clock protocol + RealClock (UTC)
    │       ├── domain.py          # internal dataclasses (persistence boundary)
    │       ├── db.py              # SQLAlchemy engine / session factory / Base
    │       └── app.py             # FastAPI app (lifespan + /health)
    └── client/                    # "math-practice-client": HTTP client / CLI
        └── src/math_practice_client/
            └── app.py             # console entry point (main)
```

The `cli` package depends on `common-lib` via a uv workspace source, so the two
are developed and versioned together with no published-package round-trip.

## Requirements

- Python 3.11+
- uv

The library and CLI use the standard library only (no third-party runtime
dependencies), so the workspace installs offline.

## Getting started

```bash
# Create the workspace virtual environment and install both packages.
uv sync

# Run the interactive practice CLI.
uv run math-practice
```

## Packages

| Package         | Distribution name     | Import package        |
|-----------------|-----------------------|-----------------------|
| `common-lib`    | `math-practice`          | `math_practice`          |
| `cli`           | `math-practice-cli`      | `math_practice_cli`      |
| `backend`       | `math-practice-backend`  | `math_practice_backend`  |
| `client`        | `math-practice-client`   | `math_practice_client`   |

## Backend

`packages/backend` exposes the engine over HTTP with [FastAPI](https://fastapi.tiangolo.com/).
The server owns each session's engine state, grades submitted answers (the
client supplies its own measured elapsed time), and keeps a full trial log.

```bash
# Install the workspace (downloads FastAPI, SQLAlchemy, etc.).
uv sync

# Run the API with autoreload.
uv run uvicorn math_practice_backend.app:app --reload
```

### Endpoints (overview)

| Method & path                          | Purpose                                   |
|----------------------------------------|-------------------------------------------|
| `GET    /health`                       | liveness probe → `{"status": "ok"}`       |
| `POST   /v1/sessions`                  | create a session (returns opaque id)      |
| `GET    /v1/sessions/{sid}`            | fetch session + progress                  |
| `DELETE /v1/sessions/{sid}`            | delete a session                          |
| `POST   /v1/sessions/{sid}/next`       | draw (or re-show) the next exercise       |
| `POST   /v1/sessions/{sid}/answers`    | submit an answer; server grades it        |
| `GET    /v1/sessions/{sid}/stats`      | progress, accuracy, and recent trials     |

Sessions are identified by an opaque `session_id` (uuid4 hex) returned at
creation; there is no auth. Sessions are retained for 24h from last activity
(sliding window) and a background sweeper purges expired ones.

### Storage

Storage defaults to **in-memory SQLite** (SQLAlchemy 2.0 ORM, shared across
connections via `StaticPool`), so all session and trial data is **ephemeral**
and lost when the process exits. Switching to file SQLite or Postgres later only
requires changing `MATH_PRACTICE_DATABASE_URL`.
