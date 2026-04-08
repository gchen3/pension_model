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
import math


def load_funding_inputs(funding_dir: Path) -> dict:
    """Load funding input data from ``data/<plan>/funding/``.

    Files:
      - ``init_funding.csv``  (required)
      - ``return_scenarios.csv`` (required)
      - ``amort_layers.csv`` (optional — FRS only)

    Also accepts the legacy ``baseline_outputs/`` layout where the files
    are named ``init_funding_data.csv`` and ``current_amort_layers.csv``.
    """
    # init_funding: try standard name first, fall back to legacy
    init_path = funding_dir / "init_funding.csv"
    if not init_path.exists():
        init_path = funding_dir / "init_funding_data.csv"
    init_funding = pd.read_csv(init_path)
    # Normalize column names (TRS Excel had ' AAL' with leading space)
    init_funding.columns = [c.strip() for c in init_funding.columns]

    result = {
        "init_funding": init_funding,
        "return_scenarios": pd.read_csv(funding_dir / "return_scenarios.csv"),
    }

    # Amort layers (FRS only)
    amort_path = funding_dir / "amort_layers.csv"
    if not amort_path.exists():
        amort_path = funding_dir / "current_amort_layers.csv"
    if amort_path.exists():
        result["amort_layers"] = pd.read_csv(amort_path)

    return result


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
        Dict mapping class_name -> funding DataFrame (also "drop" and aggregate).
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

    class_names = list(constants.classes)
    agg_name = constants.plan_name
    has_drop = constants.raw.get("funding", {}).get("has_drop", False)
    drop_ref_class = constants.raw.get("funding", {}).get("drop_reference_class", class_names[0])
    all_classes = class_names + (["drop"] if has_drop else [])

    # Return scenario setup — select which column of return_scenarios to use.
    # "assumption" (default) → assets earn dr_current each year.
    # "model" → assets earn model_return each year.
    # Other columns (e.g. "recession") use their pre-loaded values.
    return_scen_col = constants.raw.get("economic", {}).get("return_scen", "assumption")
    ret_scen = return_scenarios.copy()
    # Year 1 (start_year+1) keeps its CSV values (actual realized return).
    # Years after that use model_return / dr_current as the projected path.
    first_proj_year = r.start_year + 2  # year after the first projection year
    ret_scen.loc[ret_scen["year"] >= first_proj_year, "model"] = econ.model_return
    ret_scen.loc[ret_scen["year"] >= first_proj_year, "assumption"] = dr_current

    if fund_params.amo_method == "level $":
        amo_pay_growth = 0

    # Initialize funding tables
    funding = {}
    for cn in all_classes + [agg_name]:
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
    for cn in class_names:
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
    for cn in all_classes:
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
        frs = funding[agg_name]

        # --- 7 membership classes ---
        for cn in class_names:
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

        # --- DROP (only for plans with has_drop=true) ---
        if has_drop:
            drop = funding["drop"]
            reg = funding[drop_ref_class]
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
        for cn in all_classes:
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
            roa = roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current
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
        for cn in all_classes:
            f = funding[cn]
            if frs.loc[i, "ava_base_legacy"] != 0:
                f.loc[i, "alloc_inv_earnings_ava_legacy"] = frs.loc[i, "alloc_inv_earnings_ava_legacy"] * f.loc[i, "ava_base_legacy"] / frs.loc[i, "ava_base_legacy"]
            f.loc[i, "unadj_ava_legacy"] = f.loc[i - 1, "ava_legacy"] + f.loc[i, "net_cf_legacy"] + f.loc[i, "alloc_inv_earnings_ava_legacy"]

            if frs.loc[i, "ava_base_new"] != 0:
                f.loc[i, "alloc_inv_earnings_ava_new"] = frs.loc[i, "alloc_inv_earnings_ava_new"] * f.loc[i, "ava_base_new"] / frs.loc[i, "ava_base_new"]
            f.loc[i, "unadj_ava_new"] = f.loc[i - 1, "ava_new"] + f.loc[i, "net_cf_new"] + f.loc[i, "alloc_inv_earnings_ava_new"]
            funding[cn] = f

        # --- DROP reallocation (only for plans with has_drop=true) ---
        if has_drop:
            drop = funding["drop"]
            if frs.loc[i, "aal_legacy"] != 0:
                drop.loc[i, "net_reallocation_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "aal_legacy"] * frs.loc[i, "ava_legacy"] / frs.loc[i, "aal_legacy"]
            drop.loc[i, "ava_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "net_reallocation_legacy"]
            if frs.loc[i, "aal_new"] != 0:
                drop.loc[i, "net_reallocation_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "aal_new"] * frs.loc[i, "ava_new"] / frs.loc[i, "aal_new"]
            drop.loc[i, "ava_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "net_reallocation_new"]
            funding["drop"] = drop

            for cn in class_names:
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
        else:
            # No DROP: unadjusted AVA is final AVA
            for cn in class_names:
                f = funding[cn]
                f.loc[i, "ava_legacy"] = f.loc[i, "unadj_ava_legacy"]
                f.loc[i, "ava_new"] = f.loc[i, "unadj_ava_new"]
                funding[cn] = f

        # --- UAL, funded ratios ---
        for cn in all_classes:
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
        for cn in all_classes:
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

        funding[agg_name] = frs

    return funding


# ---------------------------------------------------------------------------
# TRS funding model
# ---------------------------------------------------------------------------

def _ava_gain_loss_smoothing(
    ava_prev, net_cf, mva, dr,
    defer_y1_prev, defer_y2_prev, defer_y3_prev, defer_y4_prev,
):
    """AVA gain/loss deferral smoothing (TRS method).

    Replicates R's TxTRS_funding_model.R lines 326-364.
    Returns dict with all intermediate and final values.
    """
    exp_inv_income = ava_prev * dr + net_cf * dr / 2
    exp_ava = ava_prev + net_cf + exp_inv_income
    asset_gain_loss = mva - exp_ava

    prev_defer_total = defer_y1_prev + defer_y2_prev + defer_y3_prev + defer_y4_prev
    remain_defer_boy = asset_gain_loss - prev_defer_total

    # Cascade offset logic: y4 → y3 → y2 → y1
    # Step 1: offset defer_y4
    if math.copysign(1, remain_defer_boy) == math.copysign(1, defer_y4_prev) or defer_y4_prev == 0:
        aft_offset_y4 = remain_defer_boy
    else:
        aft_offset_y4 = math.copysign(
            max(0, abs(remain_defer_boy) - abs(defer_y4_prev)),
            remain_defer_boy) if remain_defer_boy != 0 else 0.0
    if math.copysign(1, aft_offset_y4) == math.copysign(1, defer_y3_prev) or defer_y3_prev == 0:
        new_y4 = defer_y3_prev * 0.5
    else:
        new_y4 = math.copysign(
            max(0, abs(defer_y3_prev) - abs(aft_offset_y4)),
            defer_y3_prev) * 0.5 if defer_y3_prev != 0 else 0.0

    # Step 2: offset defer_y3
    if math.copysign(1, aft_offset_y4) == math.copysign(1, defer_y3_prev) or defer_y3_prev == 0:
        aft_offset_y3 = aft_offset_y4
    else:
        aft_offset_y3 = math.copysign(
            max(0, abs(aft_offset_y4) - abs(defer_y3_prev)),
            aft_offset_y4) if aft_offset_y4 != 0 else 0.0
    if math.copysign(1, aft_offset_y3) == math.copysign(1, defer_y2_prev) or defer_y2_prev == 0:
        new_y3 = defer_y2_prev * (2 / 3)
    else:
        new_y3 = math.copysign(
            max(0, abs(defer_y2_prev) - abs(aft_offset_y3)),
            defer_y2_prev) * (2 / 3) if defer_y2_prev != 0 else 0.0

    # Step 3: offset defer_y2
    if math.copysign(1, aft_offset_y3) == math.copysign(1, defer_y2_prev) or defer_y2_prev == 0:
        aft_offset_y2 = aft_offset_y3
    else:
        aft_offset_y2 = math.copysign(
            max(0, abs(aft_offset_y3) - abs(defer_y2_prev)),
            aft_offset_y3) if aft_offset_y3 != 0 else 0.0
    if math.copysign(1, aft_offset_y2) == math.copysign(1, defer_y1_prev) or defer_y1_prev == 0:
        new_y2 = defer_y1_prev * (3 / 4)
    else:
        new_y2 = math.copysign(
            max(0, abs(defer_y1_prev) - abs(aft_offset_y2)),
            defer_y1_prev) * (3 / 4) if defer_y1_prev != 0 else 0.0

    # Step 4: offset defer_y1
    if math.copysign(1, aft_offset_y2) == math.copysign(1, defer_y1_prev) or defer_y1_prev == 0:
        aft_offset_y1 = aft_offset_y2
    else:
        aft_offset_y1 = math.copysign(
            max(0, abs(aft_offset_y2) - abs(defer_y1_prev)),
            aft_offset_y2) if aft_offset_y2 != 0 else 0.0
    new_y1 = aft_offset_y1 * (4 / 5)

    remain_defer_eoy = new_y1 + new_y2 + new_y3 + new_y4
    ava = mva - remain_defer_eoy

    return {
        "exp_inv_income": exp_inv_income,
        "exp_ava": exp_ava,
        "asset_gain_loss": asset_gain_loss,
        "remain_defer_boy": remain_defer_boy,
        "aft_offset_defer_y4": aft_offset_y4,
        "defer_y4": new_y4,
        "aft_offset_defer_y3": aft_offset_y3,
        "defer_y3": new_y3,
        "aft_offset_defer_y2": aft_offset_y2,
        "defer_y2": new_y2,
        "aft_offset_defer_y1": aft_offset_y1,
        "defer_y1": new_y1,
        "remain_defer_eoy": remain_defer_eoy,
        "ava": ava,
    }


def _lookup_rate_schedule(schedule: list, year: int) -> float:
    """Look up a rate from a year-based schedule.

    Schedule is a list of {"from_year": Y, "rate": R} sorted ascending.
    Returns the rate for the latest entry where from_year <= year.
    """
    rate = schedule[0]["rate"]
    for entry in schedule:
        if year >= entry["from_year"]:
            rate = entry["rate"]
        else:
            break
    return rate


def compute_funding_trs(
    liability_result: pd.DataFrame,
    funding_inputs: dict,
    constants: PlanConfig,
) -> pd.DataFrame:
    """
    Run the TRS funding model.

    Replicates R's TxTRS_funding_model.R.

    Args:
        liability_result: Output of run_plan_pipeline for class "all".
        funding_inputs: Output of load_txtrs_funding_data().
        constants: TRS PlanConfig.

    Returns:
        DataFrame with 96 columns matching R's funding_fresh.csv.
    """
    econ = constants.economic
    fund = constants.funding
    r_cfg = constants.ranges

    dr_current = econ.dr_current
    dr_new = econ.dr_new
    payroll_growth = econ.payroll_growth
    inflation = econ.inflation

    amo_pay_growth = fund.amo_pay_growth
    amo_period_new = fund.amo_period_new
    funding_policy = fund.funding_policy

    amo_method = fund.amo_method if hasattr(fund, "amo_method") else "level_pct"
    if amo_method == "level $":
        amo_pay_growth = 0

    model_period = r_cfg.model_period
    start_year = r_cfg.start_year
    n_years = model_period + 1

    # Return scenario column selection (same logic as FRS)
    return_scen_col = constants.raw.get("economic", {}).get("return_scen", "assumption")

    # --- Load initial row ---
    init = funding_inputs["init_funding"].iloc[0]
    ret_scen = funding_inputs["return_scenarios"].copy()

    # Set "model" and "assumption" columns in return_scenarios
    ret_scen["model"] = econ.model_return
    ret_scen["assumption"] = dr_current

    # --- Funding config parameters ---
    raw = constants.raw if hasattr(constants, "raw") else {}
    funding_raw = raw.get("funding", {})

    public_edu_payroll_pct = funding_raw.get("public_edu_payroll_percent", 0.588)
    extra_er_stat_cont = funding_raw.get("extra_er_stat_cont", 0.0)
    amo_period_current = funding_raw.get("amo_period_current", 30)

    # Statutory rate schedules (time-varying contribution rates)
    stat_rates = funding_raw.get("statutory_rates", {})
    ee_schedule = stat_rates.get("ee_rate_schedule",
                                 [{"from_year": 0, "rate": constants.benefit.db_ee_cont_rate}])
    er_base_schedule = stat_rates.get("er_base_rate_schedule",
                                      [{"from_year": 0, "rate": constants.benefit.db_ee_cont_rate}])
    surcharge_cfg = stat_rates.get("surcharge", {})
    surcharge_ramp_rate = surcharge_cfg.get("ramp_rate", 0.0)
    surcharge_ramp_end = surcharge_cfg.get("ramp_end_year", 0)
    extra_er_start_year = stat_rates.get("extra_er_start_year", 9999)

    # nc_cal: authoritative source is calibration.json (class_data), with
    # funding_raw as legacy fallback
    nc_cal = 1.0
    if hasattr(constants, "class_data") and "all" in constants.class_data:
        cd = constants.class_data["all"]
        if hasattr(cd, "nc_cal") and cd.nc_cal != 1.0:
            nc_cal = cd.nc_cal
    if nc_cal == 1.0:
        nc_cal = funding_raw.get("nc_cal", 1.0)

    # --- Initialize DataFrame from initial funding row ---
    # Normalize column names to lowercase with total_ prefix for aggregates
    _init_rename = {
        "AAL": "total_aal", "AAL_legacy": "aal_legacy", "AAL_new": "aal_new",
        "AVA": "total_ava", "AVA_legacy": "ava_legacy", "AVA_new": "ava_new",
        "MVA": "total_mva", "MVA_legacy": "mva_legacy", "MVA_new": "mva_new",
        "UAL_AVA": "total_ual_ava", "UAL_AVA_legacy": "ual_ava_legacy",
        "UAL_AVA_new": "ual_ava_new",
        "UAL_MVA": "total_ual_mva", "UAL_MVA_legacy": "ual_mva_legacy",
        "UAL_MVA_new": "ual_mva_new", "UAL_MVA_real": "total_ual_mva_real",
        "FR_AVA": "fr_ava", "FR_MVA": "fr_mva",
        "ROA": "roa", "DR": "dr_legacy",
        "exp_AVA_legacy": "exp_ava_legacy", "exp_AVA_new": "exp_ava_new",
        "payroll": "total_payroll",
        "er_cont": "total_er_cont", "er_cont_rate": "total_er_cont_rate",
        "er_cont_real": "total_er_cont_real",
    }
    init = init.rename(index={k: v for k, v in _init_rename.items() if k in init.index})
    # Lowercase any remaining mixed-case index entries
    init = init.rename(index={k: k.lower() for k in init.index if k != k.lower()})

    cols = list(init.index)
    f = pd.DataFrame(0.0, index=range(n_years), columns=cols)
    f["year"] = range(start_year, start_year + n_years)
    for col in cols:
        if col != "year":
            val = init.get(col, 0)
            f.loc[0, col] = float(val if pd.notna(val) else 0)

    # Rename 'fy' to 'year' if present
    if "fy" in f.columns and "year" not in cols:
        f["year"] = range(start_year, start_year + n_years)
    elif "fy" in f.columns:
        f.loc[:, "fy"] = f["year"]

    liab = liability_result

    # --- Calibration: payroll ratios and NC rates from liability pipeline ---
    # R uses lag(ratio) — ratio from previous year applied to next year's payroll
    pay_est = liab["total_payroll_est"].values
    for ratio_col, num_col in [
        ("payroll_db_legacy_ratio", "payroll_db_legacy_est"),
        ("payroll_db_new_ratio", "payroll_db_new_est"),
    ]:
        if ratio_col not in f.columns:
            f[ratio_col] = 0.0
        num = liab[num_col].values if num_col in liab.columns else np.zeros(n_years)
        ratios = np.divide(num, pay_est, out=np.zeros_like(pay_est), where=pay_est != 0)
        # lag by 1
        f.loc[1:, ratio_col] = ratios[:-1]

    # CB payroll ratio
    if "payroll_cb_new_ratio" not in f.columns:
        f["payroll_cb_new_ratio"] = 0.0
    if "payroll_cb_new_est" in liab.columns:
        cb_ratios = np.divide(liab["payroll_cb_new_est"].values, pay_est,
                              out=np.zeros_like(pay_est), where=pay_est != 0)
        f.loc[1:, "payroll_cb_new_ratio"] = cb_ratios[:-1]

    # NC rate calibration (with nc_cal and lag)
    nc_leg = liab["nc_rate_db_legacy_est"].values * nc_cal
    nc_new_db = liab.get("nc_rate_db_new_est", pd.Series(np.zeros(n_years))).values * nc_cal
    nc_new_cb = liab.get("nc_rate_cb_new_est", pd.Series(np.zeros(n_years))).values
    f.loc[1:, "nc_rate_db_legacy"] = nc_leg[:-1]
    f.loc[1:, "nc_rate_db_new"] = nc_new_db[:-1]
    f.loc[1:, "nc_rate_cb_new"] = nc_new_cb[:-1]

    # AAL initialization
    if "aal_legacy_est" in liab.columns:
        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
    elif "aal_legacy_est" in liab.columns:
        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
    f.loc[0, "total_aal"] = f.loc[0, "aal_legacy"] + f.loc[0, "aal_new"]
    f.loc[0, "ual_ava_legacy"] = f.loc[0, "aal_legacy"] - f.loc[0, "ava_legacy"]
    f.loc[0, "total_ual_ava"] = f.loc[0, "total_aal"] - f.loc[0, "total_ava"]

    # --- Amortization period tables ---
    amo_seq_current = list(range(amo_period_current, 0, -1))
    amo_seq_new = list(range(amo_period_new, 0, -1))
    n_amo = max(len(amo_seq_current), len(amo_seq_new))

    # Current-hire period table: row 0 = existing countdown, rows 1+ = new layers
    amo_per_current = np.zeros((n_years, n_amo))
    amo_per_current[0, :len(amo_seq_current)] = amo_seq_current
    for row in range(1, n_years):
        amo_per_current[row, :len(amo_seq_new)] = amo_seq_new
    # Shift onto diagonals
    for j in range(1, n_amo):
        for row in range(n_years):
            if row - j >= 0:
                amo_per_current[row, j] = amo_per_current[row - j, j] if row == j else amo_per_current[row, j]
    # Rebuild with proper diagonal shift (match R's lag logic)
    amo_per_current_diag = np.zeros((n_years, n_amo))
    amo_per_current_diag[0, :len(amo_seq_current)] = amo_seq_current
    for row in range(1, n_years):
        amo_per_current_diag[row, 0] = amo_seq_new[0] if len(amo_seq_new) > 0 else 0
    for j in range(1, n_amo):
        for row in range(j, n_years):
            prev = amo_per_current_diag[row - 1, j - 1]
            amo_per_current_diag[row, j] = max(prev - 1, 0) if prev > 0 else 0

    amo_per_new = np.zeros((n_years, n_amo))
    for j in range(n_amo):
        for row in range(j + 1, n_years):
            idx = row - j - 1
            amo_per_new[row, j] = max(amo_seq_new[0] - idx, 0) if idx < amo_seq_new[0] else 0
    # Simpler: diagonal from row j+1, col j, counting down
    amo_per_new = np.zeros((n_years, n_amo))
    for j in range(n_amo):
        for row in range(j + 1, n_years):
            amo_per_new[row, j] = max(amo_period_new - (row - j - 1), 0)

    # Debt and payment tables
    debt_current = np.zeros((n_years, n_amo + 1))
    pay_current = np.zeros((n_years, n_amo))
    debt_new = np.zeros((n_years, n_amo + 1))
    pay_new = np.zeros((n_years, n_amo))

    # Initialize first debt layer and payment
    debt_current[0, 0] = f.loc[0, "total_ual_ava"]
    if amo_per_current_diag[0, 0] > 0:
        pay_current[0, 0] = _get_pmt(
            dr_current, amo_pay_growth, int(amo_per_current_diag[0, 0]),
            debt_current[0, 0], t=0.5)

    # --- Main year loop ---
    for i in range(1, n_years):
        year = start_year + i

        # Payroll projection
        f.loc[i, "total_payroll"] = f.loc[i - 1, "total_payroll"] * (1 + payroll_growth)
        f.loc[i, "payroll_db_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_legacy_ratio"]
        f.loc[i, "payroll_db_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_new_ratio"]
        f.loc[i, "payroll_cb_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_cb_new_ratio"]

        # Benefit payments from liability pipeline
        f.loc[i, "ben_payment_legacy"] = (
            liab["retire_ben_db_legacy_est"].iloc[i]
            + liab["retire_ben_current_est"].iloc[i]
            + liab["retire_ben_term_est"].iloc[i])
        f.loc[i, "refund_legacy"] = liab["refund_db_legacy_est"].iloc[i]
        f.loc[i, "ben_payment_new"] = (
            liab.get("retire_ben_db_new_est", pd.Series(np.zeros(n_years))).iloc[i]
            + liab.get("retire_ben_cb_new_est", pd.Series(np.zeros(n_years))).iloc[i])
        f.loc[i, "refund_new"] = (
            liab.get("refund_db_new_est", pd.Series(np.zeros(n_years))).iloc[i]
            + liab.get("refund_cb_new_est", pd.Series(np.zeros(n_years))).iloc[i])

        # Normal cost
        f.loc[i, "nc_legacy"] = f.loc[i, "nc_rate_db_legacy"] * f.loc[i, "payroll_db_legacy"]
        payroll_new_total = f.loc[i, "payroll_db_new"] + f.loc[i, "payroll_cb_new"]
        f.loc[i, "nc_new"] = (f.loc[i, "nc_rate_db_new"] * f.loc[i, "payroll_db_new"]
                               + f.loc[i, "nc_rate_cb_new"] * f.loc[i, "payroll_cb_new"])
        f.loc[i, "nc_rate"] = ((f.loc[i, "nc_legacy"] + f.loc[i, "nc_new"])
                                / f.loc[i, "total_payroll"]) if f.loc[i, "total_payroll"] > 0 else 0

        # Liability gain/loss
        f.loc[i, "liability_gain_loss_legacy"] = (
            liab["liability_gain_loss_legacy_est"].iloc[i]
            if "liability_gain_loss_legacy_est" in liab.columns else 0)
        f.loc[i, "liability_gain_loss_new"] = (
            liab["liability_gain_loss_new_est"].iloc[i]
            if "liability_gain_loss_new_est" in liab.columns else 0)
        f.loc[i, "liability_gain_loss"] = f.loc[i, "liability_gain_loss_legacy"] + f.loc[i, "liability_gain_loss_new"]

        # AAL roll-forward
        f.loc[i, "aal_legacy"] = (
            f.loc[i - 1, "aal_legacy"] * (1 + dr_current)
            + (f.loc[i, "nc_legacy"] - f.loc[i, "ben_payment_legacy"] - f.loc[i, "refund_legacy"]) * (1 + dr_current) ** 0.5
            + f.loc[i, "liability_gain_loss_legacy"])
        f.loc[i, "aal_new"] = (
            f.loc[i - 1, "aal_new"] * (1 + dr_new)
            + (f.loc[i, "nc_new"] - f.loc[i, "ben_payment_new"] - f.loc[i, "refund_new"]) * (1 + dr_new) ** 0.5
            + f.loc[i, "liability_gain_loss_new"])
        f.loc[i, "total_aal"] = f.loc[i, "aal_legacy"] + f.loc[i, "aal_new"]

        # NC rates
        f.loc[i, "nc_rate_legacy"] = (f.loc[i, "nc_legacy"] / f.loc[i, "payroll_db_legacy"]
                                       if f.loc[i, "payroll_db_legacy"] > 0 else 0)
        f.loc[i, "nc_rate_new"] = (f.loc[i, "nc_new"] / payroll_new_total
                                    if payroll_new_total > 0 else 0)

        # Employee contribution rates (from config schedule)
        ee_rate = _lookup_rate_schedule(ee_schedule, year)
        f.loc[i, "ee_nc_rate_legacy"] = ee_rate
        f.loc[i, "ee_nc_rate_new"] = ee_rate

        # Employer NC rates
        f.loc[i, "er_nc_rate_legacy"] = f.loc[i, "nc_rate_legacy"] - ee_rate
        f.loc[i, "er_nc_rate_new"] = f.loc[i, "nc_rate_new"] - ee_rate

        # Statutory employer rates (from config schedule)
        f.loc[i, "er_stat_base_rate"] = _lookup_rate_schedule(er_base_schedule, year)

        if year <= surcharge_ramp_end:
            f.loc[i, "public_edu_surcharge_rate"] = f.loc[i - 1, "public_edu_surcharge_rate"] + surcharge_ramp_rate
        else:
            f.loc[i, "public_edu_surcharge_rate"] = f.loc[i - 1, "public_edu_surcharge_rate"]

        f.loc[i, "er_stat_extra_rate"] = extra_er_stat_cont if year >= extra_er_start_year else 0

        f.loc[i, "er_stat_eff_rate"] = (f.loc[i, "er_stat_base_rate"]
                                          + f.loc[i, "public_edu_surcharge_rate"] * public_edu_payroll_pct
                                          + f.loc[i, "er_stat_extra_rate"])

        # Amortization rates
        if funding_policy == "statutory":
            f.loc[i, "amo_rate_legacy"] = f.loc[i, "er_stat_eff_rate"] - f.loc[i, "er_nc_rate_legacy"]
            f.loc[i, "amo_rate_new"] = f.loc[i, "er_stat_eff_rate"] - f.loc[i, "er_nc_rate_new"]
        else:
            f.loc[i, "amo_rate_legacy"] = (pay_current[i - 1].sum() / f.loc[i, "total_payroll"]
                                            if f.loc[i, "total_payroll"] > 0 else 0)
            f.loc[i, "amo_rate_new"] = (pay_new[i - 1].sum() / payroll_new_total
                                         if payroll_new_total > 0 else 0)

        # Admin expense rate
        f.loc[i, "admin_exp_rate"] = f.loc[i - 1, "admin_exp_rate"]

        # Employee contribution amounts
        f.loc[i, "ee_nc_cont_legacy"] = f.loc[i, "ee_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
        f.loc[i, "ee_nc_cont_new"] = f.loc[i, "ee_nc_rate_new"] * payroll_new_total

        # Admin expenses
        f.loc[i, "admin_exp_legacy"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_legacy"]
        f.loc[i, "admin_exp_new"] = f.loc[i, "admin_exp_rate"] * payroll_new_total

        # Employer contribution amounts
        f.loc[i, "er_nc_cont_legacy"] = (f.loc[i, "er_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
                                          + f.loc[i, "admin_exp_legacy"])
        f.loc[i, "er_nc_cont_new"] = (f.loc[i, "er_nc_rate_new"] * payroll_new_total
                                       + f.loc[i, "admin_exp_new"])

        # Employer amortization amounts
        if funding_policy == "statutory":
            f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
        else:
            f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "total_payroll"]
        f.loc[i, "er_amo_cont_new"] = f.loc[i, "amo_rate_new"] * payroll_new_total

        # Return on assets
        roa_row = ret_scen[ret_scen["year"] == year]
        roa = roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current
        f.loc[i, "roa"] = roa

        # Cash flows and solvency contribution
        cf_legacy = (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
                     + f.loc[i, "er_amo_cont_legacy"] - f.loc[i, "ben_payment_legacy"]
                     - f.loc[i, "refund_legacy"] - f.loc[i, "admin_exp_legacy"])
        cf_new = (f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
                  + f.loc[i, "er_amo_cont_new"] - f.loc[i, "ben_payment_new"]
                  - f.loc[i, "refund_new"] - f.loc[i, "admin_exp_new"])
        cf_total = cf_legacy + cf_new

        f.loc[i, "solv_cont"] = max(
            -(f.loc[i - 1, "total_mva"] * (1 + roa) + cf_total * (1 + roa) ** 0.5) / (1 + roa) ** 0.5, 0)
        if f.loc[i, "total_aal"] > 0:
            f.loc[i, "solv_cont_legacy"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_legacy"] / f.loc[i, "total_aal"]
            f.loc[i, "solv_cont_new"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_new"] / f.loc[i, "total_aal"]

        f.loc[i, "net_cf_legacy"] = cf_legacy + f.loc[i, "solv_cont_legacy"]
        f.loc[i, "net_cf_new"] = cf_new + f.loc[i, "solv_cont_new"]

        # MVA projection
        f.loc[i, "mva_legacy"] = (f.loc[i - 1, "mva_legacy"] * (1 + roa)
                                   + f.loc[i, "net_cf_legacy"] * (1 + roa) ** 0.5)
        f.loc[i, "mva_new"] = (f.loc[i - 1, "mva_new"] * (1 + roa)
                                + f.loc[i, "net_cf_new"] * (1 + roa) ** 0.5)
        f.loc[i, "total_mva"] = f.loc[i, "mva_legacy"] + f.loc[i, "mva_new"]

        # AVA gain/loss deferral smoothing — legacy
        ava_leg = _ava_gain_loss_smoothing(
            f.loc[i - 1, "ava_legacy"], f.loc[i, "net_cf_legacy"], f.loc[i, "mva_legacy"],
            dr_current,
            f.loc[i - 1, "defer_y1_legacy"], f.loc[i - 1, "defer_y2_legacy"],
            f.loc[i - 1, "defer_y3_legacy"], f.loc[i - 1, "defer_y4_legacy"])
        for k, v in ava_leg.items():
            col = f"{'exp_inv_income' if k == 'exp_inv_income' else k}_legacy" if k != "ava" else "ava_legacy"
            if k == "exp_inv_income":
                f.loc[i, "exp_inv_income_legacy"] = v
            elif k == "exp_ava":
                f.loc[i, "exp_ava_legacy"] = v
            elif k == "ava":
                f.loc[i, "ava_legacy"] = v
            else:
                f.loc[i, f"{k}_legacy"] = v

        # AVA gain/loss deferral smoothing — new
        ava_new = _ava_gain_loss_smoothing(
            f.loc[i - 1, "ava_new"], f.loc[i, "net_cf_new"], f.loc[i, "mva_new"],
            dr_new,
            f.loc[i - 1, "defer_y1_new"], f.loc[i - 1, "defer_y2_new"],
            f.loc[i - 1, "defer_y3_new"], f.loc[i - 1, "defer_y4_new"])
        for k, v in ava_new.items():
            if k == "exp_inv_income":
                f.loc[i, "exp_inv_income_new"] = v
            elif k == "exp_ava":
                f.loc[i, "exp_ava_new"] = v
            elif k == "ava":
                f.loc[i, "ava_new"] = v
            else:
                f.loc[i, f"{k}_new"] = v

        f.loc[i, "total_ava"] = f.loc[i, "ava_legacy"] + f.loc[i, "ava_new"]

        # UAL and funded ratios
        f.loc[i, "ual_ava_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "ava_legacy"]
        f.loc[i, "ual_ava_new"] = f.loc[i, "aal_new"] - f.loc[i, "ava_new"]
        f.loc[i, "total_ual_ava"] = f.loc[i, "ual_ava_legacy"] + f.loc[i, "ual_ava_new"]

        f.loc[i, "ual_mva_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "mva_legacy"]
        f.loc[i, "ual_mva_new"] = f.loc[i, "aal_new"] - f.loc[i, "mva_new"]
        f.loc[i, "total_ual_mva"] = f.loc[i, "ual_mva_legacy"] + f.loc[i, "ual_mva_new"]

        f.loc[i, "fr_ava"] = f.loc[i, "total_ava"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0
        f.loc[i, "fr_mva"] = f.loc[i, "total_mva"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0

        # Contribution totals
        f.loc[i, "total_er_cont"] = (f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
                                      + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"]
                                      + f.loc[i, "solv_cont"])
        f.loc[i, "total_er_cont_rate"] = f.loc[i, "total_er_cont"] / f.loc[i, "total_payroll"] if f.loc[i, "total_payroll"] > 0 else 0
        f.loc[i, "tot_cont_rate"] = (
            (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
             + f.loc[i, "er_amo_cont_legacy"]
             + f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
             + f.loc[i, "er_amo_cont_new"] + f.loc[i, "solv_cont"])
            / f.loc[i, "total_payroll"]) if f.loc[i, "total_payroll"] > 0 else 0

        # Real cost metrics
        f.loc[i, "total_er_cont_real"] = f.loc[i, "total_er_cont"] / (1 + inflation) ** (year - start_year)
        if i == 1:
            f.loc[i, "cum_er_cont_real"] = f.loc[i, "total_er_cont_real"]
        else:
            f.loc[i, "cum_er_cont_real"] = f.loc[i - 1, "cum_er_cont_real"] + f.loc[i, "total_er_cont_real"]
        f.loc[i, "total_ual_mva_real"] = f.loc[i, "total_ual_mva"] / (1 + inflation) ** (year - start_year)
        f.loc[i, "all_in_cost_real"] = f.loc[i, "cum_er_cont_real"] + f.loc[i, "total_ual_mva_real"]

        # Amortization layer updates — current hires (legacy)
        for j in range(1, n_amo + 1):
            if j <= n_amo:
                debt_current[i, j] = (debt_current[i - 1, j - 1] * (1 + dr_current)
                                      - pay_current[i - 1, j - 1] * (1 + dr_current) ** 0.5)
        debt_current[i, 0] = f.loc[i, "ual_ava_legacy"] - debt_current[i, 1:n_amo + 1].sum()
        for j in range(n_amo):
            per = amo_per_current_diag[i, j]
            if per > 0 and abs(debt_current[i, j]) > 1e-6:
                pay_current[i, j] = _get_pmt(dr_current, amo_pay_growth, max(int(per), 1),
                                              debt_current[i, j], t=0.5)
            else:
                pay_current[i, j] = 0

        # Amortization layer updates — new hires
        for j in range(1, n_amo + 1):
            if j <= n_amo:
                debt_new[i, j] = (debt_new[i - 1, j - 1] * (1 + dr_new)
                                  - pay_new[i - 1, j - 1] * (1 + dr_new) ** 0.5)
        debt_new[i, 0] = f.loc[i, "ual_ava_new"] - debt_new[i, 1:n_amo + 1].sum()
        for j in range(n_amo):
            per = amo_per_new[i, j]
            if per > 0 and abs(debt_new[i, j]) > 1e-6:
                pay_new[i, j] = _get_pmt(dr_new, amo_pay_growth, max(int(per), 1),
                                          debt_new[i, j], t=0.5)
            else:
                pay_new[i, j] = 0

    return f
