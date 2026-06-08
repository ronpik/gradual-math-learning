# AGENTS.md — client (`math_practice_client`)

httpx CLI that drives the backend over HTTP. **Decoupled** — depends only on
`httpx`, never on `common-lib`.

## Commands

```bash
# Needs a running backend (uv run uvicorn math_practice_backend.app:app --reload)
uv run math-practice-client [--url URL] [--session SID] \
    [--auto N --seed S --max-sum M]
```

## Boundaries

### Always Do
- Talk only to the **student-safe `/v1/play`** API.
- Measure answer time client-side (`time.monotonic`) and send `elapsed_seconds`.
- Persist/resume the `session_id` for the 24h window (`--session`).

### Never Do
- Import `common-lib` or any engine internals — this package reaches the backend
  over HTTP only.
- Read or display θ / mastery counts (the play API doesn't expose them).

## Architecture

`app.py`: an `ApiClient` wrapping a single `httpx.Client(base_url=...)`, plus an
interactive loop and an `--auto` synthetic-student mode. `--session` resumes an
existing run; on 404/410 it transparently starts a fresh session.
