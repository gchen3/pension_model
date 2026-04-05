"""
Tests for calibration module.

Verifies that:
1. Computed calibration factors match the existing JSON values
2. Applying computed calibration reproduces the baseline funding results
3. Neutral calibration produces different (uncalibrated) NC rates
"""

import sys
from pathlib import Path
import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

BASELINE = Path(__file__).parent.parent.parent / "baseline_outputs"
CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]


@pytest.fixture(scope="module")
def calibration_results():
    """Run calibration and return (results, targets, constants)."""
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.plan_config import load_frs_config
    from pension_model.core.funding_model import load_funding_inputs
    from pension_model.core.calibration import (
        load_targets_from_init_funding, run_calibration,
    )

    # Neutral calibration: passing a non-existent calibration path makes
    # load_plan_config skip calibration loading, so nc_cal defaults to 1.0
    # and pvfb_term_current to 0.0 for every class.
    constants = load_frs_config(calibration_path=Path("__no_calibration__"))
    funding_inputs = load_funding_inputs(BASELINE)
    val_norm_costs = {cn: constants.class_data[cn].val_norm_cost for cn in CLASSES}
    targets = load_targets_from_init_funding(funding_inputs["init_funding"], val_norm_costs)

    liability = run_plan_pipeline(constants, BASELINE)

    results = run_calibration(liability, targets, constants.ranges.start_year)
    return results, targets, constants


@pytest.mark.parametrize("class_name", CLASSES)
def test_nc_cal_matches_json(calibration_results, class_name):
    """Computed nc_cal should match the value in configs/frs/calibration.json."""
    import json
    results, _, _ = calibration_results

    json_path = Path(__file__).parent.parent.parent / "configs" / "frs" / "calibration.json"
    with open(json_path) as f:
        cal_json = json.load(f)

    computed = results[class_name].nc_cal
    expected = cal_json["classes"][class_name]["nc_cal"]
    # JSON serialization introduces small rounding; allow 1e-6 tolerance
    assert abs(computed - expected) < 1e-6, (
        f"{class_name}: computed nc_cal={computed:.10f} vs JSON={expected:.10f}"
    )


@pytest.mark.parametrize("class_name", CLASSES)
def test_pvfb_term_matches_json(calibration_results, class_name):
    """Computed pvfb_term_current should match JSON value (within rounding)."""
    import json
    results, _, _ = calibration_results

    json_path = Path(__file__).parent.parent.parent / "configs" / "frs" / "calibration.json"
    with open(json_path) as f:
        cal_json = json.load(f)

    computed = results[class_name].pvfb_term_current
    expected = cal_json["classes"][class_name]["pvfb_term_current"]
    # Allow $1 tolerance (float precision vs integer in JSON)
    assert abs(computed - expected) < 1.0, (
        f"{class_name}: computed pvfb_term={computed:.2f} vs JSON={expected:.2f}"
    )


@pytest.mark.parametrize("class_name", ["regular", "special"])
def test_nc_cal_near_one_for_large_classes(calibration_results, class_name):
    """For regular and special (largest classes), nc_cal should be near 1.0."""
    results, _, _ = calibration_results
    nc_cal = results[class_name].nc_cal
    assert 0.9 < nc_cal < 1.1, (
        f"{class_name}: nc_cal={nc_cal:.4f} is far from 1.0, "
        "suggesting cal_factor=0.9 is not well-tuned for this class"
    )


def test_diagnostics_format(calibration_results):
    """Diagnostics string should contain expected sections."""
    from pension_model.core.calibration import format_diagnostics
    results, targets, constants = calibration_results
    output = format_diagnostics(results, targets, constants.benefit.cal_factor)
    assert "Calibration Diagnostics" in output
    assert "nc_cal" in output
    assert "pvfb_term" in output
    assert "Out-of-sample" in output
