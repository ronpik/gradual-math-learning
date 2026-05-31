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
    └── cli/                       # "math-practice-cli": terminal front-end
        └── src/math_practice_cli/
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
| `common-lib`    | `math-practice`       | `math_practice`       |
| `cli`           | `math-practice-cli`   | `math_practice_cli`   |
