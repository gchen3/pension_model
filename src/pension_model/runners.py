"""Convenience runners for one-off pipeline runs.

These wrap the standard pipeline / funding / truth-table chain so
scripts and tests don't each repeat the boilerplate. Not intended for
high-throughput use - data prep, calibration CLI, and the cell-level
diagnostic scripts each go through here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _scenario_path(scenario: Optional[str]) -> Optional[Path]:
    if scenario is None or scenario == "baseline":
        return None
    return PROJECT_ROOT / "scenarios" / f"{scenario}.json"


def run_truth_table(plan: str, scenario: Optional[str] = None) -> pd.DataFrame:
    """Run the full pipeline for ``(plan, scenario)`` and return its truth table.

    ``scenario=None`` and ``scenario="baseline"`` both mean "no scenario
    overrides" - the plan's defaults stand. Any other string is looked
    up as ``scenarios/<name>.json``.
    """
    from pension_model.config_loading import load_plan_config
    from pension_model.core.funding_model import load_funding_inputs, run_funding_model
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.truth_table import build_python_truth_table

    config_path = PROJECT_ROOT / "plans" / plan / "config" / "plan_config.json"
    calibration_path = PROJECT_ROOT / "plans" / plan / "config" / "calibration.json"
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
