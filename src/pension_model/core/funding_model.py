"""
Funding model.

Replicates R's Florida FRS funding model.R.
Year-by-year projection of:
  - Payroll, benefit payments, normal cost
  - AAL roll-forward with liability gain/loss
  - MVA projection with investment returns
  - AVA smoothing (5-year, bounded 80%-120% of MVA)
  - UAAL amortization (layered, level % of payroll)
  - Employer contributions (NC + amortization + admin + DC + solvency)
  - Funded ratios (AVA and MVA basis)

Requires: liability pipeline output + initial funding data + amort layers
"""

import numpy as np
import pandas as pd
from pathlib import Path

from pension_model.plan_config import PlanConfig, load_frs_config
from pension_model.core.pipeline import _get_pmt


def load_funding_inputs(baseline_dir: Path) -> dict:
    """Load all funding-specific input data."""
    return {
        "init_funding": pd.read_csv(baseline_dir / "init_funding_data.csv"),
        "amort_layers": pd.read_csv(baseline_dir / "current_amort_layers.csv"),
        "return_scenarios": pd.read_csv(baseline_dir / "return_scenarios.csv"),
    }


def _get_init_row(init_funding: pd.DataFrame, class_name: str) -> pd.Series:
    """Get initial funding values for a class (with class name normalization)."""
    lookup = class_name.replace("_", " ")
    row = init_funding[init_funding["class"] == lookup]
    if len(row) == 0:
        row = init_funding[init_funding["class"] == class_name]
    return row.iloc[0]


def build_amort_period_tables(
    amort_layers: pd.DataFrame, class_name: str,
    amo_period_new: int, funding_lag: int, model_period: int,
) -> tuple:
    """
    Build amortization period matrices for current and future hires.

    Returns (current_periods, future_periods, init_balances, max_col).
    Each period matrix: rows = years, columns = amortization layers.
    Periods count down diagonally.
    """
    lookup = class_name.replace("_", " ")
    class_layers = amort_layers[amort_layers["class"] == lookup].copy()
    # R converts "n/a" to amo_period_new, then groups by period
    class_layers["amo_period"] = pd.to_numeric(
        class_layers["amo_period"].replace("n/a", str(amo_period_new))
    ).fillna(amo_period_new)  # Also handle numeric NaN from CSV loading
    # R groups by (class, amo_period) and sums balances
    class_layers = (class_layers.groupby("amo_period", as_index=False)
                    .agg({"amo_balance": "sum"})
                    .sort_values("amo_period", ascending=False))

    current_periods_init = class_layers["amo_period"].dropna().values
    # max_col must accommodate all existing layers AND future layers
    max_col = max(
        len(current_periods_init),
        int(current_periods_init.max()) if len(current_periods_init) > 0 else 0,
        amo_period_new + funding_lag,
    )

    n_rows = model_period + 1

    # Current hire periods
    current = np.zeros((n_rows, max_col))
    current[0, :len(current_periods_init)] = current_periods_init
    future_period = amo_period_new + funding_lag
    for row in range(1, n_rows):
        current[row, 0] = future_period

    for i in range(1, n_rows):
        for j in range(1, max_col):
            current[i, j] = max(current[i - 1, j - 1] - 1, 0)

    # Future hire periods
    future = np.zeros((n_rows, max_col))
    for row in range(n_rows):
        future[row, 0] = future_period

    for i in range(1, n_rows):
        for j in range(1, max_col):
            future[i, j] = max(future[i - 1, j - 1] - 1, 0)

    init_balances = class_layers["amo_balance"].dropna().values
    return current, future, init_balances, max_col


