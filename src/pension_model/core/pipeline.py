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

from pension_model.plan_config import (
    PlanConfig, load_frs_config,
    get_tier as pc_get_tier,
    get_ben_mult as pc_get_ben_mult,
    get_reduce_factor as pc_get_reduce_factor,
    get_sep_type as pc_get_sep_type,
)
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
                             constants, baseline_dir: Path) -> float:
    """Compute headcount adjustment ratio matching R model."""
    if class_name in ("eco", "eso", "judges"):
        combined_raw = sum(
            pd.read_csv(baseline_dir / f"{c}_headcount.csv").iloc[:, 1:].sum().sum()
            for c in ("eco", "eso", "judges")
        )
        return 2075 / combined_raw  # eco_eso_judges_total_active_member_
    return constants.class_data[class_name].total_active_member / headcount.iloc[:, 1:].sum().sum()


def _make_callables(constants, class_name=None):
    """Create tier/benefit callables from constants.

    Always uses config-driven callables. When constants is a ModelConstants
    (legacy path), loads the FRS PlanConfig for tier/benefit lookups.
    """
    if isinstance(constants, PlanConfig):
        cfg = constants
    else:
        # Legacy ModelConstants — use FRS config for tier/benefit rules
        cfg = load_frs_config()
    return (
        lambda cn, ey, age, yos, ny=None, **kw: pc_get_tier(cfg, cn, ey, age, yos),
        lambda cn, tier, da, yos, dy=0: pc_get_ben_mult(cfg, cn, tier, da, yos, dy),
        lambda cn, tier, da, yos=0, ey=0: pc_get_reduce_factor(cfg, cn, tier, da, yos, ey),
        pc_get_sep_type,
    )


