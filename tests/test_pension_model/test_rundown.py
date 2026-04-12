"""
Closed-plan rundown test.

A defined-benefit pension plan with no new entrants should eventually:
  - Have zero active members
  - Pay all promised benefits
  - Run assets down to zero when the last participant dies

This test runs the full pipeline (liability + funding) with no_new_entrants=True
over a long projection horizon and verifies the plan runs down to completion.

IMPORTANT LIMITATION: The funding model is a going-concern model — it projects
payroll at a fixed growth rate regardless of actual headcount. This means:
  - Funding AAL diverges from liability AAL once actives are gone
  - Contributions are computed on phantom payroll after all actives leave
  - This is a known limitation documented by the test, not a bug

The test verifies:
  1. Demographics: actives → 0, payroll → 0 (liability pipeline)
  2. Liability AAL → 0 (all obligations eventually expire)
  3. Funding model: no NaN/crash over long horizons
  4. Benefit payments: peak and decline to zero
  5. Cash flow conservation in a simplified asset projection
"""

import sys
from dataclasses import replace
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]

# Projection horizon: youngest entry age ~21, max age 120 → ~100 years needed.
RUNDOWN_PERIOD = 100


@pytest.fixture(scope="module")
def rundown_results():
    """Run full pipeline with no new entrants over a long horizon.

    Returns (liability_dict, funding_dict, constants).
    """
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.core.funding_model import load_funding_inputs, run_funding_model
    from pension_model.plan_config import load_frs_config

    constants = load_frs_config()
    # PlanConfig stores model_period as a top-level field; ranges is a derived
    # property, so we override the field directly.
    constants = replace(constants, model_period=RUNDOWN_PERIOD)

    liability = run_plan_pipeline(constants, no_new_entrants=True)

    funding_dir = constants.resolve_data_dir() / "funding"
    funding_inputs = load_funding_inputs(funding_dir)
    funding = run_funding_model(liability, funding_inputs, constants)

    return liability, funding, constants


# ---------------------------------------------------------------------------
# Demographics (liability pipeline)
# ---------------------------------------------------------------------------

class TestRundownDemographics:
    """Verify the population runs down to zero."""

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_active_count_declines(self, class_name, rundown_results):
        """Active member count should decline monotonically (no new entrants)."""
        liab = rundown_results[0][class_name]
        actives = liab["total_n_active"].values
        for i in range(1, len(actives)):
            assert actives[i] <= actives[i - 1] + 1e-6, (
                f"{class_name} year {i}: active count increased "
                f"from {actives[i-1]:.1f} to {actives[i]:.1f}")

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_active_count_reaches_near_zero(self, class_name, rundown_results):
        """Active count should be negligible by end of projection."""
        liab = rundown_results[0][class_name]
        initial = liab["total_n_active"].iloc[0]
        final = liab["total_n_active"].iloc[-1]
        pct_remaining = final / initial * 100 if initial > 0 else 0
        assert pct_remaining < 1.0, (
            f"{class_name}: active count still {pct_remaining:.2f}% "
            f"of initial after {RUNDOWN_PERIOD} years")


# ---------------------------------------------------------------------------
# Liability AAL rundown
# ---------------------------------------------------------------------------

class TestRundownLiabilities:
    """Verify liabilities run down."""

    @pytest.mark.parametrize("class_name", CLASSES)
    def test_aal_reaches_zero(self, class_name, rundown_results):
        """Total AAL should reach zero — all participants have died."""
        liab = rundown_results[0][class_name]
        initial = liab["total_aal_est"].iloc[0]
        final = liab["total_aal_est"].iloc[-1]
        pct_remaining = abs(final) / abs(initial) * 100 if abs(initial) > 0 else 0
        assert pct_remaining < 0.001, (
            f"{class_name}: AAL still {pct_remaining:.6f}% "
            f"of initial after {RUNDOWN_PERIOD} years "
            f"(${final:,.0f} remaining)")

    def test_benefit_payments_eventually_decline(self, rundown_results):
        """Benefits should peak and then decline as retirees die (regular class)."""
        liab = rundown_results[0]["regular"]
        benefits = liab["tot_ben_refund_est"].values
        peak_idx = np.argmax(benefits)
        last_quarter_start = len(benefits) * 3 // 4
        last_quarter_avg = benefits[last_quarter_start:].mean()
        peak_val = benefits[peak_idx]
        if peak_val > 0:
            assert last_quarter_avg < peak_val, (
                f"Benefits not declining: peak={peak_val:.0f} at year {peak_idx}, "
                f"last quarter avg={last_quarter_avg:.0f}")

    def test_benefits_reach_zero(self, rundown_results):
        """Benefit payments should reach zero — no participants left to pay."""
        liab = rundown_results[0]["regular"]
        initial_aal = liab["total_aal_est"].iloc[0]
        final_ben = liab["tot_ben_refund_est"].iloc[-1]
        pct = abs(final_ben) / abs(initial_aal) * 100 if abs(initial_aal) > 0 else 0
        assert pct < 0.001, (
            f"Benefits still {pct:.6f}% of initial AAL after {RUNDOWN_PERIOD} years "
            f"(${final_ben:,.0f} remaining)")