def compute_funding(
    liability_results: dict,
    funding_inputs: dict,
    constants=None,
) -> dict:
    """
    Run the full funding model for all classes.

    Args:
        liability_results: Dict mapping class_name -> liability pipeline output DataFrame.
        funding_inputs: Output of load_funding_inputs().
        constants: Model constants.

    Returns:
        Dict mapping class_name -> funding DataFrame (also "drop" and "frs").
    """
    if constants is None:
        constants = load_frs_config()

    econ = constants.economic
    fund_params = constants.funding
    r = constants.ranges
    init_funding = funding_inputs["init_funding"]
    amort_layers = funding_inputs["amort_layers"]
    return_scenarios = funding_inputs["return_scenarios"]

    dr_current = econ.dr_current
    dr_new = econ.dr_new
    dr_old = econ.dr_old
    payroll_growth = econ.payroll_growth
    amo_pay_growth = fund_params.amo_pay_growth
    amo_period_new = fund_params.amo_period_new
    funding_lag = fund_params.funding_lag
    db_ee_cont_rate = constants.benefit.db_ee_cont_rate
    inflation = econ.inflation

    model_period = r.model_period
    start_year = r.start_year
    n_years = model_period + 1

    class_names_7 = ["regular", "special", "admin", "eso", "eco", "judges", "senior_management"]
    class_names_no_frs = class_names_7 + ["drop"]

    # Return scenario setup
    ret_scen = return_scenarios.copy()
    ret_scen.loc[ret_scen["year"] == 2023, ["model", "assumption"]] = [econ.model_return, dr_current]
    ret_scen.loc[ret_scen["year"] > 2023, "model"] = econ.model_return
    ret_scen.loc[ret_scen["year"] > 2023, "assumption"] = dr_current

    if fund_params.amo_method == "level $":
        amo_pay_growth = 0

    # Initialize funding tables
    funding = {}
    for cn in class_names_no_frs + ["frs"]:
        init_row = _get_init_row(init_funding, cn)
        cols = [c for c in init_funding.columns if c != "class"]
        df = pd.DataFrame(0.0, index=range(n_years), columns=cols)
        df["year"] = range(start_year, start_year + n_years)
        for col in cols:
            if col != "year":
                val = init_row.get(col, 0)
                df.loc[0, col] = float(val if pd.notna(val) else 0)
        funding[cn] = df

    # Calibration
    for cn in class_names_7:
        f = funding[cn]
        liab = liability_results[cn]

        for ratio_col, num_col, denom_col in [
            ("payroll_db_legacy_ratio", "payroll_db_legacy_est", "total_payroll_est"),
            ("payroll_db_new_ratio", "payroll_db_new_est", "total_payroll_est"),
            ("payroll_dc_legacy_ratio", "payroll_dc_legacy_est", "total_payroll_est"),
            ("payroll_dc_new_ratio", "payroll_dc_new_est", "total_payroll_est"),
        ]:
            if ratio_col not in f.columns:
                f[ratio_col] = 0.0
            denom = liab[denom_col].values
            ratios = np.divide(liab[num_col].values, denom,
                               out=np.zeros_like(denom), where=denom != 0)
            f.loc[1:, ratio_col] = ratios[:-1]

        if "nc_rate_db_legacy" not in f.columns:
            f["nc_rate_db_legacy"] = 0.0
            f["nc_rate_db_new"] = 0.0

        # NC rate calibration: R multiplies liability NC rates by nc_cal
        # nc_cal = val_norm_cost / model_norm_cost (additional adjustment beyond cal_factor=0.9)
        nc_cal = constants.class_data[cn].nc_cal
        nc_legacy = liab["nc_rate_db_legacy_est"].values * nc_cal
        nc_new = liab.get("nc_rate_db_new_est", pd.Series(np.zeros(n_years))).values * nc_cal
        # Lag by 1 year (R uses lag to align with funding mechanism)
        f.loc[1:, "nc_rate_db_legacy"] = nc_legacy[:-1]
        f.loc[1:, "nc_rate_db_new"] = nc_new[:-1]

        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
        f.loc[0, "total_aal"] = liab["total_aal_est"].iloc[0]
        f.loc[0, "ual_ava_legacy"] = f.loc[0, "aal_legacy"] - f.loc[0, "ava_legacy"]
        f.loc[0, "total_ual_ava"] = f.loc[0, "total_aal"] - f.loc[0, "total_ava"]

        funding[cn] = f

    # Amortization tables
    amo_tables = {}
    for cn in class_names_no_frs:
        cur_per, fut_per, init_bal, max_col = build_amort_period_tables(
            amort_layers, cn, amo_period_new, funding_lag, model_period)

        cur_debt = np.zeros((n_years, max_col + 1))
        if len(init_bal) > 0:
            cur_debt[0, :len(init_bal)] = init_bal
        fut_debt = np.zeros((n_years, max_col + 1))

        cur_pay = np.zeros((n_years, max_col))
        for j in range(max_col):
            if cur_per[0, j] > 0 and abs(cur_debt[0, j]) > 1e-6:
                cur_pay[0, j] = _get_pmt(dr_old, amo_pay_growth, int(cur_per[0, j]),
                                         cur_debt[0, j], t=0.5)
        if funding_lag > 0:
            cur_pay[0, :funding_lag] = 0

        fut_pay = np.zeros((n_years, max_col))

        amo_tables[cn] = {
            "cur_per": cur_per, "fut_per": fut_per,
            "cur_debt": cur_debt, "fut_debt": fut_debt,
            "cur_pay": cur_pay, "fut_pay": fut_pay,
            "max_col": max_col,
        }

    # ========== Main year loop ==========
    for i in range(1, n_years):
        frs = funding["frs"]

        # --- 7 membership classes ---
        for cn in class_names_7:
            f = funding[cn]
            liab = liability_results[cn]

            f.loc[i, "total_payroll"] = f.loc[i - 1, "total_payroll"] * (1 + payroll_growth)
            f.loc[i, "payroll_db_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_legacy_ratio"]
            f.loc[i, "payroll_db_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_new_ratio"]
            f.loc[i, "payroll_dc_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_legacy_ratio"]
            f.loc[i, "payroll_dc_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_new_ratio"]

            for pc in ["total_payroll", "payroll_db_legacy", "payroll_db_new", "payroll_dc_legacy", "payroll_dc_new"]:
                frs.loc[i, pc] += f.loc[i, pc]

            f.loc[i, "ben_payment_legacy"] = (liab["retire_ben_db_legacy_est"].iloc[i]
                + liab["retire_ben_current_est"].iloc[i] + liab["retire_ben_term_est"].iloc[i])
            f.loc[i, "refund_legacy"] = liab["refund_db_legacy_est"].iloc[i]
            f.loc[i, "ben_payment_new"] = liab["retire_ben_db_new_est"].iloc[i]
            f.loc[i, "refund_new"] = liab["refund_db_new_est"].iloc[i]
            f.loc[i, "total_ben_payment"] = f.loc[i, "ben_payment_legacy"] + f.loc[i, "ben_payment_new"]
            f.loc[i, "total_refund"] = f.loc[i, "refund_legacy"] + f.loc[i, "refund_new"]

            for bc in ["ben_payment_legacy", "refund_legacy", "ben_payment_new", "refund_new",
                        "total_ben_payment", "total_refund"]:
                frs.loc[i, bc] += f.loc[i, bc]

            f.loc[i, "nc_legacy"] = f.loc[i, "nc_rate_db_legacy"] * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "nc_new"] = f.loc[i, "nc_rate_db_new"] * f.loc[i, "payroll_db_new"]
            pdb = f.loc[i, "payroll_db_legacy"] + f.loc[i, "payroll_db_new"]
            f.loc[i, "total_nc_rate"] = (f.loc[i, "nc_legacy"] + f.loc[i, "nc_new"]) / pdb if pdb > 0 else 0
            frs.loc[i, "nc_legacy"] += f.loc[i, "nc_legacy"]
            frs.loc[i, "nc_new"] += f.loc[i, "nc_new"]

            # Under baseline (experience = assumptions), gain/loss = 0
            f.loc[i, "liability_gain_loss_legacy"] = liab["liability_gain_loss_legacy_est"].iloc[i] if "liability_gain_loss_legacy_est" in liab.columns else 0
            f.loc[i, "liability_gain_loss_new"] = liab["liability_gain_loss_new_est"].iloc[i] if "liability_gain_loss_new_est" in liab.columns else 0

            f.loc[i, "aal_legacy"] = (f.loc[i - 1, "aal_legacy"] * (1 + dr_current)
                + (f.loc[i, "nc_legacy"] - f.loc[i, "ben_payment_legacy"] - f.loc[i, "refund_legacy"]) * (1 + dr_current) ** 0.5
                + f.loc[i, "liability_gain_loss_legacy"])
            f.loc[i, "aal_new"] = (f.loc[i - 1, "aal_new"] * (1 + dr_new)
                + (f.loc[i, "nc_new"] - f.loc[i, "ben_payment_new"] - f.loc[i, "refund_new"]) * (1 + dr_new) ** 0.5
                + f.loc[i, "liability_gain_loss_new"])
            f.loc[i, "total_aal"] = f.loc[i, "aal_legacy"] + f.loc[i, "aal_new"]

            frs.loc[i, "aal_legacy"] += f.loc[i, "aal_legacy"]
            frs.loc[i, "aal_new"] += f.loc[i, "aal_new"]
            frs.loc[i, "total_aal"] += f.loc[i, "total_aal"]

            funding[cn] = f

        frs_pdb = frs.loc[i, "payroll_db_legacy"] + frs.loc[i, "payroll_db_new"]
        frs.loc[i, "total_nc_rate"] = (frs.loc[i, "nc_legacy"] + frs.loc[i, "nc_new"]) / frs_pdb if frs_pdb > 0 else 0

        # --- DROP ---
        drop = funding["drop"]
        reg = funding["regular"]
        drop.loc[i, "total_payroll"] = drop.loc[i - 1, "total_payroll"] * (1 + payroll_growth)
        drop.loc[i, "payroll_db_legacy"] = drop.loc[i, "total_payroll"] * (reg.loc[i, "payroll_db_legacy_ratio"] + reg.loc[i, "payroll_dc_legacy_ratio"])
        drop.loc[i, "payroll_db_new"] = drop.loc[i, "total_payroll"] * (reg.loc[i, "payroll_db_new_ratio"] + reg.loc[i, "payroll_dc_new_ratio"])

        if reg.loc[i - 1, "total_ben_payment"] > 0:
            drop.loc[i, "total_ben_payment"] = drop.loc[i - 1, "total_ben_payment"] * reg.loc[i, "total_ben_payment"] / reg.loc[i - 1, "total_ben_payment"]
        if reg.loc[i - 1, "total_refund"] > 0:
            drop.loc[i, "total_refund"] = drop.loc[i - 1, "total_refund"] * reg.loc[i, "total_refund"] / reg.loc[i - 1, "total_refund"]

        if reg.loc[i, "total_ben_payment"] > 0:
            drop.loc[i, "ben_payment_legacy"] = drop.loc[i, "total_ben_payment"] * reg.loc[i, "ben_payment_legacy"] / reg.loc[i, "total_ben_payment"]
            drop.loc[i, "ben_payment_new"] = drop.loc[i, "total_ben_payment"] * reg.loc[i, "ben_payment_new"] / reg.loc[i, "total_ben_payment"]
        if reg.loc[i, "total_refund"] > 0:
            drop.loc[i, "refund_legacy"] = drop.loc[i, "total_refund"] * reg.loc[i, "refund_legacy"] / reg.loc[i, "total_refund"]
            drop.loc[i, "refund_new"] = drop.loc[i, "total_refund"] * reg.loc[i, "refund_new"] / reg.loc[i, "total_refund"]

        drop.loc[i, "nc_rate_db_legacy"] = frs.loc[i, "nc_legacy"] / frs.loc[i, "payroll_db_legacy"] if frs.loc[i, "payroll_db_legacy"] > 0 else 0
        drop.loc[i, "nc_rate_db_new"] = frs.loc[i, "nc_new"] / frs.loc[i, "payroll_db_new"] if frs.loc[i, "payroll_db_new"] > 0 else 0
        drop.loc[i, "nc_legacy"] = drop.loc[i, "nc_rate_db_legacy"] * drop.loc[i, "payroll_db_legacy"]
        drop.loc[i, "nc_new"] = drop.loc[i, "nc_rate_db_new"] * drop.loc[i, "payroll_db_new"]

        drop.loc[i, "aal_legacy"] = (drop.loc[i - 1, "aal_legacy"] * (1 + dr_current)
            + (drop.loc[i, "nc_legacy"] - drop.loc[i, "ben_payment_legacy"] - drop.loc[i, "refund_legacy"]) * (1 + dr_current) ** 0.5)
        drop.loc[i, "aal_new"] = (drop.loc[i - 1, "aal_new"] * (1 + dr_new)
            + (drop.loc[i, "nc_new"] - drop.loc[i, "ben_payment_new"] - drop.loc[i, "refund_new"]) * (1 + dr_new) ** 0.5)
        drop.loc[i, "total_aal"] = drop.loc[i, "aal_legacy"] + drop.loc[i, "aal_new"]
        funding["drop"] = drop

        for pc in ["total_payroll", "payroll_db_legacy", "payroll_db_new"]:
            frs.loc[i, pc] += drop.loc[i, pc]
        for bc in ["ben_payment_legacy", "refund_legacy", "ben_payment_new", "refund_new",
                    "total_ben_payment", "total_refund"]:
            frs.loc[i, bc] += drop.loc[i, bc]
        frs.loc[i, "nc_legacy"] += drop.loc[i, "nc_legacy"]
        frs.loc[i, "nc_new"] += drop.loc[i, "nc_new"]
        frs_pdb2 = frs.loc[i, "payroll_db_legacy"] + frs.loc[i, "payroll_db_new"]
        frs.loc[i, "total_nc_rate"] = (frs.loc[i, "nc_legacy"] + frs.loc[i, "nc_new"]) / frs_pdb2 if frs_pdb2 > 0 else 0
        frs.loc[i, "nc_rate_db_legacy"] = frs.loc[i, "nc_legacy"] / frs.loc[i, "payroll_db_legacy"] if frs.loc[i, "payroll_db_legacy"] > 0 else 0
        frs.loc[i, "nc_rate_db_new"] = frs.loc[i, "nc_new"] / frs.loc[i, "payroll_db_new"] if frs.loc[i, "payroll_db_new"] > 0 else 0
        frs.loc[i, "aal_legacy"] += drop.loc[i, "aal_legacy"]
        frs.loc[i, "aal_new"] += drop.loc[i, "aal_new"]
        frs.loc[i, "total_aal"] += drop.loc[i, "total_aal"]

        # --- Contributions, MVA, AVA ---
        for cn in class_names_no_frs:
            f = funding[cn]
            amo = amo_tables[cn]

            f.loc[i, "nc_rate_legacy"] = f.loc[i, "nc_legacy"] / f.loc[i, "payroll_db_legacy"] if f.loc[i, "payroll_db_legacy"] > 0 else 0
            f.loc[i, "nc_rate_new"] = f.loc[i, "nc_new"] / f.loc[i, "payroll_db_new"] if f.loc[i, "payroll_db_new"] > 0 else 0
            f.loc[i, "ee_nc_rate_legacy"] = db_ee_cont_rate
            f.loc[i, "ee_nc_rate_new"] = db_ee_cont_rate
            f.loc[i, "er_nc_rate_legacy"] = f.loc[i, "nc_rate_legacy"] - db_ee_cont_rate
            f.loc[i, "er_nc_rate_new"] = f.loc[i, "nc_rate_new"] - db_ee_cont_rate
            f.loc[i, "amo_rate_legacy"] = amo["cur_pay"][i - 1].sum() / f.loc[i, "payroll_db_legacy"] if f.loc[i, "payroll_db_legacy"] > 0 else 0
            f.loc[i, "amo_rate_new"] = amo["fut_pay"][i - 1].sum() / f.loc[i, "payroll_db_new"] if f.loc[i, "payroll_db_new"] > 0 else 0

            if cn == "drop":
                f.loc[i, "er_dc_rate_legacy"] = 0
                f.loc[i, "er_dc_rate_new"] = 0
            else:
                dc_rate = constants.class_data[cn].er_dc_cont_rate
                f.loc[i, "er_dc_rate_legacy"] = dc_rate
                f.loc[i, "er_dc_rate_new"] = dc_rate

            f.loc[i, "admin_exp_rate"] = f.loc[i - 1, "admin_exp_rate"]
            f.loc[i, "ee_nc_cont_legacy"] = db_ee_cont_rate * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "ee_nc_cont_new"] = db_ee_cont_rate * f.loc[i, "payroll_db_new"]
            frs.loc[i, "ee_nc_cont_legacy"] += f.loc[i, "ee_nc_cont_legacy"]
            frs.loc[i, "ee_nc_cont_new"] += f.loc[i, "ee_nc_cont_new"]

            f.loc[i, "admin_exp_legacy"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "admin_exp_new"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_new"]
            frs.loc[i, "admin_exp_legacy"] += f.loc[i, "admin_exp_legacy"]
            frs.loc[i, "admin_exp_new"] += f.loc[i, "admin_exp_new"]

            f.loc[i, "er_nc_cont_legacy"] = f.loc[i, "er_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"] + f.loc[i, "admin_exp_legacy"]
            f.loc[i, "er_nc_cont_new"] = f.loc[i, "er_nc_rate_new"] * f.loc[i, "payroll_db_new"] + f.loc[i, "admin_exp_new"]
            f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "er_amo_cont_new"] = f.loc[i, "amo_rate_new"] * f.loc[i, "payroll_db_new"]
            f.loc[i, "total_er_db_cont"] = (f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
                                             + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"])
            frs.loc[i, "er_nc_cont_legacy"] += f.loc[i, "er_nc_cont_legacy"]
            frs.loc[i, "er_nc_cont_new"] += f.loc[i, "er_nc_cont_new"]
            frs.loc[i, "er_amo_cont_legacy"] += f.loc[i, "er_amo_cont_legacy"]
            frs.loc[i, "er_amo_cont_new"] += f.loc[i, "er_amo_cont_new"]
            frs.loc[i, "total_er_db_cont"] += f.loc[i, "total_er_db_cont"]

            f.loc[i, "er_dc_cont_legacy"] = f.loc[i, "er_dc_rate_legacy"] * f.loc[i, "payroll_dc_legacy"]
            f.loc[i, "er_dc_cont_new"] = f.loc[i, "er_dc_rate_new"] * f.loc[i, "payroll_dc_new"]
            f.loc[i, "total_er_dc_cont"] = f.loc[i, "er_dc_cont_legacy"] + f.loc[i, "er_dc_cont_new"]
            frs.loc[i, "er_dc_cont_legacy"] += f.loc[i, "er_dc_cont_legacy"]
            frs.loc[i, "er_dc_cont_new"] += f.loc[i, "er_dc_cont_new"]
            frs.loc[i, "total_er_dc_cont"] += f.loc[i, "total_er_dc_cont"]

            year = start_year + i
            roa_row = ret_scen[ret_scen["year"] == year]
            roa = roa_row["assumption"].iloc[0] if len(roa_row) > 0 else dr_current
            f.loc[i, "roa"] = roa
            frs.loc[i, "roa"] = roa

            cf_leg = (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
                      + f.loc[i, "er_amo_cont_legacy"] - f.loc[i, "ben_payment_legacy"]
                      - f.loc[i, "refund_legacy"] - f.loc[i, "admin_exp_legacy"])
            cf_new = (f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
                      + f.loc[i, "er_amo_cont_new"] - f.loc[i, "ben_payment_new"]
                      - f.loc[i, "refund_new"] - f.loc[i, "admin_exp_new"])

            f.loc[i, "total_solv_cont"] = max(
                -(f.loc[i - 1, "total_mva"] * (1 + roa) + (cf_leg + cf_new) * (1 + roa) ** 0.5) / (1 + roa) ** 0.5, 0)
            if f.loc[i, "total_aal"] > 0:
                f.loc[i, "solv_cont_legacy"] = f.loc[i, "total_solv_cont"] * f.loc[i, "aal_legacy"] / f.loc[i, "total_aal"]
                f.loc[i, "solv_cont_new"] = f.loc[i, "total_solv_cont"] * f.loc[i, "aal_new"] / f.loc[i, "total_aal"]

            f.loc[i, "net_cf_legacy"] = cf_leg + f.loc[i, "solv_cont_legacy"]
            f.loc[i, "net_cf_new"] = cf_new + f.loc[i, "solv_cont_new"]
            frs.loc[i, "net_cf_legacy"] += f.loc[i, "net_cf_legacy"]
            frs.loc[i, "net_cf_new"] += f.loc[i, "net_cf_new"]

            f.loc[i, "mva_legacy"] = f.loc[i - 1, "mva_legacy"] * (1 + roa) + f.loc[i, "net_cf_legacy"] * (1 + roa) ** 0.5
            f.loc[i, "mva_new"] = f.loc[i - 1, "mva_new"] * (1 + roa) + f.loc[i, "net_cf_new"] * (1 + roa) ** 0.5
            f.loc[i, "total_mva"] = f.loc[i, "mva_legacy"] + f.loc[i, "mva_new"]
            frs.loc[i, "mva_legacy"] += f.loc[i, "mva_legacy"]
            frs.loc[i, "mva_new"] += f.loc[i, "mva_new"]
            frs.loc[i, "total_mva"] += f.loc[i, "total_mva"]

            f.loc[i, "ava_base_legacy"] = f.loc[i - 1, "ava_legacy"] + f.loc[i, "net_cf_legacy"] / 2
            f.loc[i, "ava_base_new"] = f.loc[i - 1, "ava_new"] + f.loc[i, "net_cf_new"] / 2

            funding[cn] = f

        # --- AVA smoothing at FRS level ---
        frs.loc[i, "exp_inv_earnings_ava_legacy"] = frs.loc[i - 1, "ava_legacy"] * dr_current + frs.loc[i, "net_cf_legacy"] * dr_current / 2
        frs.loc[i, "exp_ava_legacy"] = frs.loc[i - 1, "ava_legacy"] + frs.loc[i, "net_cf_legacy"] + frs.loc[i, "exp_inv_earnings_ava_legacy"]
        frs.loc[i, "ava_legacy"] = max(min(
            frs.loc[i, "exp_ava_legacy"] + (frs.loc[i, "mva_legacy"] - frs.loc[i, "exp_ava_legacy"]) * 0.2,
            frs.loc[i, "mva_legacy"] * 1.2), frs.loc[i, "mva_legacy"] * 0.8)
        frs.loc[i, "alloc_inv_earnings_ava_legacy"] = frs.loc[i, "ava_legacy"] - frs.loc[i - 1, "ava_legacy"] - frs.loc[i, "net_cf_legacy"]
        frs.loc[i, "ava_base_legacy"] = frs.loc[i - 1, "ava_legacy"] + frs.loc[i, "net_cf_legacy"] / 2

        frs.loc[i, "exp_inv_earnings_ava_new"] = frs.loc[i - 1, "ava_new"] * dr_new + frs.loc[i, "net_cf_new"] * dr_new / 2
        frs.loc[i, "exp_ava_new"] = frs.loc[i - 1, "ava_new"] + frs.loc[i, "net_cf_new"] + frs.loc[i, "exp_inv_earnings_ava_new"]
        frs.loc[i, "ava_new"] = max(min(
            frs.loc[i, "exp_ava_new"] + (frs.loc[i, "mva_new"] - frs.loc[i, "exp_ava_new"]) * 0.2,
            frs.loc[i, "mva_new"] * 1.2), frs.loc[i, "mva_new"] * 0.8)
        frs.loc[i, "alloc_inv_earnings_ava_new"] = frs.loc[i, "ava_new"] - frs.loc[i - 1, "ava_new"] - frs.loc[i, "net_cf_new"]
        frs.loc[i, "ava_base_new"] = frs.loc[i - 1, "ava_new"] + frs.loc[i, "net_cf_new"] / 2

        # --- Allocate AVA earnings to classes ---
        for cn in class_names_no_frs:
            f = funding[cn]
            if frs.loc[i, "ava_base_legacy"] != 0:
                f.loc[i, "alloc_inv_earnings_ava_legacy"] = frs.loc[i, "alloc_inv_earnings_ava_legacy"] * f.loc[i, "ava_base_legacy"] / frs.loc[i, "ava_base_legacy"]
            f.loc[i, "unadj_ava_legacy"] = f.loc[i - 1, "ava_legacy"] + f.loc[i, "net_cf_legacy"] + f.loc[i, "alloc_inv_earnings_ava_legacy"]

            if frs.loc[i, "ava_base_new"] != 0:
                f.loc[i, "alloc_inv_earnings_ava_new"] = frs.loc[i, "alloc_inv_earnings_ava_new"] * f.loc[i, "ava_base_new"] / frs.loc[i, "ava_base_new"]
            f.loc[i, "unadj_ava_new"] = f.loc[i - 1, "ava_new"] + f.loc[i, "net_cf_new"] + f.loc[i, "alloc_inv_earnings_ava_new"]
            funding[cn] = f

        # --- DROP reallocation ---
        drop = funding["drop"]
        if frs.loc[i, "aal_legacy"] != 0:
            drop.loc[i, "net_reallocation_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "aal_legacy"] * frs.loc[i, "ava_legacy"] / frs.loc[i, "aal_legacy"]
        drop.loc[i, "ava_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "net_reallocation_legacy"]
        if frs.loc[i, "aal_new"] != 0:
            drop.loc[i, "net_reallocation_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "aal_new"] * frs.loc[i, "ava_new"] / frs.loc[i, "aal_new"]
        drop.loc[i, "ava_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "net_reallocation_new"]
        funding["drop"] = drop

        for cn in class_names_7:
            f = funding[cn]
            frs_ex_drop_leg = frs.loc[i, "aal_legacy"] - drop.loc[i, "aal_legacy"]
            prop_leg = f.loc[i, "aal_legacy"] / frs_ex_drop_leg if frs_ex_drop_leg != 0 else 0
            f.loc[i, "net_reallocation_legacy"] = prop_leg * drop.loc[i, "net_reallocation_legacy"]
            f.loc[i, "ava_legacy"] = f.loc[i, "unadj_ava_legacy"] + f.loc[i, "net_reallocation_legacy"]

            frs_ex_drop_new = frs.loc[i, "aal_new"] - drop.loc[i, "aal_new"]
            prop_new = f.loc[i, "aal_new"] / frs_ex_drop_new if frs_ex_drop_new != 0 else 0
            f.loc[i, "net_reallocation_new"] = prop_new * drop.loc[i, "net_reallocation_new"]
            f.loc[i, "ava_new"] = f.loc[i, "unadj_ava_new"] + f.loc[i, "net_reallocation_new"]
            funding[cn] = f

        # --- UAL, funded ratios ---
        for cn in class_names_no_frs:
            f = funding[cn]
            f.loc[i, "total_ava"] = f.loc[i, "ava_legacy"] + f.loc[i, "ava_new"]
            frs.loc[i, "total_ava"] += f.loc[i, "total_ava"]

            f.loc[i, "ual_ava_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "ava_legacy"]
            f.loc[i, "ual_ava_new"] = f.loc[i, "aal_new"] - f.loc[i, "ava_new"]
            f.loc[i, "total_ual_ava"] = f.loc[i, "ual_ava_legacy"] + f.loc[i, "ual_ava_new"]
            frs.loc[i, "ual_ava_legacy"] += f.loc[i, "ual_ava_legacy"]
            frs.loc[i, "ual_ava_new"] += f.loc[i, "ual_ava_new"]
            frs.loc[i, "total_ual_ava"] += f.loc[i, "total_ual_ava"]

            f.loc[i, "ual_mva_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "mva_legacy"]
            f.loc[i, "ual_mva_new"] = f.loc[i, "aal_new"] - f.loc[i, "mva_new"]
            f.loc[i, "total_ual_mva"] = f.loc[i, "ual_mva_legacy"] + f.loc[i, "ual_mva_new"]
            frs.loc[i, "ual_mva_legacy"] += f.loc[i, "ual_mva_legacy"]
            frs.loc[i, "ual_mva_new"] += f.loc[i, "ual_mva_new"]
            frs.loc[i, "total_ual_mva"] += f.loc[i, "total_ual_mva"]

            f.loc[i, "fr_mva"] = f.loc[i, "total_mva"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0
            f.loc[i, "fr_ava"] = f.loc[i, "total_ava"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0

            f.loc[i, "total_er_cont"] = f.loc[i, "total_er_db_cont"] + f.loc[i, "total_er_dc_cont"] + f.loc[i, "total_solv_cont"]
            frs.loc[i, "total_er_cont"] += f.loc[i, "total_er_cont"]
            f.loc[i, "total_er_cont_rate"] = f.loc[i, "total_er_cont"] / f.loc[i, "total_payroll"] if f.loc[i, "total_payroll"] > 0 else 0
            funding[cn] = f

        frs.loc[i, "fr_mva"] = frs.loc[i, "total_mva"] / frs.loc[i, "total_aal"] if frs.loc[i, "total_aal"] != 0 else 0
        frs.loc[i, "fr_ava"] = frs.loc[i, "total_ava"] / frs.loc[i, "total_aal"] if frs.loc[i, "total_aal"] != 0 else 0
        frs.loc[i, "total_er_cont_rate"] = frs.loc[i, "total_er_cont"] / frs.loc[i, "total_payroll"] if frs.loc[i, "total_payroll"] > 0 else 0

        # --- Amortization layers ---
        for cn in class_names_no_frs:
            f = funding[cn]
            amo = amo_tables[cn]
            mc = amo["max_col"]

            cd, cp, cper = amo["cur_debt"], amo["cur_pay"], amo["cur_per"]
            cd[i, 1:mc + 1] = cd[i - 1, :mc] * (1 + dr_current) - cp[i - 1, :mc] * (1 + dr_current) ** 0.5
            cd[i, 0] = f.loc[i, "ual_ava_legacy"] - cd[i, 1:mc + 1].sum()
            for j in range(mc):
                if cper[i, j] > 0 and abs(cd[i, j]) > 1e-6:
                    cp[i, j] = _get_pmt(dr_current, amo_pay_growth, int(cper[i, j]), cd[i, j], t=0.5)
                else:
                    cp[i, j] = 0

            fd, fp, fper = amo["fut_debt"], amo["fut_pay"], amo["fut_per"]
            fd[i, 1:mc + 1] = fd[i - 1, :mc] * (1 + dr_new) - fp[i - 1, :mc] * (1 + dr_new) ** 0.5
            fd[i, 0] = f.loc[i, "ual_ava_new"] - fd[i, 1:mc + 1].sum()
            for j in range(mc):
                if fper[i, j] > 0 and abs(fd[i, j]) > 1e-6:
                    fp[i, j] = _get_pmt(dr_new, amo_pay_growth, int(fper[i, j]), fd[i, j], t=0.5)
                else:
                    fp[i, j] = 0

        funding["frs"] = frs

    return funding
