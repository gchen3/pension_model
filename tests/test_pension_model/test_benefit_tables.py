"""
Tests for benefit table construction.

Each test validates a computation step against R's extracted intermediate data.
This ensures end-to-end correctness from raw inputs to final outputs.
"""

import sys
from pathlib import Path
import pytest
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

BASELINE = Path(__file__).parent.parent.parent / "baseline_outputs"
CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]


class TestSalaryHeadcountTable:
    """Test build_salary_headcount_table against R's extracted output."""

    @pytest.fixture
    def salary_growth(self):
        return pd.read_csv(BASELINE / "salary_growth_table.csv")

    def _load_raw(self, class_name):
        """Load raw wide-format salary and headcount tables."""
        sal = pd.read_csv(BASELINE / f"{class_name}_salary.csv")
        hc = pd.read_csv(BASELINE / f"{class_name}_headcount.csv")
        return sal, hc

    def _load_r_result(self, class_name):
        """Load R's salary_headcount_table for comparison."""
        return pd.read_csv(BASELINE / f"{class_name}_salary_headcount.csv")

    def _get_adjustment_ratio(self, class_name):
        """Compute headcount adjustment ratio matching R model."""
        from pension_model.core.model_constants import frs_constants
        c = frs_constants()

        if class_name in ("eco", "eso", "judges"):
            # R uses a shared ratio: combined_total / combined_raw_count
            combined_total = 2075  # eco_eso_judges_total_active_member_
            eco_hc = pd.read_csv(BASELINE / "eco_headcount.csv")
            eso_hc = pd.read_csv(BASELINE / "eso_headcount.csv")
            judges_hc = pd.read_csv(BASELINE / "judges_headcount.csv")
            raw = (eco_hc.iloc[:, 1:].sum().sum()
                   + eso_hc.iloc[:, 1:].sum().sum()
                   + judges_hc.iloc[:, 1:].sum().sum())
            return combined_total / raw
        else:
            total = c.class_data[class_name].total_active_member
            hc = pd.read_csv(BASELINE / f"{class_name}_headcount.csv")
            raw = hc.iloc[:, 1:].sum().sum()
            return total / raw

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_salary_headcount_matches_r(self, class_name, salary_growth):
        """Verify Python salary_headcount_table matches R for each class."""
        from pension_model.core.benefit_tables import build_salary_headcount_table

        sal, hc = self._load_raw(class_name)
        adj_ratio = self._get_adjustment_ratio(class_name)

        py = build_salary_headcount_table(
            salary_wide=sal,
            headcount_wide=hc,
            salary_growth=salary_growth,
            class_name=class_name,
            adjustment_ratio=adj_ratio,
            start_year=2022,
        )

        r = self._load_r_result(class_name)

        # Compare: merge on keys, check entry_salary
        merged = py.merge(r, on=["entry_year", "entry_age"], suffixes=("_py", "_r"))

        assert len(merged) > 0, f"No matching rows for {class_name}"

        # entry_salary should match
        mask = merged["entry_salary_r"].notna() & (merged["entry_salary_r"].abs() > 0)
        if mask.any():
            pct_diff = (
                (merged.loc[mask, "entry_salary_py"] - merged.loc[mask, "entry_salary_r"]).abs()
                / merged.loc[mask, "entry_salary_r"].abs()
                * 100
            )
            max_diff = pct_diff.max()
            assert max_diff < 0.01, (
                f"{class_name}: entry_salary max diff {max_diff:.4f}%"
            )

        # count should match
        mask_c = merged["count_r"].notna() & (merged["count_r"].abs() > 0)
        if mask_c.any():
            pct_diff_c = (
                (merged.loc[mask_c, "count_py"] - merged.loc[mask_c, "count_r"]).abs()
                / merged.loc[mask_c, "count_r"].abs()
                * 100
            )
            max_diff_c = pct_diff_c.max()
            assert max_diff_c < 0.01, (
                f"{class_name}: count max diff {max_diff_c:.4f}%"
            )