def build_benefit_tables(class_name: str, inputs: dict, constants,
                         baseline_dir: Path) -> dict:
    """
    Build all benefit tables from raw inputs for a single class.

    Args:
        constants: PlanConfig or ModelConstants.

    Returns dict with: salary_headcount, entrant_profile, salary_benefit,
        separation_rate, ann_factor, benefit, final_benefit, benefit_val
    """
    tier_fn, ben_mult_fn, reduce_fn, sep_type_fn = _make_callables(constants)

    adj_ratio = compute_adjustment_ratio(class_name, inputs["headcount"], constants, baseline_dir)
    sep_class = (constants.get_sep_class(class_name) if isinstance(constants, PlanConfig)
                 else SEP_CLASS_MAP.get(class_name, class_name))

    # --- ICR computation (when cash balance is active) ---
    has_cb = (hasattr(constants, "benefit_types") and "cb" in constants.benefit_types
              and getattr(constants, "cash_balance", None) is not None)
    expected_icr = None
    actual_icr_series = None
    if has_cb:
        from pension_model.core.icr import compute_expected_icr, compute_actual_icr_series
        cb = constants.cash_balance
        expected_icr = compute_expected_icr(
            constants.model_return, cb.get("return_volatility", 0.12),
            cb["icr_smooth_period"], cb["icr_floor"], cb["icr_cap"],
            cb["icr_upside_share"],
        )
        # Actual ICR: under "assumption" scenario, returns = model_return every year
        years = range(constants.min_entry_year, constants.max_year + 1)
        # Use return_scenario from inputs if available, else constant model_return
        ret_scenario = inputs.get("_return_scenario")
        if ret_scenario is None:
            ret_scenario = pd.Series(constants.model_return, index=list(years))
        actual_icr_series = compute_actual_icr_series(
            years, constants.start_year, ret_scenario,
            cb["icr_smooth_period"], cb["icr_floor"], cb["icr_cap"],
            cb["icr_upside_share"],
        )

    # Step 1: Salary/headcount
    sh = build_salary_headcount_table(
        inputs["salary"], inputs["headcount"], inputs["salary_growth"],
        class_name, adj_ratio, constants.ranges.start_year,
        constants=constants,
    )
    # Use explicit entrant profile if provided (e.g., TRS reads from Excel sheet),
    # otherwise derive from salary_headcount (FRS approach).
    if "_entrant_profile" in inputs:
        ep = inputs["_entrant_profile"]
    else:
        ep = build_entrant_profile(sh)

    # For separation rates, use the sep_class's salary/headcount if different
    if sep_class != class_name:
        sep_sal = pd.read_csv(baseline_dir / f"{sep_class}_salary.csv")
        sep_hc = pd.read_csv(baseline_dir / f"{sep_class}_headcount.csv")
        sep_adj = compute_adjustment_ratio(sep_class, sep_hc, constants, baseline_dir)
        sep_sh = build_salary_headcount_table(
            sep_sal, sep_hc, inputs["salary_growth"],
            sep_class, sep_adj, constants.ranges.start_year,
            constants=constants,
        )
        sep_ep = build_entrant_profile(sep_sh)
    else:
        sep_ep = ep

    # Step 2: Salary/benefit table (with ICR for CB balance accumulation)
    sbt = build_salary_benefit_table(
        sh, ep, inputs["salary_growth"], class_name, constants, tier_fn,
        actual_icr_series=actual_icr_series,
    )

    # Step 3: Separation rate table
    if "_separation_rate" in inputs:
        # Pre-built separation rate table (e.g., TRS with different decrement structure)
        sep = inputs["_separation_rate"]
    else:
        sep = build_separation_rate_table(
            inputs["term_rate_avg"], inputs["normal_retire_tier1"],
            inputs["normal_retire_tier2"], inputs["early_retire_tier1"],
            inputs["early_retire_tier2"], sep_ep, sep_class, constants,
            get_tier_fn=tier_fn,
        )

    # Step 4: Annuity factor table → benefit table → final benefit table
    if "_compact_mortality" in inputs:
        from pension_model.core.benefit_tables import build_ann_factor_table_compact
        # Pass config-driven tier function for all PlanConfig plans
        aft_tier_fn = None
        if isinstance(constants, PlanConfig):
            aft_tier_fn = lambda cn, ey, da, yos: tier_fn(cn, ey, da, yos)
        aft = build_ann_factor_table_compact(sbt, inputs["_compact_mortality"], class_name, constants,
                                             expected_icr=expected_icr,
                                             get_tier_fn=aft_tier_fn)
    else:
        aft = build_ann_factor_table(inputs["mortality"], class_name, constants)
    bt = build_benefit_table(aft, sbt, class_name, constants, ben_mult_fn, reduce_fn)
    # Config-driven: use_earliest_retire determines whether members retire at
    # earliest eligible age (incl. early) or earliest normal retirement age.
    use_earliest = (constants.use_earliest_retire
                    if isinstance(constants, PlanConfig) else False)
    fbt = build_final_benefit_table(bt, use_earliest_retire=use_earliest)

    # Step 5: Benefit valuation table (with expected ICR for CB PVFB projection)
    bvt = build_benefit_val_table(sbt, fbt, sep, class_name, constants, sep_type_fn,
                                  expected_icr=expected_icr, ann_factor_table=aft)

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


def _get_bt_columns(bt: str) -> dict:
    """Map benefit type to its column names in benefit_val_table."""
    if bt == "db":
        return {"pvfb": "pvfb_db_wealth_at_current_age", "pvfnc": "pvfnc_db",
                "nc": "indv_norm_cost"}
    elif bt == "cb":
        return {"pvfb": "pvfb_cb_at_current_age", "pvfnc": "pvfnc_cb",
                "nc": "indv_norm_cost_cb"}
    # DC has no liability columns
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


