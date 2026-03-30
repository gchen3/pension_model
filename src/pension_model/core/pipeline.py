"""
End-to-end pension model pipeline.

Flows from raw inputs through benefit table construction to liability output.
Each step is validated against R intermediate data.

Pipeline:
  1. Load raw inputs (salary, headcount, decrement tables, mortality, constants)
  2. Build salary_headcount_table → salary_benefit_table
  3. Build separation_rate_table
  4. Build ann_factor_table → benefit_table → final_benefit_table
  5. Build benefit_val_table (PVFB, PVFS, NC)
  6. Join with workforce projections → liability components
  7. Aggregate by year → total AAL
"""

from pathlib import Path
import numpy as np
import pandas as pd

from pension_model.core.model_constants import ModelConstants, frs_constants
from pension_model.core.tier_logic import get_tier, get_ben_mult, get_reduce_factor, get_sep_type
from pension_model.core.benefit_tables import (
    build_salary_headcount_table,
    build_entrant_profile,
    build_salary_benefit_table,
    build_separation_rate_table,
    build_ann_factor_table,
    build_benefit_table,
    build_final_benefit_table,
    build_benefit_val_table,
)


# R's class mapping for separation rates (R benefit model line 588)
SEP_CLASS_MAP = {
    "regular": "regular", "special": "special", "admin": "admin",
    "eco": "eco", "eso": "regular", "judges": "judges",
    "senior_management": "senior_management",
}


def load_raw_inputs(class_name: str, baseline_dir: Path) -> dict:
    """Load all raw input files for a single class."""
    dt = baseline_dir / "decrement_tables"
    sep_class = SEP_CLASS_MAP[class_name]

    return {
        "salary": pd.read_csv(baseline_dir / f"{class_name}_salary.csv"),
        "headcount": pd.read_csv(baseline_dir / f"{class_name}_headcount.csv"),
        "salary_growth": pd.read_csv(baseline_dir / "salary_growth_table.csv"),
        "mortality": pd.read_csv(baseline_dir / f"{class_name}_mortality_rates.csv"),
        "retiree_distribution": pd.read_csv(baseline_dir / "retiree_distribution.csv"),
        # Separation rate inputs (may use different class for ESO)
        "term_rate_avg": pd.read_csv(dt / f"{sep_class}_term_rate_avg.csv"),
        "normal_retire_tier1": pd.read_csv(dt / f"{sep_class}_normal_retire_rate_tier1.csv"),
        "normal_retire_tier2": pd.read_csv(dt / f"{sep_class}_normal_retire_rate_tier2.csv"),
        "early_retire_tier1": pd.read_csv(dt / f"{sep_class}_early_retire_rate_tier1.csv"),
        "early_retire_tier2": pd.read_csv(dt / f"{sep_class}_early_retire_rate_tier2.csv"),
        # Workforce projections from R (validated in Phase A)
        "wf_active": pd.read_csv(baseline_dir / f"{class_name}_wf_active.csv"),
        "wf_term": pd.read_csv(baseline_dir / f"{class_name}_wf_term.csv"),
        "wf_retire": pd.read_csv(baseline_dir / f"{class_name}_wf_retire.csv"),
        "wf_refund": pd.read_csv(baseline_dir / f"{class_name}_wf_refund.csv"),
        # Current retiree annuity factors
        "ann_factor_retire": pd.read_csv(baseline_dir / f"{class_name}_ann_factor_retire.csv"),
    }


def compute_adjustment_ratio(class_name: str, headcount: pd.DataFrame,
                             constants: ModelConstants, baseline_dir: Path) -> float:
    """Compute headcount adjustment ratio matching R model."""
    if class_name in ("eco", "eso", "judges"):
        combined_raw = sum(
            pd.read_csv(baseline_dir / f"{c}_headcount.csv").iloc[:, 1:].sum().sum()
            for c in ("eco", "eso", "judges")
        )
        return 2075 / combined_raw  # eco_eso_judges_total_active_member_
    return constants.class_data[class_name].total_active_member / headcount.iloc[:, 1:].sum().sum()


