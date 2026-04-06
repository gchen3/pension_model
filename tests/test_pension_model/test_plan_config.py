"""
Tests for PlanConfig loading and properties.

Verifies that plan configs load correctly for both FRS and TRS,
and that all derived properties match expected values.
"""

import pytest

from pension_model.plan_config import load_frs_config


@pytest.fixture(scope="module")
def frs_config():
    return load_frs_config()


# ---------------------------------------------------------------------------
# Test PlanConfig loads correctly
# ---------------------------------------------------------------------------

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
        acfr = frs_config.get_acfr("regular")
        assert acfr["outflow"] == 8_967_096_000
        assert acfr["val_norm_cost"] == 0.0896
        # Calibration should be applied
        assert acfr["nc_cal"] != 1.0  # calibration loaded

    def test_frs_ben_payment_ratio(self, frs_config):
        bpr = frs_config.ben_payment_ratio
        assert 0.9 < bpr < 1.0

    def test_txtrs_loads(self):
        from pension_model.plan_config import load_txtrs_config
        config = load_txtrs_config()
        assert config.plan_name == "txtrs"
        assert len(config.classes) == 1
        assert config.classes[0] == "all"
        assert config.dr_current == 0.07
        assert config.db_ee_cont_rate == 0.0825
        assert config.cash_balance is not None
        assert config.cash_balance["ee_pay_credit"] == 0.06

    def test_frs_tier_lookups(self, frs_config):
        """Tier lookup tables are populated correctly."""
        assert frs_config._tier_name_to_id == {"tier_1": 0, "tier_2": 1, "tier_3": 2}
        assert frs_config._tier_id_to_name == ("tier_1", "tier_2", "tier_3")
        assert frs_config._tier_id_to_fas_years == (5, 8, 8)
