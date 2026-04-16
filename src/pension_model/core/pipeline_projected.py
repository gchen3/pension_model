"""Projected active, term, refund, and retiree liability helpers."""

import numpy as np
import pandas as pd

from pension_model.config_schema import PlanConfig


def _get_bt_columns(bt: str) -> dict:
    """Map benefit type to its column names in benefit_val_table."""
    if bt == "db":
        return {"pvfb": "pvfb_db_wealth_at_current_age", "pvfnc": "pvfnc_db", "nc": "indv_norm_cost"}
    if bt == "cb":
        return {"pvfb": "pvfb_cb_at_current_age", "pvfnc": "pvfnc_cb", "nc": "indv_norm_cost_cb"}
    return {"pvfb": None, "pvfnc": None, "nc": None}


def _allocate_members(wf, benefit_types, design_ratios, new_year, design_cutoff_year=2018):
    """Allocate workforce members to benefit type buckets (legacy/new)."""
    ey = wf["entry_year"]
    n = wf["n_active"]
    for bt in benefit_types:
        before, after, new = design_ratios[bt]
        wf[f"n_{bt}_legacy"] = np.where(
            ey < new_year, np.where(ey < design_cutoff_year, n * before, n * after), 0.0)
        wf[f"n_{bt}_new"] = np.where(ey < new_year, 0.0, n * new)
    return wf


def _get_design_ratios(constants: PlanConfig, class_name: str):
    """Get design ratios and benefit types from a PlanConfig."""
    return constants.get_design_ratios(class_name), list(constants.benefit_types)


def _allocate_term(wf, pop_col, design_ratios, benefit_types, new_year, design_cutoff_year=2018):
    """Allocate term/refund/retire workforce to benefit type buckets."""
    ey = wf["entry_year"]
    n = wf[pop_col]
    base = pop_col[2:] if pop_col.startswith("n_") else pop_col
    for bt in benefit_types:
        before, after, new = design_ratios[bt]
        wf[f"n_{base}_{bt}_legacy"] = np.where(
            ey < new_year, np.where(ey < design_cutoff_year, n * before, n * after), 0.0)
        wf[f"n_{base}_{bt}_new"] = np.where(ey < new_year, 0.0, n * new)
    return wf


