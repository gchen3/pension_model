"""
Validate funding model output against R baseline.

Each test runs the full end-to-end pipeline for a class and compares
key funding columns against R's extracted funding CSVs.
"""

import sys
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

BASELINE = Path(__file__).parent.parent.parent / "baseline_outputs"
CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]

FUNDING_COLS = [
    "total_aal", "total_ava", "total_mva", "total_er_cont", "fr_ava",
    "total_payroll", "nc_rate_db_legacy", "er_amo_cont_legacy",
]


@pytest.fixture(scope="module")
def funding_results():
    """Run the full pipeline once and cache results for all tests."""
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.core.funding_model import load_funding_inputs, compute_funding
    from pension_model.plan_config import load_frs_config

    constants = load_frs_config()
    liability = run_plan_pipeline(constants, BASELINE)
    funding_inputs = load_funding_inputs(BASELINE)
    return compute_funding(liability, funding_inputs, constants)


@pytest.mark.parametrize("class_name", CLASSES)
def test_funding_matches_r_baseline(class_name, funding_results):
    """Verify Python funding output matches R baseline for each class."""
    rf = pd.read_csv(BASELINE / f"{class_name}_funding.csv")
    pf = funding_results[class_name]

    max_diff = 0
    for col in FUNDING_COLS:
        if col in pf.columns and col in rf.columns:
            rv, pv = rf[col].values, pf[col].values
            mask = np.abs(rv) > 1e-6
            n = min(mask.sum(), len(pv))
            if n > 0:
                pct = np.abs(pv[mask[:len(pv)]][:n] - rv[mask][:n]) / np.abs(rv[mask][:n]) * 100
                max_diff = max(max_diff, pct.max())

    assert max_diff < 0.01, f"{class_name}: funding max diff {max_diff:.4f}%"