class TestSeparationRateTable:
    """Test build_separation_rate_table against R's extracted output."""

    # R's separation table class mapping (benefit model line 584-590)
    SEP_CLASS_MAP = {
        "regular": "regular", "special": "special", "admin": "admin",
        "eco": "eco", "eso": "regular", "judges": "judges",
        "senior_management": "senior_management",
    }

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_separation_rate_matches_r(self, class_name):
        """Verify separation rates match R for each class."""
        from pension_model.core.benefit_tables import (
            build_salary_headcount_table,
            build_entrant_profile,
            build_separation_rate_table,
        )
        from pension_model.core.model_constants import frs_constants

        constants = frs_constants()
        sg = pd.read_csv(BASELINE / "salary_growth_table.csv")

        # ESO uses Regular's separation table (R line 588)
        sep_class = self.SEP_CLASS_MAP[class_name]
        sal = pd.read_csv(BASELINE / f"{sep_class}_salary.csv")
        hc = pd.read_csv(BASELINE / f"{sep_class}_headcount.csv")

        if sep_class in ("eco", "eso", "judges"):
            combined_raw = sum(
                pd.read_csv(BASELINE / f"{c}_headcount.csv").iloc[:, 1:].sum().sum()
                for c in ("eco", "eso", "judges")
            )
            adj_ratio = 2075 / combined_raw
        else:
            adj_ratio = constants.class_data[sep_class].total_active_member / hc.iloc[:, 1:].sum().sum()

        sh = build_salary_headcount_table(sal, hc, sg, sep_class, adj_ratio, 2022)
        ep = build_entrant_profile(sh)

        dt = BASELINE / "decrement_tables"
        sep = build_separation_rate_table(
            term_rate_avg=pd.read_csv(dt / f"{sep_class}_term_rate_avg.csv"),
            normal_retire_rate_tier1=pd.read_csv(dt / f"{sep_class}_normal_retire_rate_tier1.csv"),
            normal_retire_rate_tier2=pd.read_csv(dt / f"{sep_class}_normal_retire_rate_tier2.csv"),
            early_retire_rate_tier1=pd.read_csv(dt / f"{sep_class}_early_retire_rate_tier1.csv"),
            early_retire_rate_tier2=pd.read_csv(dt / f"{sep_class}_early_retire_rate_tier2.csv"),
            entrant_profile=ep,
            class_name=sep_class,
            constants=constants,
        )

        r = pd.read_csv(BASELINE / f"{class_name}_sep_rate.csv")
        m = sep.merge(r, on=["entry_year", "entry_age", "yos"], suffixes=("_py", "_r"))

        mask = m["separation_rate_r"].notna() & (m["separation_rate_r"].abs() > 1e-10)
        if mask.any():
            pct = (
                (m.loc[mask, "separation_rate_py"] - m.loc[mask, "separation_rate_r"]).abs()
                / m.loc[mask, "separation_rate_r"].abs() * 100
            )
            assert pct.max() < 0.01, f"{class_name}: separation_rate max diff {pct.max():.4f}%"


