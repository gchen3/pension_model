"""
Regression test: multi-class + gain_loss smoothing.

Production plans today use gain_loss only with a single class (TRS).
Phase 3 Step 2.G collapsed the two funding compute functions into one
that structurally supports any class count with any smoothing method,
but until this test the multi-class gain_loss path was never exercised.

Approach: duplicate TRS's single class into two synthetic classes with
identical inputs. Under gain_loss (per-class smoothing, no cross-class
coupling) the two class frames should be byte-identical, and the
aggregate should sum flow columns 2x.
"""

import dataclasses
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(scope="module")
def two_class_gainloss_outputs():
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.core.funding_model import load_funding_inputs, run_funding_model
    from pension_model.plan_config import load_txtrs_config

    constants = load_txtrs_config()
    liability = run_plan_pipeline(constants)
    funding_inputs = load_funding_inputs(constants.resolve_data_dir() / "funding")

    sole_class = constants.classes[0]
    one_liab = liability[sole_class]
    one_vi = constants.valuation_inputs[sole_class]
    one_cal = constants.calibration.get(sole_class, {})
    init_row = funding_inputs["init_funding"].iloc[0].to_dict()

    new_constants = dataclasses.replace(
        constants,
        classes=("a", "b"),
        valuation_inputs={"a": one_vi, "b": one_vi},
        calibration={"a": one_cal, "b": one_cal},
    )

    new_liability = {"a": one_liab.copy(), "b": one_liab.copy()}

    # Multi-class init_funding also needs an aggregate row keyed by
    # plan_name. Values are 2x the per-class init (both classes share
    # the same TRS starting values).
    agg_row = {
        k: (2 * v if isinstance(v, (int, float, np.integer, np.floating)) else v)
        for k, v in init_row.items()
    }
    new_init = pd.DataFrame([
        {**init_row, "class": "a"},
        {**init_row, "class": "b"},
        {**agg_row, "class": constants.plan_name},
    ])
    new_funding_inputs = {**funding_inputs, "init_funding": new_init}

    return run_funding_model(new_liability, new_funding_inputs, new_constants), new_constants


def test_multi_class_gainloss_runs(two_class_gainloss_outputs):
    """Two-class gain_loss completes without raising."""
    funding, constants = two_class_gainloss_outputs
    assert set(funding.keys()) == {"a", "b", constants.plan_name}


def test_multi_class_gainloss_class_frames_identical(two_class_gainloss_outputs):
    """Identical inputs -> identical per-class output frames (no cross-coupling)."""
    funding, _ = two_class_gainloss_outputs
    assert_frame_equal(funding["a"], funding["b"], check_exact=True, check_dtype=True)


@pytest.mark.parametrize("col", [
    "total_payroll",
    "nc_legacy",
    "nc_new",
    "aal_legacy",
    "total_aal",
    "ben_payment_legacy",
    "total_mva",
    "total_er_cont",
])
@pytest.mark.parametrize("i", [1, 5, 15])
def test_multi_class_gainloss_aggregate_sums_flow_cols(two_class_gainloss_outputs, col, i):
    """Aggregate flow columns accumulate to the sum of per-class values."""
    funding, constants = two_class_gainloss_outputs
    agg = funding[constants.plan_name]
    a = funding["a"]
    assert agg.loc[i, col] == pytest.approx(2 * a.loc[i, col], rel=1e-12)


def test_multi_class_gainloss_aggregate_rates_populated(two_class_gainloss_outputs):
    """is_multi_class-gated aggregate rate writes fire."""
    funding, constants = two_class_gainloss_outputs
    agg = funding[constants.plan_name]
    assert agg.loc[5, "fr_mva"] != 0
    assert agg.loc[5, "fr_ava"] != 0
    assert agg.loc[5, "total_er_cont_rate"] != 0
