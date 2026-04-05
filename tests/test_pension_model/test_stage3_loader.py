"""
Regression tests for the stage 3 data loader.

These tests exercise the stage 3 path explicitly — the pre-existing 230-test
FRS suite runs through `ModelConstants` + `_load_frs_inputs` (the Excel
loader) and never touches the stage 3 code, so bugs in the stage 3 path can
survive the existing suite.

History
-------
On 2026-04-04 `_build_mortality_from_csv` was found to hardcode the mortality
table to "general" for every class, ignoring the per-class `base_table_map`
in plan_config. This caused FRS special and admin classes to silently use
general mortality rates instead of safety rates, which in turn made active
annuity factors diverge from R by ~2-3% for those classes. The bug was
invisible to the existing tests because they never called the stage 3 loader.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

FRS_CLASSES = ["regular", "special", "admin", "eco", "eso",
               "judges", "senior_management"]


@pytest.fixture(scope="module")
def frs_config():
    from pension_model.plan_config import load_frs_config
    return load_frs_config()


@pytest.fixture(scope="module")
def raw_dir():
    return Path(__file__).parent.parent.parent / "R_model" / "R_model_frs"


@pytest.mark.parametrize("class_name", FRS_CLASSES)
def test_stage3_mortality_matches_excel(class_name, frs_config, raw_dir):
    """Stage 3 CSV mortality must match the Excel-built mortality for every
    FRS class, across a wide range of ages and years, for both active and
    retiree rates.

    Guards against the base_table_map lookup bug: if _build_mortality_from_csv
    ever regresses to hardcoding a single table, special/admin will diverge.
    """
    from pension_model.core.data_loader import _build_mortality_from_csv
    from pension_model.core.mortality_builder import build_compact_mortality_from_excel

    mort_dir = Path(__file__).parent.parent.parent / "data" / "frs" / "mortality"
    pub2010 = raw_dir / "pub-2010-headcount-mort-rates.xlsx"
    mp2018 = raw_dir / "mortality-improvement-scale-mp-2018-rates.xlsx"

    if not pub2010.exists() or not mort_dir.exists():
        pytest.skip("FRS Excel inputs or stage 3 mortality CSVs not available")

    cm_csv = _build_mortality_from_csv(frs_config, mort_dir, class_name)
    cm_xlsx = build_compact_mortality_from_excel(
        pub2010, mp2018, class_name, constants=frs_config
    )

    max_diff = 0.0
    for age in range(18, 121):
        for year in (2022, 2030, 2050, 2080):
            for is_retiree in (True, False):
                d = abs(
                    cm_csv.get_rate(age, year, is_retiree)
                    - cm_xlsx.get_rate(age, year, is_retiree)
                )
                if d > max_diff:
                    max_diff = d

    assert max_diff < 1e-12, (
        f"{class_name}: stage 3 mortality differs from Excel by {max_diff:.2e} "
        f"(expected zero). Check _build_mortality_from_csv uses base_table_map."
    )


@pytest.mark.parametrize("class_name", ["special", "admin"])
def test_stage3_mortality_uses_safety_table(class_name, frs_config):
    """Explicit check that the per-class base_table_map is being honored for
    FRS classes that should use the safety mortality table.

    At age 30, safety mortality is materially different from general, so a
    wrong-table bug would show up here as a clearly non-zero diff.
    """
    from pension_model.core.data_loader import _build_mortality_from_csv
    from pension_model.core.mortality_builder import build_compact_mortality_from_csv

    mort_dir = Path(__file__).parent.parent.parent / "data" / "frs" / "mortality"
    if not mort_dir.exists():
        pytest.skip("Stage 3 FRS mortality CSVs not available")

    cm_via_loader = _build_mortality_from_csv(frs_config, mort_dir, class_name)
    cm_safety = build_compact_mortality_from_csv(
        mort_dir / "base_rates.csv",
        mort_dir / "improvement_scale.csv",
        class_name,
        table_name="safety",
        min_age=frs_config.ranges.min_age,
        max_age=frs_config.ranges.max_age,
        max_year=(frs_config.ranges.start_year + frs_config.ranges.model_period
                  + frs_config.ranges.max_age - frs_config.ranges.min_age),
        constants=frs_config,
        male_mp_forward_shift=0,
    )

    # Spot-check one rate that differs between safety and general
    assert (
        abs(cm_via_loader.get_rate(30, 2022, False)
            - cm_safety.get_rate(30, 2022, False)) < 1e-12
    ), f"{class_name} should load the safety table via base_table_map"