def compute_active_liability(wf_active: pd.DataFrame, benefit_val: pd.DataFrame,
                             class_name: str, constants) -> pd.DataFrame:
    """
    Compute active member liability by year.

    Generalizes across benefit types: for each bt in config, allocates
    members and computes payroll_{bt}_{period}_est, aal_active_{bt}_{period}_est, etc.
    """
    r = constants.ranges
    new_year = r.new_year
    design_cutoff = (constants.plan_design_cutoff_year or new_year
                     if hasattr(constants, "plan_design_cutoff_year") else 2018)

    # Get design ratios — use generalized method if available, else legacy
    if hasattr(constants, "get_design_ratios"):
        design_ratios = constants.get_design_ratios(class_name)
        benefit_types = list(constants.benefit_types)
    else:
        is_special = class_name == "special"
        db_b, db_a, db_n = constants.plan_design.get_ratios(is_special)
        design_ratios = {"db": (db_b, db_a, db_n), "dc": (1 - db_b, 1 - db_a, 1 - db_n)}
        benefit_types = ["db", "dc"]

    wf = wf_active[wf_active["year"] <= r.start_year + r.model_period].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])
    wf["yos"] = wf["age"] - wf["entry_age"]

    # Join with benefit_val_table
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

    # Allocate members to benefit types
    wf = _allocate_members(wf, benefit_types, design_ratios, new_year, design_cutoff)

    # Aggregate by year — build result dict dynamically
    def _agg(g):
        sal = g["salary"].values
        out = {
            "total_payroll_est": (sal * g["n_active"].values).sum(),
            "total_n_active": g["n_active"].sum(),
        }
        for bt in benefit_types:
            nl = g[f"n_{bt}_legacy"].values
            nn = g[f"n_{bt}_new"].values
            out[f"payroll_{bt}_legacy_est"] = (sal * nl).sum()
            out[f"payroll_{bt}_new_est"] = (sal * nn).sum()

            cols = _get_bt_columns(bt)
            if cols["pvfb"] is not None and cols["pvfb"] in g.columns:
                pvfb = g[cols["pvfb"]].values
                pvfnc = g[cols["pvfnc"]].values
                out[f"pvfb_active_{bt}_legacy_est"] = (pvfb * nl).sum()
                out[f"pvfb_active_{bt}_new_est"] = (pvfb * nn).sum()
                out[f"pvfnc_{bt}_legacy_est"] = (pvfnc * nl).sum()
                out[f"pvfnc_{bt}_new_est"] = (pvfnc * nn).sum()
        return pd.Series(out)

    result = wf.groupby("year").apply(_agg).reset_index()

    # Derived columns for each benefit type with liability
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
            nc_num = wf.groupby("year").apply(
                lambda g, _bt=bt, _nc=nc_col, _p=period: (
                    g[_nc] * g["salary"] * g[f"n_{_bt}_{_p}"]
                ).sum()).values
            result[f"nc_rate_{bt}_{period}_est"] = np.divide(
                nc_num, payroll_arr, out=np.zeros_like(payroll_arr), where=payroll_arr != 0)

            pvfb_col = f"pvfb_active_{bt}_{period}_est"
            pvfnc_col = f"pvfnc_{bt}_{period}_est"
            if pvfb_col in result.columns and pvfnc_col in result.columns:
                result[f"aal_active_{bt}_{period}_est"] = result[pvfb_col] - result[pvfnc_col]

    # Backward compat: payroll_db_est
    if "payroll_db_legacy_est" in result.columns:
        result["payroll_db_est"] = result["payroll_db_legacy_est"] + result.get("payroll_db_new_est", 0)

    return result


def _get_design_ratios(constants, class_name):
    """Get design ratios and benefit types from constants (PlanConfig or ModelConstants)."""
    if hasattr(constants, "get_design_ratios"):
        return constants.get_design_ratios(class_name), list(constants.benefit_types)
    is_special = class_name == "special"
    db_b, db_a, db_n = constants.plan_design.get_ratios(is_special)
    return {"db": (db_b, db_a, db_n), "dc": (1 - db_b, 1 - db_a, 1 - db_n)}, ["db", "dc"]