def build_benefit_tables(class_name: str, inputs: dict, constants: ModelConstants,
                         baseline_dir: Path) -> dict:
    """
    Build all benefit tables from raw inputs for a single class.

    Returns dict with: salary_headcount, entrant_profile, salary_benefit,
        separation_rate, ann_factor, benefit, final_benefit, benefit_val
    """
    adj_ratio = compute_adjustment_ratio(class_name, inputs["headcount"], constants, baseline_dir)
    sep_class = SEP_CLASS_MAP[class_name]

    # Step 1: Salary/headcount
    sh = build_salary_headcount_table(
        inputs["salary"], inputs["headcount"], inputs["salary_growth"],
        class_name, adj_ratio, constants.ranges.start_year,
    )
    ep = build_entrant_profile(sh)

    # For separation rates, use the sep_class's salary/headcount if different
    if sep_class != class_name:
        sep_sal = pd.read_csv(baseline_dir / f"{sep_class}_salary.csv")
        sep_hc = pd.read_csv(baseline_dir / f"{sep_class}_headcount.csv")
        sep_adj = compute_adjustment_ratio(sep_class, sep_hc, constants, baseline_dir)
        sep_sh = build_salary_headcount_table(
            sep_sal, sep_hc, inputs["salary_growth"],
            sep_class, sep_adj, constants.ranges.start_year,
        )
        sep_ep = build_entrant_profile(sep_sh)
    else:
        sep_ep = ep

    # Step 2: Salary/benefit table
    sbt = build_salary_benefit_table(
        sh, ep, inputs["salary_growth"], class_name, constants, get_tier,
    )

    # Step 3: Separation rate table
    sep = build_separation_rate_table(
        inputs["term_rate_avg"], inputs["normal_retire_tier1"],
        inputs["normal_retire_tier2"], inputs["early_retire_tier1"],
        inputs["early_retire_tier2"], sep_ep, sep_class, constants,
    )

    # Step 4: Annuity factor table → benefit table → final benefit table
    if "_compact_mortality" in inputs:
        from pension_model.core.benefit_tables import build_ann_factor_table_compact
        aft = build_ann_factor_table_compact(sbt, inputs["_compact_mortality"], class_name, constants)
    else:
        aft = build_ann_factor_table(inputs["mortality"], class_name, constants)
    bt = build_benefit_table(aft, sbt, class_name, constants, get_ben_mult, get_reduce_factor)
    fbt = build_final_benefit_table(bt)

    # Step 5: Benefit valuation table
    bvt = build_benefit_val_table(sbt, fbt, sep, class_name, constants, get_sep_type)

    return {
        "salary_headcount": sh,
        "entrant_profile": ep,
        "salary_benefit": sbt,
        "separation_rate": sep,
        "ann_factor": aft,
        "benefit": bt,
        "final_benefit": fbt,
        "benefit_val": bvt,
    }


