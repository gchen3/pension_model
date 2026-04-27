"""R-vs-Python truth-table regression tests across (plan, scenario) cells.

These tests load each plan with each scenario (or no scenario for baseline),
run the full pipeline, and compare the resulting truth table to the R
reference baseline. Tolerance is set tight enough to catch any non-FP
divergence (max relative diff < 1e-10).

Coverage today:
  - frs x {baseline, low_return, high_discount}
  - txtrs x {baseline}

Cells without an R baseline yet (frs x no_cola, txtrs x high_discount) are
not exercised here. Generate the R baseline first, then add the cell to
the parametrize list.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = [pytest.mark.invariant, pytest.mark.regression]


REPO_ROOT = Path(__file__).resolve().parents[2]


def _r_baseline_path(plan: str, scenario: str | None) -> Path:
    if scenario is None:
        return REPO_ROOT / "plans" / plan / "baselines" / "r_truth_table.csv"
    return REPO_ROOT / "plans" / plan / "baselines" / f"r_truth_table_{scenario}.csv"


def _scenario_path(scenario: str | None) -> Path | None:
    if scenario is None:
        return None
    return REPO_ROOT / "scenarios" / f"{scenario}.json"


def _build_python_truth_table(plan: str, scenario: str | None) -> pd.DataFrame:
    from pension_model.config_loading import load_plan_config
    from pension_model.core.funding_model import load_funding_inputs, run_funding_model
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.truth_table import build_python_truth_table

    config_path = REPO_ROOT / "plans" / plan / "config" / "plan_config.json"
    calibration_path = REPO_ROOT / "plans" / plan / "config" / "calibration.json"
    constants = load_plan_config(
        config_path,
        calibration_path=calibration_path,
        scenario_path=_scenario_path(scenario),
    )
    liability = run_plan_pipeline(constants)
    funding_dir = constants.resolve_data_dir() / "funding"
    funding_inputs = load_funding_inputs(funding_dir)
    funding = run_funding_model(liability, funding_inputs, constants)
    return build_python_truth_table(plan, liability, funding, constants)


@pytest.mark.parametrize(
    "plan,scenario",
    [
        ("frs", None),
        ("frs", "low_return"),
        ("frs", "high_discount"),
        ("txtrs", None),
    ],
    ids=["frs-baseline", "frs-low_return", "frs-high_discount", "txtrs-baseline"],
)
def test_truth_table_matches_r_baseline(plan, scenario):
    r_path = _r_baseline_path(plan, scenario)
    if not r_path.exists():
        pytest.skip(f"R baseline not present: {r_path}")

    py = _build_python_truth_table(plan, scenario)
    r = pd.read_csv(r_path)

    common_numeric = [
        c for c in r.columns
        if c in py.columns
        and c not in ("plan", "year")
        and pd.api.types.is_numeric_dtype(r[c])
        and pd.api.types.is_numeric_dtype(py[c])
    ]
    assert common_numeric, f"No comparable numeric columns for {plan}/{scenario}"

    worst = []
    for col in common_numeric:
        diff = (py[col] - r[col]).abs()
        denom = r[col].abs().replace(0, np.nan)
        rel = (diff / denom).max(skipna=True)
        if pd.notna(rel) and rel > 1e-10:
            worst.append((col, float(rel), float(diff.max())))

    assert not worst, (
        f"{plan}/{scenario or 'baseline'} diverges from R beyond FP noise:\n"
        + "\n".join(f"  {c}: max rel={r:.2e}, max abs={a:.6e}" for c, r, a in worst)
    )
