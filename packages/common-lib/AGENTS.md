# AGENTS.md — common-lib (`math_practice`)

The pure-Python adaptive practice engine. Stdlib-only; no third-party runtime deps.

## Commands

```bash
# Tests are plain-assert scripts (NOT pytest) — run them directly:
uv run --package math-practice python packages/common-lib/tests/test_smoke.py
uv run --package math-practice python packages/common-lib/tests/test_state.py
```

## Boundaries

### Always Do
- Keep this package **stdlib-only** (zero third-party runtime dependencies).
- Put every tunable in the single frozen `EngineConfig` (config.py) — change behavior there or in one component, never by scattering constants.
- Run both test scripts before committing.

### Ask First
- Changing the public API of `EngineState` / `PracticeEngine.snapshot()` / `from_state()` — the backend persists and rehydrates through this seam.
- Renaming `EngineConfig` fields — they are serialized to JSON (`sessions.config`) and live in stored state.

### Never Do
- Add a third-party runtime dependency.
- Let `MasteryTracker` influence selection (it is a progress signal only).
- Remove an exercise from the pool (selection weighting handles difficulty progression).

## Architecture

Four decoupled components behind the `PracticeEngine` facade (`engine.py`):
`DifficultyScorer` (difficulty.py) → `AbilityTracker` (ability.py, latent θ) →
`SelectionPolicy` (selection.py, softmax peaked at 85% success) →
`MasteryTracker` (mastery.py). `models.py` = `Exercise` + `build_curriculum`;
`config.py` = `EngineConfig`; `state.py` = the `EngineState` persistence seam.

`docs/adaptive-practice-spec.md` is the authoritative algorithm spec, **but**
`EngineConfig` defaults are the source of truth where they diverge (mastery is
"3 correct under 10s": `mastery_streak=3`, `mastery_time_limit=10.0`).

## Code Style

Frozen `@dataclass` value objects, full type hints, docstrings citing the spec
section. Determinism via an injected `random.Random` (seeded in tests).
