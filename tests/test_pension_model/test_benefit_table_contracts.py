"""Regression tests for benefit-table merge-key contracts."""

from pathlib import Path
import sys

import pytest

pytestmark = [pytest.mark.regression]

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pension_model.core.pipeline import prepare_plan_run
from pension_model.plan_config import load_frs_config, load_txtrs_config


@pytest.fixture(scope="module", params=[load_frs_config, load_txtrs_config], ids=["frs", "txtrs"])
def prepared_plan_tables(request):
    constants = request.param()
    prepared = prepare_plan_run(constants, research_mode=True)
    return prepared.constants.plan_name, prepared.retained_plan_tables


def test_plan_tables_keep_unique_merge_keys(prepared_plan_tables):
    plan_name, plan_tables = prepared_plan_tables
    assert plan_tables is not None

    salary_benefit = plan_tables["salary_benefit"]
    assert salary_benefit.duplicated(
        ["class_name", "entry_year", "entry_age", "yos", "term_age"]
    ).sum() == 0, f"{plan_name}: salary_benefit merge key must stay unique"

    ann_factor = plan_tables["ann_factor"]
    assert ann_factor.duplicated(
        ["class_name", "entry_year", "entry_age", "dist_year", "dist_age", "yos", "term_year"]
    ).sum() == 0, f"{plan_name}: ann_factor merge key must stay unique"

    benefit = plan_tables["benefit"]
    assert benefit.duplicated(
        ["class_name", "entry_year", "entry_age", "term_age", "dist_age"]
    ).sum() == 0, f"{plan_name}: benefit merge key must stay unique"

    final_benefit = plan_tables["final_benefit"]
    assert final_benefit.duplicated(
        ["class_name", "entry_year", "entry_age", "term_age"]
    ).sum() == 0, f"{plan_name}: final_benefit merge key must stay unique"

    separation_rate = plan_tables["separation_rate"]
    assert separation_rate.duplicated(
        ["class_name", "entry_year", "entry_age", "term_age", "yos", "term_year"]
    ).sum() == 0, f"{plan_name}: separation_rate merge key must stay unique"

    aft_term = ann_factor[ann_factor["dist_age"] == ann_factor["entry_age"] + ann_factor["yos"]]
    assert aft_term.duplicated(
        ["class_name", "entry_year", "entry_age", "yos"]
    ).sum() == 0, f"{plan_name}: term-age annuity key must stay unique"


def test_benefit_rows_stay_contiguous_and_ordered(prepared_plan_tables):
    plan_name, plan_tables = prepared_plan_tables
    benefit = plan_tables["benefit"]
    grp_keys = ["class_name", "entry_year", "entry_age", "term_age"]

    key_frame = benefit[grp_keys]
    separated_duplicate_groups = key_frame.duplicated() & key_frame.ne(key_frame.shift()).any(axis=1)
    assert not separated_duplicate_groups.any(), (
        f"{plan_name}: benefit rows for one cohort must remain contiguous"
    )

    dist_age_monotone = benefit.groupby(
        grp_keys, sort=False, observed=True
    )["dist_age"].apply(lambda s: s.is_monotonic_increasing)
    assert bool(dist_age_monotone.all()), (
        f"{plan_name}: dist_age must stay monotone within each benefit cohort"
    )


def test_ann_factor_term_rows_align_with_salary_benefit(prepared_plan_tables):
    plan_name, plan_tables = prepared_plan_tables
    salary_benefit = plan_tables["salary_benefit"]
    ann_factor = plan_tables["ann_factor"]

    max_dist_age = int(ann_factor["dist_age"].max())
    sbt_keys = salary_benefit.loc[
        salary_benefit["term_age"] <= max_dist_age,
        ["class_name", "entry_year", "entry_age", "yos", "term_age"],
    ].reset_index(drop=True)

    ann_term_keys = ann_factor.loc[
        ann_factor["dist_age"] == ann_factor["entry_age"] + ann_factor["yos"],
        ["class_name", "entry_year", "entry_age", "yos"],
    ].reset_index(drop=True)
    ann_term_keys["term_age"] = ann_term_keys["entry_age"] + ann_term_keys["yos"]

    assert len(ann_term_keys) == len(sbt_keys), (
        f"{plan_name}: ann_factor term rows must match eligible salary_benefit rows"
    )
    assert ann_term_keys.equals(sbt_keys), (
        f"{plan_name}: ann_factor term rows must stay aligned with salary_benefit order"
    )