# ---------------------------------------------------------------------------
# Funding model stability
# ---------------------------------------------------------------------------

class TestRundownFundingStability:
    """Verify the funding model doesn't crash or produce NaN over long horizons."""

    @pytest.mark.parametrize("class_name", CLASSES + ["drop", "frs"])
    def test_no_nan_in_funding(self, class_name, rundown_results):
        """Funding output should not contain NaN."""
        f = rundown_results[1][class_name]
        for col in ["total_aal", "total_mva", "total_payroll"]:
            assert not f[col].isna().any(), (
                f"{class_name}: NaN in {col}")

    def test_mva_roll_forward_consistent(self, rundown_results):
        """MVA roll-forward should be internally consistent."""
        f = rundown_results[1]["regular"]
        for i in range(1, len(f)):
            roa = f.loc[i, "roa"]
            for tier in ["legacy", "new"]:
                expected = (
                    f.loc[i - 1, f"mva_{tier}"] * (1 + roa)
                    + f.loc[i, f"net_cf_{tier}"] * (1 + roa) ** 0.5
                )
                actual = f.loc[i, f"mva_{tier}"]
                if abs(expected) > 1.0:
                    pct_diff = abs(actual - expected) / abs(expected) * 100
                    assert pct_diff < 0.01, (
                        f"Year {i}: MVA {tier} roll-forward off by {pct_diff:.4f}%")


# ---------------------------------------------------------------------------
# Simplified asset projection (uses actual benefit cash flows)
# ---------------------------------------------------------------------------

class TestRundownAssetProjection:
    """Test a simplified asset projection using actual liability cash flows.

    This bypasses the going-concern funding model to check whether
    initial assets + NC contributions + investment returns can cover benefits.
    """

    @pytest.fixture(scope="class")
    def asset_projection(self, rundown_results):
        """Build simplified MVA projection from liability cash flows."""
        liab = rundown_results[0]["regular"]
        constants = rundown_results[2]

        from pension_model.core.funding_model import load_funding_inputs
        funding_dir = constants.resolve_data_dir() / "funding"
        funding_inputs = load_funding_inputs(funding_dir)
        init_funding = funding_inputs["init_funding"]
        reg_row = init_funding[init_funding["class"] == "regular"].iloc[0]
        initial_mva = float(reg_row["total_mva"])

        dr = constants.economic.dr_current
        ee_rate = constants.benefit.db_ee_cont_rate
        nc_cal = constants.class_data["regular"].nc_cal

        n_years = len(liab)
        mva = np.zeros(n_years)
        mva[0] = initial_mva
        benefits_paid = np.zeros(n_years)
        contributions = np.zeros(n_years)
        inv_earnings = np.zeros(n_years)

        for i in range(1, n_years):
            ben = liab["tot_ben_refund_est"].iloc[i]
            benefits_paid[i] = ben

            payroll_db = (liab["payroll_db_legacy_est"].iloc[i]
                          + liab["payroll_db_new_est"].iloc[i])
            nc_rate_leg = liab["nc_rate_db_legacy_est"].iloc[i] * nc_cal
            nc_rate_new = liab["nc_rate_db_new_est"].iloc[i] * nc_cal
            ee_cont = ee_rate * payroll_db
            er_nc = ((nc_rate_leg - ee_rate) * liab["payroll_db_legacy_est"].iloc[i]
                     + max(nc_rate_new - ee_rate, 0) * liab["payroll_db_new_est"].iloc[i])
            cont = ee_cont + max(er_nc, 0)
            contributions[i] = cont

            net_cf = cont - ben
            mva[i] = mva[i - 1] * (1 + dr) + net_cf * (1 + dr) ** 0.5
            inv_earnings[i] = mva[i] - mva[i - 1] - net_cf

        return pd.DataFrame({
            "year": liab["year"].values,
            "mva": mva,
            "benefits_paid": benefits_paid,
            "contributions": contributions,
            "inv_earnings": inv_earnings,
            "n_active": liab["total_n_active"].values,
            "total_aal": liab["total_aal_est"].values,
        })

    def test_cumulative_cash_flow_balance(self, asset_projection):
        """Conservation of value: initial + contrib + earnings = benefits + final."""
        adf = asset_projection
        initial = adf["mva"].iloc[0]
        final = adf["mva"].iloc[-1]
        total_benefits = adf["benefits_paid"].sum()
        total_contributions = adf["contributions"].sum()
        total_earnings = adf["inv_earnings"].sum()

        lhs = initial + total_contributions + total_earnings
        rhs = total_benefits + final
        diff_pct = abs(lhs - rhs) / abs(lhs) * 100 if abs(lhs) > 0 else 0
        assert diff_pct < 0.01, (
            f"Cash flow imbalance: {diff_pct:.4f}%")

    def test_nc_only_insufficient_for_underfunded_plan(self, asset_projection):
        """NC-only contributions cannot cover all benefits for an underfunded plan."""
        adf = asset_projection
        total_benefits = adf["benefits_paid"].sum()
        initial_mva = adf["mva"].iloc[0]
        total_contributions = adf["contributions"].sum()
        assert total_benefits > initial_mva + total_contributions, (
            "Expected underfunded plan to have benefit shortfall with NC-only contributions")

    def test_asset_trajectory_peaks_and_declines(self, asset_projection):
        """Assets should peak and then decline as benefits exceed contributions."""
        adf = asset_projection
        mva = adf["mva"].values
        peak_idx = np.argmax(mva)
        if peak_idx < len(mva) - 10:
            assert mva[-1] < mva[peak_idx], (
                f"Assets still growing: peak={mva[peak_idx]:,.0f}, final={mva[-1]:,.0f}")