def compute_active_liability(wf_active: pd.DataFrame, benefit_val: pd.DataFrame,
                             class_name: str, constants) -> pd.DataFrame:
    """Compute active member liability by year."""
    r = constants.ranges
    new_year = r.new_year
    design_cutoff = constants.plan_design_cutoff_year or new_year

    design_ratios = constants.get_design_ratios(class_name)
    benefit_types = list(constants.benefit_types)

    wf = wf_active[wf_active["year"] <= r.start_year + r.model_period].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])
    wf["yos"] = wf["age"] - wf["entry_age"]

    bvt_cols = ["entry_year", "entry_age", "yos", "salary"]
    for bt in benefit_types:
        cols = _get_bt_columns(bt)
        for c in cols.values():
            if c is not None and c in benefit_val.columns and c not in bvt_cols:
                bvt_cols.append(c)
    wf = wf.merge(
        benefit_val[bvt_cols].drop_duplicates(subset=["entry_year", "entry_age", "yos"]),
        on=["entry_year", "entry_age", "yos"],
        how="left",
    )
    wf = wf.fillna(0)
    wf = _allocate_members(wf, benefit_types, design_ratios, new_year, design_cutoff)
    salary = wf["salary"]
    wf["total_payroll_est"] = salary * wf["n_active"]
    wf["total_n_active"] = wf["n_active"]

    sum_cols = ["total_payroll_est", "total_n_active"]
    for bt in benefit_types:
        cols = _get_bt_columns(bt)
        for period in ["legacy", "new"]:
            n_col = f"n_{bt}_{period}"
            payroll_col = f"payroll_{bt}_{period}_est"
            wf[payroll_col] = salary * wf[n_col]
            sum_cols.append(payroll_col)

            if cols["pvfb"] is None or cols["pvfb"] not in wf.columns:
                continue
            pvfb_col = f"pvfb_active_{bt}_{period}_est"
            pvfnc_col = f"pvfnc_{bt}_{period}_est"
            nc_num_col = f"_nc_num_{bt}_{period}"
            wf[pvfb_col] = wf[cols["pvfb"]] * wf[n_col]
            wf[pvfnc_col] = wf[cols["pvfnc"]] * wf[n_col]
            wf[nc_num_col] = wf[cols["nc"]] * salary * wf[n_col]
            sum_cols.extend([pvfb_col, pvfnc_col, nc_num_col])

    result = wf.groupby("year", as_index=False)[sum_cols].sum()

    for bt in benefit_types:
        cols = _get_bt_columns(bt)
        if cols["nc"] is None or cols["nc"] not in wf.columns:
            continue

        nc_col = cols["nc"]
        for period in ["legacy", "new"]:
            pay_col = f"payroll_{bt}_{period}_est"
            if pay_col not in result.columns:
                continue
            payroll_arr = result[pay_col].values
            nc_num = result[f"_nc_num_{bt}_{period}"].values
            result[f"nc_rate_{bt}_{period}_est"] = np.divide(
                nc_num, payroll_arr, out=np.zeros_like(payroll_arr), where=payroll_arr != 0)

            pvfb_col = f"pvfb_active_{bt}_{period}_est"
            pvfnc_col = f"pvfnc_{bt}_{period}_est"
            if pvfb_col in result.columns and pvfnc_col in result.columns:
                result[f"aal_active_{bt}_{period}_est"] = result[pvfb_col] - result[pvfnc_col]
            result = result.drop(columns=[f"_nc_num_{bt}_{period}"])

    if "payroll_db_legacy_est" in result.columns:
        result["payroll_db_est"] = result["payroll_db_legacy_est"] + result.get("payroll_db_new_est", 0)

    return result