def _allocate_term(wf, pop_col, design_ratios, benefit_types, new_year, design_cutoff_year=2018):
    """Allocate term/refund/retire workforce to benefit type buckets.

    pop_col is e.g. "n_term", "n_refund", "n_retire".
    Creates columns like "n_term_db_legacy", "n_term_db_new", etc.
    """
    ey = wf["entry_year"]
    n = wf[pop_col]
    # Strip the "n_" prefix if present for cleaner column names
    base = pop_col[2:] if pop_col.startswith("n_") else pop_col
    for bt in benefit_types:
        before, after, new = design_ratios[bt]
        wf[f"n_{base}_{bt}_legacy"] = np.where(
            ey < new_year, np.where(ey < design_cutoff_year, n * before, n * after), 0.0)
        wf[f"n_{base}_{bt}_new"] = np.where(ey < new_year, 0.0, n * new)
    return wf


def compute_term_liability(wf_term: pd.DataFrame, benefit_val: pd.DataFrame,
                           benefit: pd.DataFrame, class_name: str,
                           constants) -> pd.DataFrame:
    """Compute projected terminated vested liability by year."""
    r = constants.ranges
    design_ratios, benefit_types = _get_design_ratios(constants, class_name)
    design_cutoff = (constants.plan_design_cutoff_year or r.new_year
                     if hasattr(constants, "plan_design_cutoff_year") else 2018)

    wf = wf_term[(wf_term["year"] <= r.start_year + r.model_period) & (wf_term["n_term"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join benefit_val_table for pvfb_db_at_term_age
    bvt_key = benefit_val[["entry_year", "entry_age", "yos", "pvfb_db_at_term_age"]].copy()
    bvt_key["term_year"] = bvt_key["entry_year"] + bvt_key["yos"]
    bvt_key = bvt_key.drop_duplicates(subset=["entry_age", "entry_year", "term_year"])
    wf = wf.merge(bvt_key[["entry_age", "entry_year", "term_year", "pvfb_db_at_term_age"]],
                  on=["entry_age", "entry_year", "term_year"], how="left")

    # Join benefit_table for cum_mort_dr at current age/year
    bt_cols = benefit[["entry_age", "entry_year", "dist_age", "dist_year", "term_year", "cum_mort_dr"]].drop_duplicates()
    wf = wf.merge(bt_cols, left_on=["entry_age", "entry_year", "age", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"], how="left")

    wf["pvfb_db_term"] = wf["pvfb_db_at_term_age"] / wf["cum_mort_dr"]

    wf = _allocate_term(wf, "n_term", design_ratios, benefit_types, r.new_year, design_cutoff)

    # Aggregate by benefit type
    agg_dict = {}
    for bt in benefit_types:
        if bt == "dc":
            continue
        val_col = "pvfb_db_term"
        for period in ["legacy", "new"]:
            n_col = f"n_term_{bt}_{period}"
            if n_col in wf.columns:
                agg_dict[f"aal_term_{bt}_{period}_est"] = pd.NamedAgg(
                    val_col, aggfunc=lambda x, _n=n_col: (x * wf.loc[x.index, _n]).sum())

    if not agg_dict:
        return pd.DataFrame({"year": wf["year"].unique()})
    return wf.groupby("year").agg(**agg_dict).reset_index()


def compute_refund_liability(wf_refund: pd.DataFrame, benefit: pd.DataFrame,
                             class_name: str, constants) -> pd.DataFrame:
    """Compute refund liability by year."""
    r = constants.ranges
    design_ratios, benefit_types = _get_design_ratios(constants, class_name)
    design_cutoff = (constants.plan_design_cutoff_year or r.new_year
                     if hasattr(constants, "plan_design_cutoff_year") else 2018)

    wf = wf_refund[(wf_refund["year"] <= r.start_year + r.model_period) & (wf_refund["n_refund"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join benefit_table for db_ee_balance (+ cb_balance if present)
    bt_join_cols = ["entry_age", "entry_year", "dist_age", "dist_year", "term_year", "db_ee_balance"]
    has_cb_bal = "cb_balance" in benefit.columns
    if has_cb_bal:
        bt_join_cols.append("cb_balance")
    bt_cols = benefit[bt_join_cols].drop_duplicates()
    wf = wf.merge(bt_cols, left_on=["entry_age", "entry_year", "age", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"], how="left")

    wf = _allocate_term(wf, "n_refund", design_ratios, benefit_types, r.new_year, design_cutoff)

    agg_dict = {}
    for bt in benefit_types:
        if bt == "dc":
            continue
        val_col = "cb_balance" if bt == "cb" and has_cb_bal else "db_ee_balance"
        for period in ["legacy", "new"]:
            n_col = f"n_refund_{bt}_{period}"
            if n_col in wf.columns:
                agg_dict[f"refund_{bt}_{period}_est"] = pd.NamedAgg(
                    val_col, aggfunc=lambda x, _n=n_col: (x * wf.loc[x.index, _n]).sum())

    if not agg_dict:
        return pd.DataFrame({"year": wf["year"].unique()})
    return wf.groupby("year").agg(**agg_dict).reset_index()


def compute_retire_liability(wf_retire: pd.DataFrame, benefit: pd.DataFrame,
                             ann_factor: pd.DataFrame, class_name: str,
                             constants) -> pd.DataFrame:
    """Compute projected retiree liability by year."""
    r = constants.ranges
    design_ratios, benefit_types = _get_design_ratios(constants, class_name)
    design_cutoff = (constants.plan_design_cutoff_year or r.new_year
                     if hasattr(constants, "plan_design_cutoff_year") else 2018)

    wf = wf_retire[wf_retire["year"] <= r.start_year + r.model_period].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join benefit_table for db_benefit, cola (+ cb_benefit if present)
    bt_join_cols = ["entry_age", "entry_year", "dist_year", "term_year", "db_benefit", "cola"]
    has_cb_ben = "cb_benefit" in benefit.columns
    if has_cb_ben:
        bt_join_cols.append("cb_benefit")
    bt_cols = benefit[bt_join_cols].drop_duplicates()
    wf = wf.merge(bt_cols, left_on=["entry_age", "entry_year", "retire_year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_year", "term_year"], how="left")

    # Join ann_factor_table for ann_factor at current year
    af_cols = ann_factor[["entry_age", "entry_year", "dist_year", "term_year", "ann_factor"]].drop_duplicates()
    wf = wf.merge(af_cols, left_on=["entry_age", "entry_year", "year", "term_year"],
                  right_on=["entry_age", "entry_year", "dist_year", "term_year"],
                  how="left", suffixes=("", "_af"))

    wf["db_benefit_final"] = wf["db_benefit"] * (1 + wf["cola"]) ** (wf["year"] - wf["retire_year"])
    wf["pvfb_db_retire"] = wf["db_benefit_final"] * (wf["ann_factor"] - 1)

    if has_cb_ben:
        wf["cb_benefit_final"] = wf["cb_benefit"] * (1 + wf["cola"]) ** (wf["year"] - wf["retire_year"])
        wf["pvfb_cb_retire"] = wf["cb_benefit_final"] * (wf["ann_factor"] - 1)

    wf = _allocate_term(wf, "n_retire", design_ratios, benefit_types, r.new_year, design_cutoff)

    agg_dict = {}
    for bt in benefit_types:
        if bt == "dc":
            continue
        ben_col = "cb_benefit_final" if bt == "cb" and has_cb_ben else "db_benefit_final"
        pvfb_col = "pvfb_cb_retire" if bt == "cb" and has_cb_ben else "pvfb_db_retire"
        for period in ["legacy", "new"]:
            n_col = f"n_retire_{bt}_{period}"
            if n_col in wf.columns:
                agg_dict[f"retire_ben_{bt}_{period}_est"] = pd.NamedAgg(
                    ben_col, aggfunc=lambda x, _n=n_col: (x * wf.loc[x.index, _n]).sum())
                agg_dict[f"aal_retire_{bt}_{period}_est"] = pd.NamedAgg(
                    pvfb_col, aggfunc=lambda x, _n=n_col: (x * wf.loc[x.index, _n]).sum())

    if not agg_dict:
        return pd.DataFrame({"year": wf["year"].unique()})
    return wf.groupby("year").agg(**agg_dict).reset_index()


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
    constants,
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


def _npv(rate, cashflows):
    """Net present value of a cashflow stream (R's npv function)."""
    pv = 0.0
    for i, cf in enumerate(cashflows):
        pv += cf / (1 + rate) ** (i + 1)
    return pv


def _roll_npv(rate, cashflows):
    """Rolling NPV: NPV at each point looking forward (R's roll_npv)."""
    n = len(cashflows)
    pv_vec = np.zeros(n)
    for i in range(n - 1):
        pv_vec[i] = _npv(rate, cashflows[i + 1:])
    return pv_vec


def compute_current_term_vested_liability(
    class_name: str, constants,
) -> pd.DataFrame:
    """
    Compute current term vested AAL (R liability model lines 238-248 / 286-310).

    FRS: Amortizes pvfb_term_current as a growing payment stream.
    TRS: Uses bell curve (normal distribution) weighting of payments.
    """
    r = constants.ranges
    econ = constants.economic
    fund = constants.funding
    cd = constants.class_data[class_name]

    pvfb_term_current = cd.pvfb_term_current
    dr = econ.dr_current
    payroll_growth = econ.payroll_growth
    amo_period = fund.amo_period_term

    years = list(range(r.start_year, r.start_year + r.model_period + 1))

    tv_method = (constants.term_vested_method
                 if isinstance(constants, PlanConfig) else "growing_annuity")

    if tv_method == "bell_curve":
        mid = amo_period / 2
        spread = amo_period / 5
        amo_seq = np.arange(1, amo_period + 1)
        # Normal PDF: 1/(sigma*sqrt(2*pi)) * exp(-0.5*((x-mu)/sigma)^2)
        amo_weights = (1 / (spread * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((amo_seq - mid) / spread) ** 2)
        ann_ratio = amo_weights / amo_weights[0]

        first_payment = pvfb_term_current / _npv(dr, ann_ratio)
        term_payments = first_payment * ann_ratio  # length = amo_period

        # R builds: c(0, payments_1..payments_50) then truncates to model_period+1
        # But roll_npv sees the FULL stream for NPV calculation
        full_stream = np.concatenate(([0.0], term_payments))  # length = amo_period + 1

        # Compute roll_npv on full stream, then truncate to model_period+1
        full_aal = _roll_npv(dr, full_stream)

        # Extract the model_period+1 values we need
        retire_ben_term_est = np.zeros(len(years))
        aal_term_current = np.zeros(len(years))
        for i in range(len(years)):
            if i < len(full_stream):
                retire_ben_term_est[i] = full_stream[i]
            if i < len(full_aal):
                aal_term_current[i] = full_aal[i]
    else:
        # FRS method: growing annuity
        retire_ben_term = _get_pmt(dr, payroll_growth, amo_period, pvfb_term_current, t=1)

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
                       constants=None) -> pd.DataFrame:
    """
    Run the full pipeline for a single class: raw inputs → liability output.

    Returns a DataFrame matching R's liability.csv structure.
    """
    if constants is None:
        constants = load_frs_config()

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
    _compute_aal_totals(result)
    return result


def _sum_cols(df, pattern_parts, default=0.0):
    """Sum all columns matching f"aal_{component}_{bt}_{period}_est" patterns."""
    total = default
    for col in df.columns:
        for part in pattern_parts:
            if part in col:
                total = total + df[col]
                break
    return total


def _compute_aal_totals(result):
    """Compute aal_legacy_est, aal_new_est, total_aal_est, tot_ben_refund from
    whatever benefit-type columns are present. Works for any combination of DB/CB/DC."""
    # Legacy AAL = sum of aal_active_{bt}_legacy + aal_term_{bt}_legacy + aal_retire_{bt}_legacy
    #              + retire_current + term_current
    legacy_aal = 0.0
    new_aal = 0.0
    legacy_ben = 0.0
    new_ben = 0.0

    for col in result.columns:
        if col.startswith("aal_active_") and col.endswith("_legacy_est"):
            legacy_aal = legacy_aal + result[col]
        elif col.startswith("aal_active_") and col.endswith("_new_est"):
            new_aal = new_aal + result[col]
        elif col.startswith("aal_term_") and col.endswith("_legacy_est") and "current" not in col:
            legacy_aal = legacy_aal + result[col]
        elif col.startswith("aal_term_") and col.endswith("_new_est") and "current" not in col:
            new_aal = new_aal + result[col]
        elif col.startswith("aal_retire_") and col.endswith("_legacy_est") and "current" not in col:
            legacy_aal = legacy_aal + result[col]
        elif col.startswith("aal_retire_") and col.endswith("_new_est") and "current" not in col:
            new_aal = new_aal + result[col]
        elif col.startswith("refund_") and col.endswith("_legacy_est"):
            legacy_ben = legacy_ben + result[col]
        elif col.startswith("refund_") and col.endswith("_new_est"):
            new_ben = new_ben + result[col]
        elif col.startswith("retire_ben_") and col.endswith("_legacy_est") and "current" not in col:
            legacy_ben = legacy_ben + result[col]
        elif col.startswith("retire_ben_") and col.endswith("_new_est") and "current" not in col:
            new_ben = new_ben + result[col]

    # Current retiree and term vested (not benefit-type-specific)
    if "aal_retire_current_est" in result.columns:
        legacy_aal = legacy_aal + result["aal_retire_current_est"]
    if "aal_term_current_est" in result.columns:
        legacy_aal = legacy_aal + result["aal_term_current_est"]
    if "retire_ben_current_est" in result.columns:
        legacy_ben = legacy_ben + result["retire_ben_current_est"]
    if "retire_ben_term_est" in result.columns:
        legacy_ben = legacy_ben + result["retire_ben_term_est"]

    result["aal_legacy_est"] = legacy_aal
    result["aal_new_est"] = new_aal
    result["total_aal_est"] = legacy_aal + new_aal
    result["tot_ben_refund_legacy_est"] = legacy_ben
    result["tot_ben_refund_new_est"] = new_ben
    result["tot_ben_refund_est"] = legacy_ben + new_ben
    result["liability_gain_loss_legacy_est"] = 0.0
    result["liability_gain_loss_new_est"] = 0.0
    result["total_liability_gain_loss_est"] = 0.0


def _load_frs_inputs(class_name: str, sep_class: str,
                     baseline_dir: Path, constants) -> dict:
    """Load inputs for FRS from Excel + CSVs."""
    from pension_model.core.mortality_builder import (
        build_compact_mortality_from_excel, build_ann_factor_retire_table,
    )
    from pension_model.core.decrement_builder import (
        build_withdrawal_rate_table, build_retirement_rate_tables,
    )

    raw_dir = baseline_dir.parent / "R_model" / "R_model_frs"
    frs_inputs = raw_dir / "Florida FRS inputs.xlsx"
    extracted_inputs = raw_dir / "Reports" / "extracted inputs"

    cm = build_compact_mortality_from_excel(
        raw_dir / "pub-2010-headcount-mort-rates.xlsx",
        raw_dir / "mortality-improvement-scale-mp-2018-rates.xlsx",
        class_name,
        constants=constants,
    )
    afr = build_ann_factor_retire_table(
        cm, class_name, constants.ranges.start_year, constants.ranges.model_period,
        constants.economic.dr_current, constants.benefit.cola_current_retire,
    )
    term_rate_avg = build_withdrawal_rate_table(frs_inputs, sep_class, 70)
    ret_tables = build_retirement_rate_tables(frs_inputs, extracted_inputs, sep_class)

    return {
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
        "_compact_mortality": cm,
    }


def _load_txtrs_inputs(class_name: str, baseline_dir: Path, constants) -> dict:
    """Load inputs for TRS from Excel workbook + external mortality files."""
    from pension_model.core.mortality_builder import (
        build_compact_mortality_for_plan, build_ann_factor_retire_table,
    )
    from pension_model.core.txtrs_loader import build_txtrs_inputs

    raw_dir = baseline_dir.parent / "R_model" / "R_model_txtrs"

    # Get TRS-specific inputs (salary, headcount, separation rates, etc.)
    inputs = build_txtrs_inputs(raw_dir, constants)

    # Attach reduction tables to config for get_reduce_factor lookups
    if "_reduction_tables" in inputs:
        object.__setattr__(constants, "_reduce_tables", inputs["_reduction_tables"])

    # Build mortality from config-driven specification
    cm = build_compact_mortality_for_plan(constants, raw_dir, class_name)
    afr = build_ann_factor_retire_table(
        cm, class_name, constants.ranges.start_year, constants.ranges.model_period,
        constants.economic.dr_current, constants.benefit.cola_current_retire,
    )
    inputs["ann_factor_retire"] = afr
    inputs["_compact_mortality"] = cm

    return inputs


def run_class_pipeline_e2e(class_name: str, baseline_dir: Path,
                           constants=None,
                           on_stage=None,
                           no_new_entrants: bool = False) -> pd.DataFrame:
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
    if constants is None:
        constants = load_frs_config()

    tier_fn, _, _, sep_type_fn = _make_callables(constants)
    sep_class = (constants.get_sep_class(class_name) if isinstance(constants, PlanConfig)
                 else SEP_CLASS_MAP.get(class_name, class_name))

    # Use generic stage 3 loader if data directory exists, else fall back to legacy
    _use_stage3 = (isinstance(constants, PlanConfig)
                   and constants.resolve_data_dir().exists()
                   and (constants.resolve_data_dir() / "demographics").exists())

    if _use_stage3:
        from pension_model.core.data_loader import load_plan_data
        inputs = load_plan_data(class_name, sep_class, constants)
        # Attach reduction tables to config if provided (TRS early retirement)
        if "_reduction_tables" in inputs:
            object.__setattr__(constants, "_reduce_tables", inputs["_reduction_tables"])
    else:
        plan_name = constants.plan_name if hasattr(constants, "plan_name") else "frs"
        if plan_name == "txtrs":
            inputs = _load_txtrs_inputs(class_name, baseline_dir, constants)
        else:
            inputs = _load_frs_inputs(class_name, sep_class, baseline_dir, constants)

    # Build benefit tables
    if on_stage:
        on_stage("benefit_tables")
    tables = build_benefit_tables(class_name, inputs, constants, baseline_dir)

    # Derive benefit decisions from our benefit_val + final_benefit
    bvt = tables["benefit_val"]
    fbt = tables["final_benefit"]
    bvt_bd = bvt[["entry_year", "entry_age", "yos", "term_age", "tier_at_term_age"]].copy()
    bvt_bd["sep_type"] = bvt_bd["tier_at_term_age"].apply(sep_type_fn)
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
    if on_stage:
        on_stage("workforce")
    cm = inputs["_compact_mortality"]
    wf = project_workforce(
        initial_active, tables["separation_rate"], ben_decisions, cm,
        tables["entrant_profile"], class_name,
        constants.ranges.start_year, constants.ranges.model_period,
        constants.economic.pop_growth, constants.benefit.retire_refund_ratio,
        no_new_entrants=no_new_entrants,
        get_tier_fn=tier_fn)

    # Compute liability from projected workforce
    if on_stage:
        on_stage("liability")
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
    _compute_aal_totals(result)
    return result
