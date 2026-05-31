#!/usr/bin/env python3
"""Render the spec's formula curves as image plots (seaborn / matplotlib).

Each curve is reduced to a SINGLE independent variable by fixing every other
parameter at its default value (see `docs/adaptive-practice-spec.md`, §8). The
formula is shown as the in-plot legend; the default values go in the figure
caption inside the spec.

Usage:
    uv run scripts/plot_curves.py                 # render PNGs into docs/figures/
    uv run scripts/plot_curves.py --format csv    # print raw (x, y) values
    uv run scripts/plot_curves.py --key time_weight   # only one curve
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# --- Default parameters (must match §8 "Configuration summary") -------------
TAU_TIME = 12.0       # time-weight half-weight point (s)
P_TIME = 1.0          # time-weight curvature
TIME_LIMIT = 90.0     # timeout (s)
FLOOR = 0.85          # slow_correct_credit (= p_target)
TAU_DIFF = 2.0        # logistic difficulty scale
P_TARGET = 0.85       # selection target success rate
TAU_SEL = 0.10        # selection temperature
EPS = 1e-3            # selection weight floor

FIG_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures"
DPI = 130


# --- Formulas ---------------------------------------------------------------
def time_weight(t: float) -> float:
    """w(t) = 1 / (1 + (t / tau_time)^p_time)"""
    return 1.0 / (1.0 + (t / TAU_TIME) ** P_TIME)


def trial_score_correct(t: float) -> float:
    """s = floor + (1 - floor) * w(t)   (for a correct answer)"""
    return FLOOR + (1.0 - FLOOR) * time_weight(t)


def success_prob(delta: float) -> float:
    """E = 1 / (1 + exp(-(theta - b) / tau_diff)), with delta = theta - b"""
    return 1.0 / (1.0 + math.exp(-delta / TAU_DIFF))


def selection_weight(e: float) -> float:
    """weight = exp(-|E - p_target| / tau_sel) + eps"""
    return math.exp(-abs(e - P_TARGET) / TAU_SEL) + EPS


# --- Curve definitions (single dependent value each) ------------------------
@dataclass
class Curve:
    key: str
    formula: str        # shown as the in-plot legend
    x_label: str
    y_label: str
    x_min: float
    x_max: float
    fn: Callable[[float], float]
    caption: str        # mentions the fixed default values (used in the spec)
    y_lim: tuple[float, float] | None = None
    vlines: list[tuple[float, str]] = field(default_factory=list)  # (x, label)


CURVES: list[Curve] = [
    Curve(
        key="time_weight",
        formula=r"$w(t) = 1 / (1 + (t/\tau)^{p})$",
        x_label="response time  t  (s)",
        y_label="w(t)",
        x_min=0.0,
        x_max=90.0,
        fn=time_weight,
        y_lim=(0.0, 1.02),
        vlines=[(TAU_TIME, r"$t=\tau_{time}$ (w=0.5)")],
        caption="Time weight. Defaults: tau_time = 12 s, p_time = 1, TIME_LIMIT = 90 s.",
    ),
    Curve(
        key="trial_score",
        formula=r"$s = \mathrm{floor} + (1-\mathrm{floor})\,w(t)$",
        x_label="response time  t  (s)",
        y_label="s  (correct answer)",
        x_min=0.0,
        x_max=90.0,
        fn=trial_score_correct,
        y_lim=(0.8, 1.02),
        caption="Correct-answer score band. Defaults: floor = 0.85, tau_time = 12 s, "
                "p_time = 1. A wrong/timeout answer is s = 0 (off-scale below).",
    ),
    Curve(
        key="success_prob",
        formula=r"$E = 1 / (1 + e^{-(\theta-b)/\tau_{diff}})$",
        x_label=r"$\theta - b$   (ability minus difficulty)",
        y_label="E  (predicted success)",
        x_min=-6.0,
        x_max=6.0,
        fn=success_prob,
        y_lim=(0.0, 1.02),
        caption="Predicted success probability. Default: tau_diff = 2.0.",
    ),
    Curve(
        key="selection_weight",
        formula=r"$w = e^{-|E - p_{target}| / \tau_{sel}} + \varepsilon$",
        x_label="E  (predicted success of an item)",
        y_label="selection weight",
        x_min=0.0,
        x_max=1.0,
        fn=selection_weight,
        y_lim=(0.0, 1.05),
        vlines=[(P_TARGET, r"$E=p_{target}=0.85$")],
        caption="Unnormalized sampling weight per item. Defaults: p_target = 0.85, "
                "tau_sel = 0.10, eps = 1e-3. Peak sits at E = 0.85.",
    ),
]


# --- Renderers --------------------------------------------------------------
def render_png(curve: Curve) -> Path:
    sns.set_theme(style="whitegrid", context="notebook")
    x = np.linspace(curve.x_min, curve.x_max, 400)
    y = [curve.fn(float(v)) for v in x]

    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    sns.lineplot(x=x, y=y, ax=ax, label=curve.formula, linewidth=2.2, color="#2b6cb0")
    for vx, vlabel in curve.vlines:
        ax.axvline(vx, color="#888888", linestyle="--", linewidth=1.0)
        ax.annotate(vlabel, xy=(vx, ax.get_ylim()[0]),
                    xytext=(4, 6), textcoords="offset points",
                    fontsize=9, color="#555555")
    ax.set_xlabel(curve.x_label)
    ax.set_ylabel(curve.y_label)
    if curve.y_lim:
        ax.set_ylim(*curve.y_lim)
    ax.legend(loc="best", fontsize=12, frameon=True)

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"{curve.key}.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out


def render_csv(curve: Curve) -> str:
    n = 13
    xs = np.linspace(curve.x_min, curve.x_max, n)
    lines = [f"# {curve.key}: {curve.formula}", "x,y"]
    lines += [f"{x:g},{curve.fn(float(x)):.6f}" for x in xs]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["png", "csv"], default="png")
    parser.add_argument("--key", help="render/emit only the curve with this key")
    args = parser.parse_args()

    for curve in CURVES:
        if args.key and curve.key != args.key:
            continue
        if args.format == "png":
            out = render_png(curve)
            print(f"wrote {out}")
        else:
            print(f"\n===== {curve.key} =====\n")
            print(render_csv(curve))


if __name__ == "__main__":
    main()