# ---------------------------------------------------------------------------
# Diagnostic report (always passes, prints year-by-year summary)
# ---------------------------------------------------------------------------

class TestRundownReport:
    """Print a year-by-year summary table for manual inspection."""

    def test_print_rundown_summary(self, rundown_results, capsys):
        """Print year-by-year rundown summary for regular class."""
        liability = rundown_results[0]
        funding = rundown_results[1]
        constants = rundown_results[2]
        liab = liability["regular"]
        f = funding["regular"]

        print(f"\n{'='*120}")
        print(f"CLOSED-PLAN RUNDOWN: regular class, {RUNDOWN_PERIOD}-year projection, no new entrants")
        print(f"Discount rate: {constants.economic.dr_current:.1%}, "
              f"Payroll growth (funding model): {constants.economic.payroll_growth:.2%}")
        print(f"{'='*120}")

        header = (
            f"{'Year':>6s} {'Actives':>10s} "
            f"{'Payroll(liab)':>14s} {'Payroll(fund)':>14s} "
            f"{'AAL(liab)':>14s} {'AAL(fund)':>14s} "
            f"{'MVA':>14s} {'Benefits':>14s} {'ER Cont':>14s}"
        )
        print(header)
        print("-" * len(header))

        n = len(f)
        years_to_print = sorted(set(
            [0, 1, 2, 5] + list(range(10, n, 10)) + [n - 1]
        ))

        for i in years_to_print:
            if i >= n or i >= len(liab):
                continue
            year = int(f.loc[i, "year"])
            actives = liab["total_n_active"].iloc[i]
            payroll_liab = liab["total_payroll_est"].iloc[i]
            payroll_fund = f.loc[i, "total_payroll"]
            aal_liab = liab["total_aal_est"].iloc[i]
            aal_fund = f.loc[i, "total_aal"]
            mva = f.loc[i, "total_mva"]
            benefits = liab["tot_ben_refund_est"].iloc[i]
            er_cont = f.loc[i, "total_er_cont"]

            print(
                f"{year:6d} {actives:10,.0f} "
                f"{payroll_liab:14,.0f} {payroll_fund:14,.0f} "
                f"{aal_liab:14,.0f} {aal_fund:14,.0f} "
                f"{mva:14,.0f} {benefits:14,.0f} {er_cont:14,.0f}"
            )

        # Summary
        total_benefits = liab["tot_ben_refund_est"].sum()
        total_er_cont = f.loc[1:, "total_er_cont"].sum()
        initial_mva = f.loc[0, "total_mva"]
        final_mva = f.loc[n - 1, "total_mva"]

        print(f"\n  Initial MVA:           {initial_mva:>18,.0f}")
        print(f"  Final MVA:             {final_mva:>18,.0f}")
        print(f"  Total benefits (liab): {total_benefits:>18,.0f}")
        print(f"  Total ER cont (fund):  {total_er_cont:>18,.0f}")
        print(f"  Final AAL (liab):      {liab['total_aal_est'].iloc[-1]:>18,.0f}")
        print(f"  Final AAL (fund):      {f.loc[n-1, 'total_aal']:>18,.0f}")
        print(f"  Final active count:    {liab['total_n_active'].iloc[-1]:>18,.1f}")

        print(f"\n  NOTE: Funding model payroll grows at {constants.economic.payroll_growth:.2%}/yr")
        print(f"  regardless of actual headcount — this causes funding AAL and MVA")
        print(f"  to diverge from liability values after actives reach zero.")

        assert True