def compute_active_liability(wf_active: pd.DataFrame, benefit_val: pd.DataFrame,
                             class_name: str, constants: ModelConstants) -> pd.DataFrame:
    """
    Compute active member liability by year (R liability model lines 77-120).

    Joins workforce active with benefit_val_table, allocates to plan designs,
    aggregates by year.
    """
    r = constants.ranges
    is_special = class_name == "special"
    db_before, db_after, db_new = constants.plan_design.get_ratios(is_special)
    new_year = r.new_year

    wf = wf_active[wf_active["year"] <= r.start_year + r.model_period].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join with benefit_val_table
    bvt_cols = ["entry_year", "entry_age", "yos", "salary",
                "pvfb_db_wealth_at_current_age", "pvfnc_db", "pvfs_at_current_age",
                "indv_norm_cost"]
    # Compute yos for the join
    wf["yos"] = wf["age"] - wf["entry_age"]

    wf = wf.merge(
        benefit_val[bvt_cols].drop_duplicates(subset=["entry_year", "entry_age", "yos"]),
        on=["entry_year", "entry_age", "yos"],
        how="left",
    )
    wf = wf.fillna(0)

    # Plan design allocation
    ey = wf["entry_year"]
    n = wf["n_active"]
    wf["n_db_legacy"] = np.where(ey < 2018, n * db_before, np.where(ey < new_year, n * db_after, 0.0))
    wf["n_db_new"] = np.where(ey < new_year, 0.0, n * db_new)
    wf["n_dc_legacy"] = np.where(ey < 2018, n * (1 - db_before), np.where(ey < new_year, n * (1 - db_after), 0.0))
    wf["n_dc_new"] = np.where(ey < new_year, 0.0, n * (1 - db_new))

    # Aggregate by year
    def _agg(g):
        sal = g["salary"].values
        pvfb = g["pvfb_db_wealth_at_current_age"].values
        pvfnc = g["pvfnc_db"].values
        nc = g["indv_norm_cost"].values
        ndl = g["n_db_legacy"].values
        ndn = g["n_db_new"].values
        ndcl = g["n_dc_legacy"].values
        ndcn = g["n_dc_new"].values

        return pd.Series({
            "payroll_db_legacy_est": (sal * ndl).sum(),
            "payroll_db_new_est": (sal * ndn).sum(),
            "payroll_dc_legacy_est": (sal * ndcl).sum(),
            "payroll_dc_new_est": (sal * ndcn).sum(),
            "total_payroll_est": (sal * g["n_active"].values).sum(),
            "pvfb_active_db_legacy_est": (pvfb * ndl).sum(),
            "pvfb_active_db_new_est": (pvfb * ndn).sum(),
            "pvfnc_db_legacy_est": (pvfnc * ndl).sum(),
            "pvfnc_db_new_est": (pvfnc * ndn).sum(),
            "total_n_active": g["n_active"].sum(),
        })

    result = wf.groupby("year").apply(_agg).reset_index()

    # Derived columns
    result["payroll_db_est"] = result["payroll_db_legacy_est"] + result["payroll_db_new_est"]
    result["nc_rate_db_legacy_est"] = np.where(
        result["payroll_db_legacy_est"] == 0, 0,
        (wf.groupby("year").apply(lambda g: (g["indv_norm_cost"] * g["salary"] * g["n_db_legacy"]).sum()).values
         / result["payroll_db_legacy_est"].values)
    )
    result["nc_rate_db_new_est"] = np.where(
        result["payroll_db_new_est"] == 0, 0,
        (wf.groupby("year").apply(lambda g: (g["indv_norm_cost"] * g["salary"] * g["n_db_new"]).sum()).values
         / result["payroll_db_new_est"].values)
    )
    result["aal_active_db_legacy_est"] = result["pvfb_active_db_legacy_est"] - result["pvfnc_db_legacy_est"]
    result["aal_active_db_new_est"] = result["pvfb_active_db_new_est"] - result["pvfnc_db_new_est"]

    return result