def compute_term_liability(wf_term: pd.DataFrame, benefit_val: pd.DataFrame,
                           term_discount_lookup: pd.DataFrame, class_name: str,
                           constants: PlanConfig) -> pd.DataFrame:
    """Compute projected terminated vested liability by year."""
    r = constants.ranges
    design_ratios, benefit_types = _get_design_ratios(constants, class_name)
    design_cutoff = constants.plan_design_cutoff_year or r.new_year

    wf = wf_term[(wf_term["year"] <= r.start_year + r.model_period) & (wf_term["n_term"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    bvt_key = benefit_val[["entry_year", "entry_age", "yos", "pvfb_db_at_term_age"]].copy()
    bvt_key["term_year"] = bvt_key["entry_year"] + bvt_key["yos"]
    bvt_key = bvt_key.drop_duplicates(subset=["entry_age", "entry_year", "term_year"])
    wf = wf.merge(bvt_key[["entry_age", "entry_year", "term_year", "pvfb_db_at_term_age"]],
                  on=["entry_age", "entry_year", "term_year"], how="left")

    wf = wf.merge(term_discount_lookup, left_on=["entry_age", "entry_year", "age", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"], how="left")

    wf["pvfb_db_term"] = wf["pvfb_db_at_term_age"] / wf["cum_mort_dr"]
    wf = _allocate_term(wf, "n_term", design_ratios, benefit_types, r.new_year, design_cutoff)
    sum_cols = []
    for bt in benefit_types:
        if bt == "dc":
            continue
        for period in ["legacy", "new"]:
            n_col = f"n_term_{bt}_{period}"
            if n_col in wf.columns:
                out_col = f"aal_term_{bt}_{period}_est"
                wf[out_col] = wf["pvfb_db_term"] * wf[n_col]
                sum_cols.append(out_col)

    if not sum_cols:
        return pd.DataFrame({"year": wf["year"].unique()})
    return wf.groupby("year", as_index=False)[sum_cols].sum()


def compute_refund_liability(wf_refund: pd.DataFrame, refund_lookup: pd.DataFrame,
                             class_name: str, constants: PlanConfig) -> pd.DataFrame:
    """Compute refund liability by year."""
    r = constants.ranges
    design_ratios, benefit_types = _get_design_ratios(constants, class_name)
    design_cutoff = constants.plan_design_cutoff_year or r.new_year

    wf = wf_refund[(wf_refund["year"] <= r.start_year + r.model_period) & (wf_refund["n_refund"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    has_cb_bal = "cb_balance" in refund_lookup.columns
    wf = wf.merge(refund_lookup, left_on=["entry_age", "entry_year", "age", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"], how="left")

    wf = _allocate_term(wf, "n_refund", design_ratios, benefit_types, r.new_year, design_cutoff)
    sum_cols = []
    for bt in benefit_types:
        if bt == "dc":
            continue
        val_col = "cb_balance" if bt == "cb" and has_cb_bal else "db_ee_balance"
        for period in ["legacy", "new"]:
            n_col = f"n_refund_{bt}_{period}"
            if n_col in wf.columns:
                out_col = f"refund_{bt}_{period}_est"
                wf[out_col] = wf[val_col] * wf[n_col]
                sum_cols.append(out_col)

    if not sum_cols:
        return pd.DataFrame({"year": wf["year"].unique()})
    return wf.groupby("year", as_index=False)[sum_cols].sum()


def compute_retire_liability(wf_retire: pd.DataFrame, retire_benefit_lookup: pd.DataFrame,
                             retire_annuity_lookup: pd.DataFrame, class_name: str,
                             constants: PlanConfig) -> pd.DataFrame:
    """Compute projected retiree liability by year."""
    r = constants.ranges
    design_ratios, benefit_types = _get_design_ratios(constants, class_name)
    design_cutoff = constants.plan_design_cutoff_year or r.new_year

    wf = wf_retire[wf_retire["year"] <= r.start_year + r.model_period].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    has_cb_ben = "cb_benefit" in retire_benefit_lookup.columns
    wf = wf.merge(retire_benefit_lookup, left_on=["entry_age", "entry_year", "retire_year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_year", "term_year"], how="left")

    wf = wf.merge(retire_annuity_lookup, left_on=["entry_age", "entry_year", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_year", "term_year"],
                  how="left", suffixes=("", "_af"))

    wf["db_benefit_final"] = wf["db_benefit"] * (1 + wf["cola"]) ** (wf["year"] - wf["retire_year"])
    wf["pvfb_db_retire"] = wf["db_benefit_final"] * (wf["ann_factor"] - 1)

    if has_cb_ben:
        wf["cb_benefit_final"] = wf["cb_benefit"] * (1 + wf["cola"]) ** (wf["year"] - wf["retire_year"])
        wf["pvfb_cb_retire"] = wf["cb_benefit_final"] * (wf["ann_factor"] - 1)

    wf = _allocate_term(wf, "n_retire", design_ratios, benefit_types, r.new_year, design_cutoff)
    sum_cols = []
    for bt in benefit_types:
        if bt == "dc":
            continue
        ben_col = "cb_benefit_final" if bt == "cb" and has_cb_ben else "db_benefit_final"
        pvfb_col = "pvfb_cb_retire" if bt == "cb" and has_cb_ben else "pvfb_db_retire"
        for period in ["legacy", "new"]:
            n_col = f"n_retire_{bt}_{period}"
            if n_col in wf.columns:
                ben_out = f"retire_ben_{bt}_{period}_est"
                aal_out = f"aal_retire_{bt}_{period}_est"
                wf[ben_out] = wf[ben_col] * wf[n_col]
                wf[aal_out] = wf[pvfb_col] * wf[n_col]
                sum_cols.extend([ben_out, aal_out])

    if not sum_cols:
        return pd.DataFrame({"year": wf["year"].unique()})
    return wf.groupby("year", as_index=False)[sum_cols].sum()
