"""
Internal consistency checks for the pension model.

These verify that mathematical/actuarial relationships hold within
the model output, independent of calibration or R baseline matching.
"""

import sys
from pathlib import Path
import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

BASELINE = Path(__file__).parent.parent.parent / "baseline_outputs"
CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]
CLASSES_PLUS_DROP = CLASSES + ["drop"]


@pytest.fixture(scope="module")
def model_results():
    """Run full pipeline once and return (liability, funding, constants)."""
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.core.funding_model import load_funding_inputs, compute_funding
    from pension_model.plan_config import load_frs_config

    constants = load_frs_config()
    liability = run_plan_pipeline(constants, BASELINE)
    funding_inputs = load_funding_inputs(BASELINE)
    funding = compute_funding(liability, funding_inputs, constants)
    return liability, funding, constants


# ---------------------------------------------------------------------------
# Liability pipeline: AAL composition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES)
def test_liability_aal_composition_legacy(class_name, model_results):
    """AAL legacy = active + term + retire + current_retire + current_term."""
    liab = model_results[0][class_name]
    computed = (
        liab["aal_active_db_legacy_est"]
        + liab["aal_term_db_legacy_est"]
        + liab["aal_retire_db_legacy_est"]
        + liab["aal_retire_current_est"]
        + liab["aal_term_current_est"]
    )
    np.testing.assert_allclose(liab["aal_legacy_est"].values, computed.values,
                               atol=1e-6, err_msg=f"{class_name}: legacy AAL composition")


@pytest.mark.parametrize("class_name", CLASSES)
def test_liability_aal_composition_new(class_name, model_results):
    """AAL new = active_new + term_new + retire_new."""
    liab = model_results[0][class_name]
    computed = (
        liab["aal_active_db_new_est"]
        + liab["aal_term_db_new_est"]
        + liab["aal_retire_db_new_est"]
    )
    np.testing.assert_allclose(liab["aal_new_est"].values, computed.values,
                               atol=1e-6, err_msg=f"{class_name}: new AAL composition")


@pytest.mark.parametrize("class_name", CLASSES)
def test_liability_total_aal(class_name, model_results):
    """total_aal = legacy + new."""
    liab = model_results[0][class_name]
    np.testing.assert_allclose(
        liab["total_aal_est"].values,
        (liab["aal_legacy_est"] + liab["aal_new_est"]).values,
        atol=1e-6, err_msg=f"{class_name}: total AAL = legacy + new")


@pytest.mark.parametrize("class_name", CLASSES)
def test_liability_active_aal_eq_pvfb_minus_pvfnc(class_name, model_results):
    """Active AAL = PVFB - PVFNC (entry age normal)."""
    liab = model_results[0][class_name]
    for tier in ["legacy", "new"]:
        computed = liab[f"pvfb_active_db_{tier}_est"] - liab[f"pvfnc_db_{tier}_est"]
        np.testing.assert_allclose(
            liab[f"aal_active_db_{tier}_est"].values, computed.values,
            atol=1e-6, err_msg=f"{class_name}: active AAL {tier} = PVFB - PVFNC")


@pytest.mark.parametrize("class_name", CLASSES)
def test_liability_benefit_outflow_composition(class_name, model_results):
    """Total benefit/refund outflow = sum of components."""
    liab = model_results[0][class_name]
    legacy = (
        liab["refund_db_legacy_est"]
        + liab["retire_ben_db_legacy_est"]
        + liab["retire_ben_current_est"]
        + liab["retire_ben_term_est"]
    )
    new = liab["refund_db_new_est"] + liab["retire_ben_db_new_est"]
    np.testing.assert_allclose(
        liab["tot_ben_refund_est"].values, (legacy + new).values,
        atol=1e-6, err_msg=f"{class_name}: total benefit outflow composition")


# ---------------------------------------------------------------------------
# Funding: algebraic identities (per class, per year)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES_PLUS_DROP)
def test_funding_total_aal_eq_legacy_plus_new(class_name, model_results):
    """total_aal = aal_legacy + aal_new."""
    f = model_results[1][class_name]
    np.testing.assert_allclose(
        f["total_aal"].values, (f["aal_legacy"] + f["aal_new"]).values,
        atol=1e-2, err_msg=f"{class_name}: funding total_aal = legacy + new")


