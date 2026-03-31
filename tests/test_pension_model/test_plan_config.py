"""
Equivalence tests: config-driven plan_config vs hardcoded tier_logic.

Proves that the new PlanConfig-driven tier determination, benefit multiplier,
and reduction factor functions produce identical results to the original
hardcoded tier_logic.py for every relevant (class, entry_year, age, yos) combo.
"""

import math
import pytest
import numpy as np

from pension_model.core.tier_logic import (
    get_tier as old_get_tier,
    get_ben_mult as old_get_ben_mult,
    get_reduce_factor as old_get_reduce_factor,
    get_sep_type as old_get_sep_type,
)
from pension_model.plan_config import (
    load_frs_config,
    get_tier as new_get_tier,
    get_ben_mult as new_get_ben_mult,
    get_reduce_factor as new_get_reduce_factor,
    get_sep_type as new_get_sep_type,
)

CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]


@pytest.fixture(scope="module")
def frs_config():
    return load_frs_config()


# ---------------------------------------------------------------------------
# Test get_tier equivalence
# ---------------------------------------------------------------------------

class TestTierEquivalence:
    """Config-driven get_tier must match hardcoded get_tier for all FRS combos."""

    # Sample entry years spanning all three tiers
    ENTRY_YEARS = [1985, 2000, 2010, 2011, 2015, 2020, 2023, 2024, 2025, 2030]
    AGES = list(range(20, 80, 3))
    YOS_VALUES = [0, 3, 5, 6, 8, 10, 15, 20, 25, 28, 30, 33, 36, 40]

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_tier_matches_all_combos(self, frs_config, class_name):
        """Exhaustive check across entry_year × age × yos grid."""
        mismatches = []
        for ey in self.ENTRY_YEARS:
            for age in self.AGES:
                for yos in self.YOS_VALUES:
                    if yos > age - 18:  # yos can't exceed working years
                        continue
                    old = old_get_tier(class_name, ey, age, yos)
                    new = new_get_tier(frs_config, class_name, ey, age, yos)
                    if old != new:
                        mismatches.append((ey, age, yos, old, new))

        if mismatches:
            sample = mismatches[:10]
            msg = f"{len(mismatches)} mismatches for {class_name}. First 10:\n"
            for ey, age, yos, old, new in sample:
                msg += f"  ey={ey}, age={age}, yos={yos}: old={old}, new={new}\n"
            pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test get_ben_mult equivalence
# ---------------------------------------------------------------------------

class TestBenMultEquivalence:
    """Config-driven get_ben_mult must match hardcoded version."""

    TIERS = [
        "tier_1_norm", "tier_1_early", "tier_1_vested",
        "tier_2_norm", "tier_2_early", "tier_2_vested",
        "tier_3_norm", "tier_3_early", "tier_3_vested",
    ]
    AGES = list(range(50, 75))
    YOS_VALUES = list(range(5, 40))

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_ben_mult_matches(self, frs_config, class_name):
        mismatches = []
        for tier in self.TIERS:
            for age in self.AGES:
                for yos in self.YOS_VALUES:
                    old = old_get_ben_mult(class_name, tier, age, yos)
                    new = new_get_ben_mult(frs_config, class_name, tier, age, yos)
                    # Both NaN = match
                    if math.isnan(old) and math.isnan(new):
                        continue
                    if old != new:
                        mismatches.append((tier, age, yos, old, new))

        if mismatches:
            sample = mismatches[:10]
            msg = f"{len(mismatches)} mismatches for {class_name}. First 10:\n"
            for tier, age, yos, old, new in sample:
                msg += f"  tier={tier}, age={age}, yos={yos}: old={old:.4f}, new={new}\n"
            pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test get_reduce_factor equivalence
# ---------------------------------------------------------------------------

class TestReduceFactorEquivalence:
    """Config-driven get_reduce_factor must match hardcoded version."""

    TIERS = [
        "tier_1_norm", "tier_1_early",
        "tier_2_norm", "tier_2_early",
        "tier_3_norm", "tier_3_early",
    ]
    AGES = list(range(45, 70))

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_reduce_factor_matches(self, frs_config, class_name):
        mismatches = []
        for tier in self.TIERS:
            for age in self.AGES:
                old = old_get_reduce_factor(class_name, tier, age)
                new = new_get_reduce_factor(frs_config, class_name, tier, age)
                if math.isnan(old) and math.isnan(new):
                    continue
                if abs(old - new) > 1e-10:
                    mismatches.append((tier, age, old, new))

        if mismatches:
            sample = mismatches[:10]
            msg = f"{len(mismatches)} mismatches for {class_name}. First 10:\n"
            for tier, age, old, new in sample:
                msg += f"  tier={tier}, age={age}: old={old:.4f}, new={new:.4f}\n"
            pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test get_sep_type (trivial — same function, but verify anyway)
# ---------------------------------------------------------------------------

class TestSepTypeEquivalence:
    TIERS = [
        "tier_1_norm", "tier_1_early", "tier_1_vested", "tier_1_non_vested",
        "tier_2_norm", "tier_2_early", "tier_2_vested", "tier_2_non_vested",
        "tier_3_norm", "tier_3_early", "tier_3_vested", "tier_3_non_vested",
    ]

    def test_sep_type_matches(self):
        for tier in self.TIERS:
            assert old_get_sep_type(tier) == new_get_sep_type(tier), f"Mismatch for {tier}"


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