def compute_term_liability(wf_term: pd.DataFrame, benefit_val: pd.DataFrame,
                           benefit: pd.DataFrame, class_name: str,
                           constants: ModelConstants) -> pd.DataFrame:
    """Compute projected terminated vested liability by year (R lines 124-149)."""
    r = constants.ranges
    is_special = class_name == "special"
    db_before, db_after, db_new = constants.plan_design.get_ratios(is_special)

    wf = wf_term[(wf_term["year"] <= r.start_year + r.model_period) & (wf_term["n_term"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join benefit_val_table for pvfb_db_at_term_age
    bvt_key = benefit_val[["entry_year", "entry_age", "yos", "pvfb_db_at_term_age"]].copy()
    bvt_key["term_year"] = bvt_key["entry_year"] + bvt_key["yos"]
    bvt_key = bvt_key.drop_duplicates(subset=["entry_age", "entry_year", "term_year"])
    wf = wf.merge(bvt_key[["entry_age", "entry_year", "term_year", "pvfb_db_at_term_age"]],
                  on=["entry_age", "entry_year", "term_year"], how="left")

    # Join benefit_table for cum_mort_dr at current age/year
    # Must include term_year to avoid many-to-many (multiple yos per entry_age/entry_year/dist_age/dist_year)
    bt_cols = benefit[["entry_age", "entry_year", "dist_age", "dist_year", "term_year", "cum_mort_dr"]].drop_duplicates()
    wf = wf.merge(bt_cols, left_on=["entry_age", "entry_year", "age", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"], how="left")

    wf["pvfb_db_term"] = wf["pvfb_db_at_term_age"] / wf["cum_mort_dr"]

    ey = wf["entry_year"]
    wf["n_term_db_legacy"] = np.where(ey < 2018, wf["n_term"] * db_before,
                             np.where(ey < r.new_year, wf["n_term"] * db_after, 0.0))
    wf["n_term_db_new"] = np.where(ey < r.new_year, 0.0, wf["n_term"] * db_new)

    return wf.groupby("year").agg(
        aal_term_db_legacy_est=pd.NamedAgg("pvfb_db_term",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_term_db_legacy"]).sum()),
        aal_term_db_new_est=pd.NamedAgg("pvfb_db_term",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_term_db_new"]).sum()),
    ).reset_index()


def compute_refund_liability(wf_refund: pd.DataFrame, benefit: pd.DataFrame,
                             class_name: str, constants: ModelConstants) -> pd.DataFrame:
    """Compute refund liability by year (R lines 154-169)."""
    r = constants.ranges
    is_special = class_name == "special"
    db_before, db_after, db_new = constants.plan_design.get_ratios(is_special)

    wf = wf_refund[(wf_refund["year"] <= r.start_year + r.model_period) & (wf_refund["n_refund"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join benefit_table for db_ee_balance (include term_year to avoid many-to-many)
    bt_cols = benefit[["entry_age", "entry_year", "dist_age", "dist_year", "term_year", "db_ee_balance"]].drop_duplicates()
    wf = wf.merge(bt_cols, left_on=["entry_age", "entry_year", "age", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"], how="left")

    ey = wf["entry_year"]
    wf["n_refund_db_legacy"] = np.where(ey < 2018, wf["n_refund"] * db_before,
                               np.where(ey < r.new_year, wf["n_refund"] * db_after, 0.0))
    wf["n_refund_db_new"] = np.where(ey < r.new_year, 0.0, wf["n_refund"] * db_new)

    return wf.groupby("year").agg(
        refund_db_legacy_est=pd.NamedAgg("db_ee_balance",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_refund_db_legacy"]).sum()),
        refund_db_new_est=pd.NamedAgg("db_ee_balance",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_refund_db_new"]).sum()),
    ).reset_index()


def compute_retire_liability(wf_retire: pd.DataFrame, benefit: pd.DataFrame,
                             ann_factor: pd.DataFrame, class_name: str,
                             constants: ModelConstants) -> pd.DataFrame:
    """Compute projected retiree liability by year (R lines 174-200)."""
    r = constants.ranges
    is_special = class_name == "special"
    db_before, db_after, db_new = constants.plan_design.get_ratios(is_special)

    wf = wf_retire[wf_retire["year"] <= r.start_year + r.model_period].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join benefit_table for db_benefit and cola at retirement year (include term_year)
    bt_cols = benefit[["entry_age", "entry_year", "dist_year", "term_year", "db_benefit", "cola"]].drop_duplicates()
    wf = wf.merge(bt_cols, left_on=["entry_age", "entry_year", "retire_year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_year", "term_year"], how="left")

    # Join ann_factor_table for ann_factor at current year (include term_year)
    af_cols = ann_factor[["entry_age", "entry_year", "dist_year", "term_year", "ann_factor"]].drop_duplicates()
    wf = wf.merge(af_cols, left_on=["entry_age", "entry_year", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_year", "term_year"],
                  how="left", suffixes=("", "_af"))

    wf["db_benefit_final"] = wf["db_benefit"] * (1 + wf["cola"]) ** (wf["year"] - wf["retire_year"])
    wf["pvfb_db_retire"] = wf["db_benefit_final"] * (wf["ann_factor"] - 1)

    ey = wf["entry_year"]
    wf["n_retire_db_legacy"] = np.where(ey < 2018, wf["n_retire"] * db_before,
                               np.where(ey < r.new_year, wf["n_retire"] * db_after, 0.0))
    wf["n_retire_db_new"] = np.where(ey < r.new_year, 0.0, wf["n_retire"] * db_new)

    return wf.groupby("year").agg(
        retire_ben_db_legacy_est=pd.NamedAgg("db_benefit_final",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_retire_db_legacy"]).sum()),
        retire_ben_db_new_est=pd.NamedAgg("db_benefit_final",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_retire_db_new"]).sum()),
        aal_retire_db_legacy_est=pd.NamedAgg("pvfb_db_retire",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_retire_db_legacy"]).sum()),
        aal_retire_db_new_est=pd.NamedAgg("pvfb_db_retire",
            aggfunc=lambda x: (x * wf.loc[x.index, "n_retire_db_new"]).sum()),
    ).reset_index()


# ---------------------------------------------------------------------------
# Financial utility functions (replicate R's utility_functions.R)
# ---------------------------------------------------------------------------

def _pv_annuity(rate, g, nper, pmt, t=1):
    """R's pv() — present value of growing annuity."""
    r = (1 + rate) / (1 + g) - 1
    if abs(r) < 1e-10:
        return pmt * nper / (1 + g) * (1 + rate) ** (1 - t)
    return pmt / r * (1 - 1 / (1 + r) ** nper) / (1 + g) * (1 + rate) ** (1 - t)


def _get_pmt(r, g, nper, pv_val, t=1):
    """R's get_pmt() — amortization payment with growth."""
    r_adj = (1 + r) / (1 + g) - 1
    pv_adj = pv_val * (1 + r) ** t
    if abs(r_adj) < 1e-10:
        return pv_adj / nper if nper > 0 else 0
    if nper == 0:
        return 0
    return pv_adj * r_adj * (1 + r_adj) ** (nper - 1) / ((1 + r_adj) ** nper - 1)


def _recur_grow(x, g):
    """R's recur_grow: x[i] = x[i-1] * (1 + g[i-1]) — lagged growth."""
    out = x.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] * (1 + g[i - 1])
    return out


def _recur_grow2(x, g):
    """R's recur_grow2: x[i] = x[i-1] * (1 + g[i]) — no lag."""
    out = x.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] * (1 + g[i])
    return out


def _recur_grow3(x, g, nper):
    """R's recur_grow3: grow single value at fixed rate for nper periods."""
    vec = np.zeros(nper)
    vec[0] = x
    for i in range(1, nper):
        vec[i] = vec[i - 1] * (1 + g)
    return vec


def _roll_pv(rate, g, nper, pmt_vec, t=1):
    """R's roll_pv: rolling present value of payment stream."""
    n = len(pmt_vec)
    pv_vec = np.zeros(n)
    for i in range(n):
        if i == 0:
            pv_vec[i] = _pv_annuity(rate, g, nper, pmt_vec[1] if n > 1 else 0, t)
        else:
            pv_vec[i] = pv_vec[i - 1] * (1 + rate) - pmt_vec[i] * (1 + rate) ** (1 - t)
    return pv_vec


# ---------------------------------------------------------------------------
# Current retiree and current term vested liability
# ---------------------------------------------------------------------------

def compute_current_retiree_liability(
    ann_factor_retire: pd.DataFrame,
    retiree_distribution: pd.DataFrame,
    retiree_pop: float,
    ben_payment_current: float,
    constants: ModelConstants,
) -> pd.DataFrame:
    """
    Project current retiree AAL (R liability model lines 204-234).

    Uses ann_factor_retire_table with mortality and COLA to project
    current retiree population and benefits forward.
    """
    r = constants.ranges

    # Initialize current retirees
    init = retiree_distribution[["age", "n_retire_ratio", "total_ben_ratio"]].copy()
    init["n_retire_current"] = init["n_retire_ratio"] * retiree_pop
    init["total_ben_current"] = init["total_ben_ratio"] * ben_payment_current
    init["avg_ben_current"] = init["total_ben_current"] / init["n_retire_current"]
    init["year"] = r.start_year

    # Join with ann_factor_retire_table
    afr = ann_factor_retire[ann_factor_retire["year"] <= r.start_year + r.model_period].copy()
    merged = afr.merge(
        init[["age", "year", "n_retire_current", "avg_ben_current", "total_ben_current"]],
        on=["age", "year"], how="left",
    )

    # Project within each base_age group
    results = []
    for base_age, group in merged.groupby("base_age"):
        g = group.sort_values("year").copy()
        n = g["n_retire_current"].values.copy()
        avg = g["avg_ben_current"].values.copy()
        mort = g["mort_final"].values
        cola = g["cola"].values

        n = _recur_grow(n, -mort)
        avg = _recur_grow2(avg, cola)

        g["n_retire_current"] = n
        g["avg_ben_current"] = avg
        g["total_ben_current"] = n * avg
        g["pvfb_retire_current"] = avg * (g["ann_factor_retire"].values - 1)
        g = g[g["n_retire_current"].notna()]
        results.append(g)

    projected = pd.concat(results, ignore_index=True)

    return projected.groupby("year").agg(
        retire_ben_current_est=("total_ben_current", "sum"),
        aal_retire_current_est=pd.NamedAgg("pvfb_retire_current",
            aggfunc=lambda x: (x * projected.loc[x.index, "n_retire_current"]).sum()),
    ).reset_index()


def compute_current_term_vested_liability(
    class_name: str, constants: ModelConstants,
) -> pd.DataFrame:
    """
    Compute current term vested AAL (R liability model lines 238-248).

    Amortizes pvfb_term_current as a growing payment stream.
    """
    r = constants.ranges
    econ = constants.economic
    fund = constants.funding
    cd = constants.class_data[class_name]

    pvfb_term_current = cd.pvfb_term_current
    dr = econ.dr_current
    payroll_growth = econ.payroll_growth
    amo_period = fund.amo_period_term

    # Compute amortization payment
    retire_ben_term = _get_pmt(dr, payroll_growth, amo_period, pvfb_term_current, t=1)

    years = list(range(r.start_year, r.start_year + r.model_period + 1))
    amo_years = list(range(r.start_year + 1, r.start_year + 1 + amo_period))

    retire_ben_term_est = np.zeros(len(years))
    term_payments = _recur_grow3(retire_ben_term, payroll_growth, amo_period)
    for i, yr in enumerate(years):
        if yr in amo_years:
            idx = yr - (r.start_year + 1)
            if idx < len(term_payments):
                retire_ben_term_est[i] = term_payments[idx]

    aal_term_current = _roll_pv(dr, payroll_growth, amo_period, retire_ben_term_est, t=1)

    return pd.DataFrame({
        "year": years,
        "retire_ben_term_est": retire_ben_term_est,
        "aal_term_current_est": aal_term_current,
    })


def run_class_pipeline(class_name: str, baseline_dir: Path,
                       constants: ModelConstants = None) -> pd.DataFrame:
    """
    Run the full pipeline for a single class: raw inputs → liability output.

    Returns a DataFrame matching R's liability.csv structure.
    """
    if constants is None:
        constants = frs_constants()

    inputs = load_raw_inputs(class_name, baseline_dir)

    # Build all benefit tables from raw inputs
    tables = build_benefit_tables(class_name, inputs, constants, baseline_dir)

    # Compute liability components
    active = compute_active_liability(
        inputs["wf_active"], tables["benefit_val"], class_name, constants)

    term = compute_term_liability(
        inputs["wf_term"], tables["benefit_val"], tables["benefit"],
        class_name, constants)

    refund = compute_refund_liability(
        inputs["wf_refund"], tables["benefit"], class_name, constants)

    retire = compute_retire_liability(
        inputs["wf_retire"], tables["benefit"], tables["ann_factor"],
        class_name, constants)

    # Current retiree liability
    cd = constants.class_data[class_name]
    ben_payment = cd.outflow * constants.ben_payment_ratio
    retire_current = compute_current_retiree_liability(
        inputs["ann_factor_retire"], inputs["retiree_distribution"],
        cd.retiree_pop, ben_payment, constants)

    # Current term vested liability
    term_current = compute_current_term_vested_liability(class_name, constants)

    # Merge all components by year
    years = pd.DataFrame({"year": range(constants.ranges.start_year,
                                        constants.ranges.start_year + constants.ranges.model_period + 1)})
    result = years.merge(active, on="year", how="left")
    result = result.merge(term, on="year", how="left")
    result = result.merge(refund, on="year", how="left")
    result = result.merge(retire, on="year", how="left")
    result = result.merge(retire_current, on="year", how="left")
    result = result.merge(term_current, on="year", how="left")
    result = result.fillna(0)

    # Compute total AAL (R liability model lines 259-266)
    result["aal_legacy_est"] = (
        result["aal_active_db_legacy_est"]
        + result["aal_term_db_legacy_est"]
        + result["aal_retire_db_legacy_est"]
        + result["aal_retire_current_est"]
        + result["aal_term_current_est"]
    )
    result["aal_new_est"] = (
        result["aal_active_db_new_est"]
        + result["aal_term_db_new_est"]
        + result["aal_retire_db_new_est"]
    )
    result["total_aal_est"] = result["aal_legacy_est"] + result["aal_new_est"]

    # Total benefit/refund outflows
    result["tot_ben_refund_legacy_est"] = (
        result["refund_db_legacy_est"]
        + result["retire_ben_db_legacy_est"]
        + result["retire_ben_current_est"]
        + result["retire_ben_term_est"]
    )
    result["tot_ben_refund_new_est"] = (
        result["refund_db_new_est"]
        + result["retire_ben_db_new_est"]
    )
    # Liability gain/loss (zero under baseline: experience = assumptions)
    result["liability_gain_loss_legacy_est"] = 0.0
    result["liability_gain_loss_new_est"] = 0.0
    result["total_liability_gain_loss_est"] = 0.0

    result["tot_ben_refund_est"] = (
        result["tot_ben_refund_legacy_est"]
        + result["tot_ben_refund_new_est"]
    )

    return result


def run_class_pipeline_e2e(class_name: str, baseline_dir: Path,
                           constants: ModelConstants = None) -> pd.DataFrame:
    """
    Fully end-to-end pipeline: Stage 3 data -> liability output.

    Unlike run_class_pipeline() which loads R's pre-computed workforce CSVs,
    this function computes the workforce projection from scratch using
    benefit decisions derived from our own benefit tables.

    Still requires from R extraction:
      - Mortality CSV (will be replaced with raw Excel build later)
      - Initial active population (wf_active year 0)
      - Decrement tables, salary/headcount, ann_factor_retire, retiree_distribution
    """
    from pension_model.core.workforce import project_workforce
    from pension_model.core.mortality_builder import (
        build_compact_mortality_from_excel, build_ann_factor_retire_table,
    )
    from pension_model.core.decrement_builder import (
        build_withdrawal_rate_table, build_retirement_rate_tables,
    )
    from pension_model.core.tier_logic import get_sep_type

    if constants is None:
        constants = frs_constants()

    sep_class = SEP_CLASS_MAP[class_name]
    raw_dir = baseline_dir.parent / "R_model" / "R_model_original"
    frs_inputs = raw_dir / "Florida FRS inputs.xlsx"
    extracted_inputs = raw_dir / "Reports" / "extracted inputs"

    # Build ALL tables from raw Excel — NO R computation products
    cm = build_compact_mortality_from_excel(
        raw_dir / "pub-2010-headcount-mort-rates.xlsx",
        raw_dir / "mortality-improvement-scale-mp-2018-rates.xlsx",
        class_name,
    )

    afr = build_ann_factor_retire_table(
        cm, class_name, constants.ranges.start_year, constants.ranges.model_period,
        constants.economic.dr_current, constants.benefit.cola_current_retire,
    )

    # Build decrement tables from raw Excel
    term_rate_avg = build_withdrawal_rate_table(frs_inputs, sep_class, 70)
    ret_tables = build_retirement_rate_tables(frs_inputs, extracted_inputs, sep_class)

    inputs = {
        "salary": pd.read_csv(baseline_dir / f"{class_name}_salary.csv"),
        "headcount": pd.read_csv(baseline_dir / f"{class_name}_headcount.csv"),
        "salary_growth": pd.read_csv(baseline_dir / "salary_growth_table.csv"),
        "retiree_distribution": pd.read_csv(baseline_dir / "retiree_distribution.csv"),
        "term_rate_avg": term_rate_avg,
        "normal_retire_tier1": ret_tables["normal_retire_tier1"],
        "normal_retire_tier2": ret_tables["normal_retire_tier2"],
        "early_retire_tier1": ret_tables["early_retire_tier1"],
        "early_retire_tier2": ret_tables["early_retire_tier2"],
        "ann_factor_retire": afr,
        "_compact_mortality": cm,  # for workforce + ann_factor_table
    }

    # Build benefit tables
    tables = build_benefit_tables(class_name, inputs, constants, baseline_dir)

    # Derive benefit decisions from our benefit_val + final_benefit
    bvt = tables["benefit_val"]
    fbt = tables["final_benefit"]
    bvt_bd = bvt[["entry_year", "entry_age", "yos", "term_age", "tier_at_term_age"]].copy()
    bvt_bd["sep_type"] = bvt_bd["tier_at_term_age"].apply(get_sep_type)
    bvt_bd["ben_decision"] = bvt_bd["sep_type"].map(
        {"retire": "retire", "vested": "mix", "non_vested": "refund"})
    bvt_bd.loc[bvt_bd["yos"] == 0, "ben_decision"] = np.nan
    ben_decisions = bvt_bd.merge(
        fbt[["entry_year", "entry_age", "term_age", "dist_age"]].drop_duplicates(),
        on=["entry_year", "entry_age", "term_age"], how="left")
    ben_decisions["dist_age"] = ben_decisions["dist_age"].fillna(ben_decisions["term_age"]).astype(int)
    ben_decisions = ben_decisions[ben_decisions["ben_decision"].notna()]

    # Initial active population from salary_headcount (no R wf_active CSV needed)
    # Filter to entry ages in the entrant profile (R's workforce model does this)
    sh = tables["salary_headcount"]
    valid_entry_ages = set(tables["entrant_profile"]["entry_age"].values)
    initial_active = sh[sh["entry_age"].isin(valid_entry_ages)][
        ["entry_age", "age", "count"]].rename(columns={"count": "n_active"}).copy()
    initial_active = initial_active[initial_active["n_active"] > 0]

    # Run workforce projection
    wf = project_workforce(
        initial_active, tables["separation_rate"], ben_decisions, cm,
        tables["entrant_profile"], class_name,
        constants.ranges.start_year, constants.ranges.model_period,
        constants.economic.pop_growth, constants.benefit.retire_refund_ratio)

    # Compute liability from projected workforce
    active = compute_active_liability(
        wf["wf_active"], tables["benefit_val"], class_name, constants)
    term = compute_term_liability(
        wf["wf_term"], tables["benefit_val"], tables["benefit"], class_name, constants)
    refund = compute_refund_liability(
        wf["wf_refund"], tables["benefit"], class_name, constants)
    retire = compute_retire_liability(
        wf["wf_retire"], tables["benefit"], tables["ann_factor"], class_name, constants)

    cd = constants.class_data[class_name]
    ben_payment = cd.outflow * constants.ben_payment_ratio
    retire_current = compute_current_retiree_liability(
        inputs["ann_factor_retire"], inputs["retiree_distribution"],
        cd.retiree_pop, ben_payment, constants)
    term_current = compute_current_term_vested_liability(class_name, constants)

    # Merge components
    years = pd.DataFrame({"year": range(constants.ranges.start_year,
                                        constants.ranges.start_year + constants.ranges.model_period + 1)})
    result = years.merge(active, on="year", how="left")
    result = result.merge(term, on="year", how="left")
    result = result.merge(refund, on="year", how="left")
    result = result.merge(retire, on="year", how="left")
    result = result.merge(retire_current, on="year", how="left")
    result = result.merge(term_current, on="year", how="left")
    result = result.fillna(0)

    result["aal_legacy_est"] = (
        result["aal_active_db_legacy_est"] + result["aal_term_db_legacy_est"]
        + result["aal_retire_db_legacy_est"] + result["aal_retire_current_est"]
        + result["aal_term_current_est"])
    result["aal_new_est"] = (
        result["aal_active_db_new_est"] + result["aal_term_db_new_est"]
        + result["aal_retire_db_new_est"])
    result["total_aal_est"] = result["aal_legacy_est"] + result["aal_new_est"]
    result["tot_ben_refund_legacy_est"] = (
        result["refund_db_legacy_est"] + result["retire_ben_db_legacy_est"]
        + result["retire_ben_current_est"] + result["retire_ben_term_est"])
    result["tot_ben_refund_new_est"] = (
        result["refund_db_new_est"] + result["retire_ben_db_new_est"])
    result["tot_ben_refund_est"] = (
        result["tot_ben_refund_legacy_est"] + result["tot_ben_refund_new_est"])
    result["liability_gain_loss_legacy_est"] = 0.0
    result["liability_gain_loss_new_est"] = 0.0
    result["total_liability_gain_loss_est"] = 0.0
    result["retire_ben_db_new_est"] = result.get("retire_ben_db_new_est", 0)
    result["refund_db_new_est"] = result.get("refund_db_new_est", 0)

    return result