@pytest.mark.parametrize("class_name", CLASSES_PLUS_DROP)
def test_funding_total_mva_eq_legacy_plus_new(class_name, model_results):
    """total_mva = mva_legacy + mva_new."""
    f = model_results[1][class_name]
    np.testing.assert_allclose(
        f["total_mva"].values, (f["mva_legacy"] + f["mva_new"]).values,
        atol=1e-2, err_msg=f"{class_name}: funding total_mva = legacy + new")


@pytest.mark.parametrize("class_name", CLASSES_PLUS_DROP)
def test_funding_ual_eq_aal_minus_ava(class_name, model_results):
    """UAL = AAL - AVA for each tier."""
    f = model_results[1][class_name]
    for tier in ["legacy", "new"]:
        np.testing.assert_allclose(
            f[f"ual_ava_{tier}"].values,
            (f[f"aal_{tier}"] - f[f"ava_{tier}"]).values,
            atol=1e-2, err_msg=f"{class_name}: UAL {tier} = AAL - AVA")
    np.testing.assert_allclose(
        f["total_ual_ava"].values,
        (f["total_aal"] - f["total_ava"]).values,
        atol=1e-2, err_msg=f"{class_name}: total UAL = total AAL - total AVA")


@pytest.mark.parametrize("class_name", CLASSES_PLUS_DROP)
def test_funding_funded_ratio(class_name, model_results):
    """Funded ratio = AVA / AAL."""
    f = model_results[1][class_name]
    mask = f["total_aal"].values > 1e-6
    expected = f["total_ava"].values[mask] / f["total_aal"].values[mask]
    np.testing.assert_allclose(
        f["fr_ava"].values[mask], expected,
        atol=1e-8, err_msg=f"{class_name}: funded ratio = AVA / AAL")


# ---------------------------------------------------------------------------
# Funding: FRS plan-wide = sum of classes + DROP
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col", [
    "total_aal", "total_mva", "total_payroll",
    "nc_legacy", "nc_new",
    "total_ben_payment", "total_refund",
])
def test_frs_is_sum_of_classes(col, model_results):
    """FRS plan-wide totals = sum across 7 classes + DROP (years 1+).

    Year 0 is seed data from the ACFR, not computed from class sums.
    """
    funding = model_results[1]
    frs = funding["frs"]
    class_sum = sum(funding[cn][col].values for cn in CLASSES_PLUS_DROP)
    # Skip year 0 (index 0) — seed data from ACFR, not computed
    np.testing.assert_allclose(
        frs[col].values[1:], class_sum[1:],
        atol=1e-2, err_msg=f"frs[{col}] != sum of classes")


# ---------------------------------------------------------------------------
# Funding: AAL roll-forward
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES)
def test_aal_roll_forward_legacy(class_name, model_results):
    """AAL(t) = AAL(t-1)*(1+dr) + (NC-ben-refund)*(1+dr)^0.5 + gain_loss."""
    funding = model_results[1]
    constants = model_results[2]
    f = funding[class_name]
    dr = constants.economic.dr_current

    for i in range(1, len(f)):
        expected = (
            f.loc[i - 1, "aal_legacy"] * (1 + dr)
            + (f.loc[i, "nc_legacy"] - f.loc[i, "ben_payment_legacy"]
               - f.loc[i, "refund_legacy"]) * (1 + dr) ** 0.5
            + f.loc[i, "liability_gain_loss_legacy"]
        )
        actual = f.loc[i, "aal_legacy"]
        if abs(expected) > 1e-6:
            pct_diff = abs(actual - expected) / abs(expected) * 100
            assert pct_diff < 0.01, (
                f"{class_name} year {i}: AAL legacy roll-forward off by {pct_diff:.4f}%")


