"""Bounded-drift test: AV-first plan vs its R-anchored twin.

The AV-first plans (today: txtrs-av) and their R-anchored twins (txtrs)
model the same underlying pension at the same valuation vintage. They
SHOULD agree at year 0 because both calibrate to the same AV-published
total AAL. They will drift over the projection because the plans use
different prep methods (AV-first extraction vs legacy R reconstruction),
different mortality bases, different retiree-distribution methods, and
different term-vested cashflow shapes.

This test does not assert that the drift is "right". It bounds the
drift at thresholds chosen to pass today's behavior with headroom.
The point is to fail loudly if a future change moves the drift
materially - we want that as a flag, not a silent regression.

If you legitimately need to widen these thresholds, do it in the same
PR as the change that widened them, with a comment explaining why.

Pairs covered today:
  - txtrs (R-anchored) vs txtrs-av (AV-first), in baseline + low_return + high_discount.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pension_model.runners import run_truth_table


PAIRS = [
    ("txtrs", "txtrs-av"),
]
SCENARIOS = ["baseline", "low_return", "high_discount"]

# Year-0 anchors: tight bound. Both plans calibrate to the same
# AV-published year-0 totals, so any meaningful drift here means
# calibration has changed shape on one side.
Y0_ANCHOR_METRICS = [
    "aal_boy",
    "ava_boy",
    "mva_boy",
    "fr_ava_boy",
    "fr_mva_boy",
    "payroll",
    "n_active_boy",
]
Y0_ANCHOR_REL_TOL = 0.01  # 1% relative

# Multi-year drift bounds: looser, set to today's worst case + headroom.
# Today's worst observed: aal/ava/mva ~12-19%, funded ratios ~6%.
# Per-metric maximum across all years and all scenarios.
DRIFT_BOUNDS_PCT = {
    "aal_boy": 25.0,
    "ava_boy": 25.0,
    "mva_boy": 25.0,
    "fr_ava_boy": 10.0,
    "fr_mva_boy": 10.0,
    "payroll": 1.0,
    "n_active_boy": 1.0,
}


@pytest.fixture(scope="module")
def truth_tables():
    """Build truth tables once per (plan, scenario) and reuse across cases."""
    cache: dict[tuple[str, str], pd.DataFrame] = {}
    for plan_a, plan_b in PAIRS:
        for plan in (plan_a, plan_b):
            for scenario in SCENARIOS:
                key = (plan, scenario)
                if key not in cache:
                    cache[key] = run_truth_table(plan, scenario)
    return cache


def _rel_pct(value_a: float, value_b: float) -> float:
    if not np.isfinite(value_a) or not np.isfinite(value_b):
        return np.nan
    if abs(value_a) < 1e-12:
        return np.nan
    return abs(value_b - value_a) / abs(value_a) * 100.0


@pytest.mark.parametrize(
    "plan_a,plan_b,scenario",
    [(a, b, s) for a, b in PAIRS for s in SCENARIOS],
    ids=[f"{a}-vs-{b}-{s}" for a, b in PAIRS for s in SCENARIOS],
)
def test_year0_anchor_agreement(truth_tables, plan_a, plan_b, scenario):
    """Year-0 anchors must agree within Y0_ANCHOR_REL_TOL across both plans."""
    a = truth_tables[(plan_a, scenario)]
    b = truth_tables[(plan_b, scenario)]

    y0_year = min(a["year"].min(), b["year"].min())
    a0 = a[a["year"] == y0_year].iloc[0]
    b0 = b[b["year"] == y0_year].iloc[0]

    failures = []
    for metric in Y0_ANCHOR_METRICS:
        if metric not in a0.index or metric not in b0.index:
            continue
        rel = _rel_pct(float(a0[metric]), float(b0[metric]))
        if not np.isfinite(rel):
            continue
        if rel > Y0_ANCHOR_REL_TOL * 100:
            failures.append(
                f"{metric}: {plan_a}={a0[metric]:.6g} vs {plan_b}={b0[metric]:.6g} "
                f"(rel diff {rel:.4f}%)"
            )
    assert not failures, (
        f"Year-{y0_year} anchors diverge beyond {Y0_ANCHOR_REL_TOL*100:.2f}% "
        f"for {plan_a} vs {plan_b} in {scenario}:\n  "
        + "\n  ".join(failures)
    )


@pytest.mark.parametrize(
    "plan_a,plan_b,scenario",
    [(a, b, s) for a, b in PAIRS for s in SCENARIOS],
    ids=[f"{a}-vs-{b}-{s}" for a, b in PAIRS for s in SCENARIOS],
)
def test_drift_within_bounds(truth_tables, plan_a, plan_b, scenario):
    """Per-metric max drift across all years stays within DRIFT_BOUNDS_PCT."""
    a = truth_tables[(plan_a, scenario)].set_index("year")
    b = truth_tables[(plan_b, scenario)].set_index("year")
    common_years = sorted(set(a.index).intersection(b.index))

    failures = []
    for metric, bound_pct in DRIFT_BOUNDS_PCT.items():
        if metric not in a.columns or metric not in b.columns:
            continue
        va = a.loc[common_years, metric].astype(float).to_numpy()
        vb = b.loc[common_years, metric].astype(float).to_numpy()
        denom = np.where(np.abs(va) > 1e-12, np.abs(va), np.nan)
        rel_pct = np.abs(vb - va) / denom * 100.0
        max_rel = float(np.nanmax(rel_pct)) if np.isfinite(rel_pct).any() else 0.0
        if max_rel > bound_pct:
            argmax = int(np.nanargmax(rel_pct))
            year = common_years[argmax]
            failures.append(
                f"{metric}: max rel drift {max_rel:.2f}% > bound {bound_pct:.1f}% "
                f"(year {year}: {plan_a}={va[argmax]:.6g}, {plan_b}={vb[argmax]:.6g})"
            )
    assert not failures, (
        f"Drift exceeds bounds for {plan_a} vs {plan_b} in {scenario}:\n  "
        + "\n  ".join(failures)
        + "\n\nIf the change is intentional, widen DRIFT_BOUNDS_PCT in this file "
        "with a comment explaining why."
    )