class TestAnnFactorTable:
    """Test build_ann_factor_table_compact against R's extracted cum_mort_dr and ann_factor."""

    RAW_DIR = Path(__file__).parent.parent.parent / "R_model" / "R_model_original"

    def _build_compact_aft(self):
        """Build ann_factor_table from raw Excel for Regular, entry_year=2000 only."""
        from pension_model.core.benefit_tables import (
            build_ann_factor_table_compact, build_salary_headcount_table,
            build_entrant_profile, build_salary_benefit_table,
        )
        from pension_model.core.mortality_builder import build_compact_mortality_from_excel
        from pension_model.core.tier_logic import get_tier
        from pension_model.core.model_constants import frs_constants

        constants = frs_constants()
        cm = build_compact_mortality_from_excel(
            self.RAW_DIR / "pub-2010-headcount-mort-rates.xlsx",
            self.RAW_DIR / "mortality-improvement-scale-mp-2018-rates.xlsx",
            "regular",
        )
        sg = pd.read_csv(BASELINE / "salary_growth_table.csv")
        sal = pd.read_csv(BASELINE / "regular_salary.csv")
        hc = pd.read_csv(BASELINE / "regular_headcount.csv")
        adj = constants.class_data["regular"].total_active_member / hc.iloc[:, 1:].sum().sum()
        sh = build_salary_headcount_table(sal, hc, sg, "regular", adj, 2022)
        ep = build_entrant_profile(sh)
        sbt = build_salary_benefit_table(sh, ep, sg, "regular", constants, get_tier)
        # Filter to single entry_year for speed
        sbt_sub = sbt[sbt["entry_year"] == 2000].copy()
        return build_ann_factor_table_compact(sbt_sub, cm, "regular", constants)

    def test_cum_mort_dr_matches_r(self):
        """Verify cum_mort_dr matches R for a subset of Regular class."""
        aft = self._build_compact_aft()
        bt = pd.read_csv(BASELINE / "regular_bt_term.csv")
        bt_sub = bt[bt["entry_year"] == 2000]

        m = bt_sub.merge(
            aft[["entry_year", "entry_age", "dist_age", "dist_year", "yos", "cum_mort_dr"]],
            on=["entry_age", "entry_year", "dist_age", "dist_year", "yos"],
            suffixes=("_r", "_py"),
        )

        mask = m["cum_mort_dr_r"].notna() & (m["cum_mort_dr_r"].abs() > 1e-10)
        if mask.any():
            pct = (
                (m.loc[mask, "cum_mort_dr_py"] - m.loc[mask, "cum_mort_dr_r"]).abs()
                / m.loc[mask, "cum_mort_dr_r"].abs() * 100
            )
            assert pct.max() < 0.01, f"cum_mort_dr max diff {pct.max():.4f}%"

    def test_ann_factor_matches_r(self):
        """Verify ann_factor matches R for a subset of Regular class."""
        aft = self._build_compact_aft()

        af = pd.read_csv(BASELINE / "regular_af_retire.csv")
        af_sub = af[af["entry_year"] == 2000]

        m = af_sub.merge(
            aft[["entry_year", "entry_age", "dist_age", "dist_year", "yos", "ann_factor"]],
            on=["entry_age", "entry_year", "dist_age", "dist_year", "yos"],
            suffixes=("_r", "_py"),
        )

        mask = m["ann_factor_r"].notna() & (m["ann_factor_r"].abs() > 1e-10)
        if mask.any():
            pct = (
                (m.loc[mask, "ann_factor_py"] - m.loc[mask, "ann_factor_r"]).abs()
                / m.loc[mask, "ann_factor_r"].abs() * 100
            )
            assert pct.max() < 0.01, f"ann_factor max diff {pct.max():.4f}%"


class TestSalaryBenefitTable:
    """Test build_salary_benefit_table against R's benefit_data.csv."""

    @pytest.mark.parametrize("class_name", ["regular"])
    def test_salary_fas_match_r(self, class_name):
        """Verify salary and FAS match R's benefit_data for Regular class."""
        from pension_model.core.benefit_tables import (
            build_salary_headcount_table,
            build_entrant_profile,
            build_salary_benefit_table,
        )
        from pension_model.core.tier_logic import get_tier
        from pension_model.core.model_constants import frs_constants

        constants = frs_constants()
        salary_growth = pd.read_csv(BASELINE / "salary_growth_table.csv")
        sal = pd.read_csv(BASELINE / f"{class_name}_salary.csv")
        hc = pd.read_csv(BASELINE / f"{class_name}_headcount.csv")

        sh = build_salary_headcount_table(
            sal, hc, salary_growth, class_name,
            constants.class_data[class_name].total_active_member, 2022,
        )
        ep = build_entrant_profile(sh)

        sbt = build_salary_benefit_table(
            sh, ep, salary_growth, class_name, constants, get_tier,
        )

        # Load R's benefit_data for comparison
        r_bvt = pd.read_csv(BASELINE / f"{class_name}_benefit_data.csv")

        # Compare salary for a sample of entry_year/entry_age/yos combinations
        sample = r_bvt[r_bvt["entry_year"] == 2000].head(20)
        for _, row in sample.iterrows():
            py_row = sbt[
                (sbt["entry_year"] == row["entry_year"])
                & (sbt["entry_age"] == row["entry_age"])
                & (sbt["yos"] == row["yos"])
            ]
            if len(py_row) > 0:
                py_sal = py_row.iloc[0]["salary"]
                r_sal = row["salary"]
                if r_sal > 0:
                    pct = abs(py_sal - r_sal) / r_sal * 100
                    assert pct < 0.01, (
                        f"Salary mismatch at ey={row['entry_year']}, ea={row['entry_age']}, "
                        f"yos={row['yos']}: py={py_sal:.2f} r={r_sal:.2f} diff={pct:.4f}%"
                    )
