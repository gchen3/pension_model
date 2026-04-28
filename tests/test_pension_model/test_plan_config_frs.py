"""FRS-specific PlanConfig tests."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

from pension_model.config_loading import load_plan_config
from pension_model.plan_config import load_frs_config


@pytest.fixture(scope="module")
def frs_config():
    return load_frs_config()


class TestPlanConfigLoad:
    def test_frs_loads(self, frs_config):
        assert frs_config.plan_name == "frs"
        assert len(frs_config.classes) == 7
        assert frs_config.dr_current == 0.067
        assert frs_config.new_year == 2024
        assert frs_config.model_period == 30

    def test_frs_class_groups(self, frs_config):
        assert frs_config.class_group("regular") == "regular_group"
        assert frs_config.class_group("special") == "special_group"
        assert frs_config.class_group("admin") == "special_group"
        assert frs_config.is_special("special")
        assert frs_config.is_special("admin")
        assert not frs_config.is_special("regular")

    def test_frs_acfr(self, frs_config):
        acfr = frs_config.get_class_inputs("regular")
        assert abs(acfr["ben_payment"] - 8_391_759_183.37) < 1.0
        assert acfr["val_norm_cost"] == 0.0896
        assert acfr["nc_cal"] != 1.0

    def test_frs_tier_lookups(self, frs_config):
        assert frs_config._tier_name_to_id == {"tier_1": 0, "tier_2": 1, "tier_3": 2}
        assert frs_config._tier_id_to_name == ("tier_1", "tier_2", "tier_3")
        assert frs_config._tier_id_to_fas_years == (5, 8, 8)


class TestBaselineDrCurrentSnapshot:
    """The baseline dr_current must survive scenario overrides.

    The synthetic term-vested cashflow stream is sized at the rate the
    input PVFB was published at; that rate stays at baseline regardless
    of scenario. See docs/design/discount_rate_scenarios.md.
    """

    def test_baseline_equals_dr_current_when_no_scenario(self, frs_config):
        assert frs_config.baseline_dr_current == frs_config.dr_current == 0.067

    def test_baseline_preserved_under_high_discount(self):
        root = Path(__file__).resolve().parents[2]
        config = load_plan_config(
            root / "plans" / "frs" / "config" / "plan_config.json",
            calibration_path=root / "plans" / "frs" / "config" / "calibration.json",
            scenario_path=root / "scenarios" / "high_discount.json",
        )
        assert config.baseline_dr_current == 0.067
        assert config.dr_current == 0.075
        assert config.economic.baseline_dr_current == 0.067
        assert config.economic.dr_current == 0.075
