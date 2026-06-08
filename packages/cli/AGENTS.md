# AGENTS.md — cli (`math_practice_cli`)

Offline terminal front-end. Imports the engine **directly** (no server).

## Commands

```bash
uv run math-practice                                  # interactive practice
uv run math-practice --auto N --seed S --max-sum M    # deterministic simulation
```

## Boundaries

### Always Do
- Depend on `common-lib` via the uv **workspace source** (path, no publish).
- Measure answer time locally and pass it to the engine.

### Never Do
- Reach the backend over HTTP — that's the `client` package's job. This CLI is
  purely offline and talks to `math_practice` in-process.
- Add dependencies beyond stdlib + `math-practice`.

## Architecture

`app.py` owns the whole TUI: builds a `PracticeEngine`, loops
`next_exercise → prompt → grade → submit`, renders feedback. `--auto` drives a
synthetic student for smoke-testing the engine end-to-end.