@pytest.mark.parametrize("class_name", CLASSES)
def test_aal_roll_forward_new(class_name, model_results):
    """AAL new tier roll-forward."""
    funding = model_results[1]
    constants = model_results[2]
    f = funding[class_name]
    dr = constants.economic.dr_new

    for i in range(1, len(f)):
        expected = (
            f.loc[i - 1, "aal_new"] * (1 + dr)
            + (f.loc[i, "nc_new"] - f.loc[i, "ben_payment_new"]
               - f.loc[i, "refund_new"]) * (1 + dr) ** 0.5
            + f.loc[i, "liability_gain_loss_new"]
        )
        actual = f.loc[i, "aal_new"]
        if abs(expected) > 1e-6:
            pct_diff = abs(actual - expected) / abs(expected) * 100
            assert pct_diff < 0.01, (
                f"{class_name} year {i}: AAL new roll-forward off by {pct_diff:.4f}%")


# ---------------------------------------------------------------------------
# Funding: MVA roll-forward
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES_PLUS_DROP)
def test_mva_roll_forward(class_name, model_results):
    """MVA(t) = MVA(t-1)*(1+roa) + net_cf*(1+roa)^0.5."""
    f = model_results[1][class_name]

    for i in range(1, len(f)):
        roa = f.loc[i, "roa"]
        for tier in ["legacy", "new"]:
            expected = (
                f.loc[i - 1, f"mva_{tier}"] * (1 + roa)
                + f.loc[i, f"net_cf_{tier}"] * (1 + roa) ** 0.5
            )
            actual = f.loc[i, f"mva_{tier}"]
            if abs(expected) > 1e-6:
                pct_diff = abs(actual - expected) / abs(expected) * 100
                assert pct_diff < 0.01, (
                    f"{class_name} year {i}: MVA {tier} roll-forward off by {pct_diff:.4f}%")


# ---------------------------------------------------------------------------
# Funding: contribution components
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES_PLUS_DROP)
def test_er_contribution_composition(class_name, model_results):
    """Total ER contribution = DB cont + DC cont + solvency."""
    f = model_results[1][class_name]
    for i in range(1, len(f)):
        expected = (
            f.loc[i, "total_er_db_cont"]
            + f.loc[i, "total_er_dc_cont"]
            + f.loc[i, "total_solv_cont"]
        )
        np.testing.assert_allclose(
            f.loc[i, "total_er_cont"], expected, atol=1e-2,
            err_msg=f"{class_name} year {i}: ER cont = DB + DC + solvency")


# ---------------------------------------------------------------------------
# Funding: payroll ratio sanity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES)
def test_payroll_ratios_sum_to_one(class_name, model_results):
    """DB + DC payroll ratios should sum to ~1.0."""
    f = model_results[1][class_name]
    for i in range(1, len(f)):
        ratio_sum = (
            f.loc[i, "payroll_db_legacy_ratio"]
            + f.loc[i, "payroll_db_new_ratio"]
            + f.loc[i, "payroll_dc_legacy_ratio"]
            + f.loc[i, "payroll_dc_new_ratio"]
        )
        # Ratios should be close to 1.0 (may not be exact due to rounding)
        assert abs(ratio_sum - 1.0) < 0.02, (
            f"{class_name} year {i}: payroll ratios sum to {ratio_sum:.4f}, expected ~1.0")


# ---------------------------------------------------------------------------
# Funding: benefit payments are positive
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES)
def test_benefit_payments_positive(class_name, model_results):
    """Total benefit payments should be positive for years 1+."""
    f = model_results[1][class_name]
    for i in range(1, len(f)):
        assert f.loc[i, "total_ben_payment"] >= 0, (
            f"{class_name} year {i}: negative benefit payment {f.loc[i, 'total_ben_payment']}")


# ---------------------------------------------------------------------------
# Funding: payroll grows at expected rate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_name", CLASSES)
def test_payroll_growth_rate(class_name, model_results):
    """Total payroll should grow at the assumed payroll growth rate."""
    f = model_results[1][class_name]
    constants = model_results[2]
    g = constants.economic.payroll_growth

    for i in range(1, len(f)):
        if f.loc[i - 1, "total_payroll"] > 0:
            expected = f.loc[i - 1, "total_payroll"] * (1 + g)
            np.testing.assert_allclose(
                f.loc[i, "total_payroll"], expected, rtol=1e-10,
                err_msg=f"{class_name} year {i}: payroll growth")
