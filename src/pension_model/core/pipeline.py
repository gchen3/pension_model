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

import sys
from pathlib import Path
import numpy as np
import pandas as pd

from pension_model.plan_config import (
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
    build_benefit_table,
    build_final_benefit_table,
    build_benefit_val_table,
)


def _headcount_total(df: pd.DataFrame) -> float:
    """Sum total active headcount from either long- or wide-format headcount.

    Stage 3 data uses long format with an explicit ``count`` column. The
    cross-class sep-class lookups in ``build_plan_benefit_tables`` still read
    R-side wide-format CSVs from ``baseline_outputs/`` (one column per yos
    bucket, age in the first column); migrating those to stage 3 is
    tracked as a separate data-layout task.
    """
    if "count" in df.columns:
        return float(df["count"].sum())
    return float(df.iloc[:, 1:].sum().sum())


def compute_adjustment_ratio(class_name: str, headcount: pd.DataFrame,
                             constants, baseline_dir: Path) -> float:
    """Compute headcount adjustment ratio matching R model.

    For grouped classes (eco/eso/judges in FRS) the denominator is the sum
    across the group, read from the plan's stage 3 demographics directory.
    """
    if class_name in ("eco", "eso", "judges"):
        demo_dir = constants.resolve_data_dir() / "demographics"
        combined_raw = sum(
            _headcount_total(pd.read_csv(demo_dir / f"{c}_headcount.csv"))
            for c in ("eco", "eso", "judges")
        )
        return 2075 / combined_raw  # eco_eso_judges_total_active_member_
    return constants.class_data[class_name].total_active_member / _headcount_total(headcount)


def _make_callables(constants, class_name=None):
    """Create tier/benefit callables from a PlanConfig."""
    return (
        lambda cn, ey, age, yos, ny=None, **kw: pc_get_tier(constants, cn, ey, age, yos),
        lambda cn, tier, da, yos, dy=0: pc_get_ben_mult(constants, cn, tier, da, yos, dy),
        lambda cn, tier, da, yos=0, ey=0: pc_get_reduce_factor(constants, cn, tier, da, yos, ey),
        pc_get_sep_type,
    )


def build_plan_benefit_tables(
    inputs_by_class: dict,
    constants,
    baseline_dir: Path,
) -> dict:
    """Build every benefit table the plan needs in a single stacked pass.

    Replaces the per-class build_benefit_tables that was called in a 7x
    loop. All heavy work (ann_factor / benefit / final_benefit /
    benefit_val) is executed once across all classes via the
    stacked-capable builders, amortizing fixed pandas overhead and
    enabling natural cross-class deduplication.

    The per-class prelude (salary_headcount, entrant_profile,
    salary_benefit, separation_rate) still runs in a loop because each
    class's inputs are inherently per-class DataFrames, but the
    individual builders are fast and the outputs are stacked
    immediately via pd.concat.

    Each class owns its own decrement files, so separation_rate is built
    once per class (no sep_class indirection).

    Args:
        inputs_by_class: dict {class_name: inputs dict from load_plan_data}.
        constants: PlanConfig.
        baseline_dir: Baseline directory (for compute_adjustment_ratio).

    Returns:
        Dict of stacked DataFrames keyed by:
          salary_headcount, entrant_profile, salary_benefit,
          separation_rate, ann_factor, benefit, final_benefit, benefit_val.
        Every frame carries class_name.
    """
    from pension_model.core.benefit_tables import build_ann_factor_table

    classes = list(constants.classes)

    # Plan-wide CB flag — if any class in the plan uses CB, we compute ICR.
    has_cb = (hasattr(constants, "benefit_types")
              and "cb" in constants.benefit_types
              and getattr(constants, "cash_balance", None) is not None)

    cm_by_class = {cn: inputs_by_class[cn]["_compact_mortality"] for cn in classes}
    expected_icr_by_class: dict = {}

    sh_frames: list = []
    ep_frames: list = []
    sbt_frames: list = []
    sep_frames: list = []

    for cn in classes:
        inputs = inputs_by_class[cn]

        adj_ratio = compute_adjustment_ratio(
            cn, inputs["headcount"], constants, baseline_dir,
        )

        # Per-class ICR (only for CB plans)
        actual_icr_series = None
        if has_cb:
            from pension_model.core.icr import (
                compute_expected_icr, compute_actual_icr_series,
            )
            cb = constants.cash_balance
            expected_icr = compute_expected_icr(
                constants.model_return, cb.get("return_volatility", 0.12),
                cb["icr_smooth_period"], cb["icr_floor"], cb["icr_cap"],
                cb["icr_upside_share"],
            )
            expected_icr_by_class[cn] = expected_icr
            years = range(constants.min_entry_year, constants.max_year + 1)
            ret_scenario = inputs.get("_return_scenario")
            if ret_scenario is None:
                ret_scenario = pd.Series(constants.model_return, index=list(years))
            actual_icr_series = compute_actual_icr_series(
                years, constants.start_year, ret_scenario,
                cb["icr_smooth_period"], cb["icr_floor"], cb["icr_cap"],
                cb["icr_upside_share"],
            )

        # Step 1: salary/headcount
        sh = build_salary_headcount_table(
            inputs["salary"], inputs["headcount"], inputs["salary_growth"],
            cn, adj_ratio, constants.ranges.start_year, constants=constants,
        )

        # Entrant profile: from explicit input (TRS Excel sheet) or derived
        if "_entrant_profile" in inputs:
            ep = inputs["_entrant_profile"].copy()
        else:
            ep = build_entrant_profile(sh)
        ep_tagged = ep.copy()
        ep_tagged["class_name"] = cn

        # Step 2: salary/benefit
        sbt = build_salary_benefit_table(
            sh, ep, inputs["salary_growth"], cn, constants,
            actual_icr_series=actual_icr_series,
        )

        # Step 3: separation rate — each class owns its own decrement data
        if "_separation_rate" in inputs:
            sep = inputs["_separation_rate"]
        else:
            sep = build_separation_rate_table(
                inputs["term_rate_avg"], inputs["normal_retire_tier1"],
                inputs["normal_retire_tier2"], inputs["early_retire_tier1"],
                inputs["early_retire_tier2"], ep, cn, constants,
            )

        sh_frames.append(sh)
        ep_frames.append(ep_tagged)
        sbt_frames.append(sbt)
        sep_frames.append(sep)

    salary_headcount = pd.concat(sh_frames, ignore_index=True)
    entrant_profile = pd.concat(ep_frames, ignore_index=True)
    salary_benefit = pd.concat(sbt_frames, ignore_index=True)
    separation_rate = pd.concat(sep_frames, ignore_index=True)

    # Convert class_name to pandas Categorical across every plan-wide frame.
    # Downstream pandas groupby / merge / sort operations hash and compare
    # categorical int codes rather than Python str objects, which is
    # materially faster on the large stacked frames.
    class_cat = pd.CategoricalDtype(categories=list(classes))
    salary_headcount["class_name"] = salary_headcount["class_name"].astype(class_cat)
    entrant_profile["class_name"] = entrant_profile["class_name"].astype(class_cat)
    salary_benefit["class_name"] = salary_benefit["class_name"].astype(class_cat)
    separation_rate["class_name"] = separation_rate["class_name"].astype(class_cat)

    # --- Stacked builders: one call each, spanning every class at once ---
    ann_factor = build_ann_factor_table(
        salary_benefit_table=salary_benefit,
        compact_mortality_by_class=cm_by_class,
        constants=constants,
        expected_icr_by_class=expected_icr_by_class or None,
    )
    benefit = build_benefit_table(ann_factor, salary_benefit, constants)
    final_benefit = build_final_benefit_table(
        benefit, use_earliest_retire=constants.use_earliest_retire,
    )

    # build_benefit_val_table takes a scalar expected_icr. Multi-class CB
    # is not currently supported (TRS has only one class "all"); when the
    # plan has exactly one CB class, pass its ICR. For FRS (no CB), None.
    if expected_icr_by_class:
        scalar_icr = next(iter(expected_icr_by_class.values()))
    else:
        scalar_icr = None
    benefit_val = build_benefit_val_table(
        salary_benefit, final_benefit, separation_rate, constants,
        expected_icr=scalar_icr, ann_factor_table=ann_factor,
    )

    return {
        "salary_headcount": salary_headcount,
        "entrant_profile": entrant_profile,
        "salary_benefit": salary_benefit,
        "separation_rate": separation_rate,
        "ann_factor": ann_factor,
        "benefit": benefit,
        "final_benefit": final_benefit,
        "benefit_val": benefit_val,
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
    """Get design ratios and benefit types from a PlanConfig."""
    return constants.get_design_ratios(class_name), list(constants.benefit_types)


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

    tv_method = constants.term_vested_method

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


def _project_and_aggregate_class(
    class_name: str,
    class_tables: dict,
    class_inputs: dict,
    constants,
    *,
    no_new_entrants: bool = False,
    on_stage=None,
) -> pd.DataFrame:
    """Per-class workforce projection + liability aggregation.

    Takes pre-built benefit tables (already sliced to this class from the
    plan-wide stacked frames) plus the class's raw inputs (needed for
    CompactMortality and current-retiree projection), and returns the
    class liability DataFrame. Internal helper — callers go through
    run_plan_pipeline.
    """
    from pension_model.core.workforce import project_workforce

    _, _, _, sep_type_fn = _make_callables(constants)

    bvt = class_tables["benefit_val"]
    fbt = class_tables["final_benefit"]
    bvt_bd = bvt[["entry_year", "entry_age", "yos", "term_age",
                  "tier_at_term_age"]].copy()
    bvt_bd["sep_type"] = bvt_bd["tier_at_term_age"].apply(sep_type_fn)
    bvt_bd["ben_decision"] = bvt_bd["sep_type"].map(
        {"retire": "retire", "vested": "mix", "non_vested": "refund"})
    bvt_bd.loc[bvt_bd["yos"] == 0, "ben_decision"] = np.nan
    ben_decisions = bvt_bd.merge(
        fbt[["entry_year", "entry_age", "term_age", "dist_age"]].drop_duplicates(),
        on=["entry_year", "entry_age", "term_age"], how="left",
    )
    ben_decisions["dist_age"] = ben_decisions["dist_age"].fillna(
        ben_decisions["term_age"]).astype(int)
    ben_decisions = ben_decisions[ben_decisions["ben_decision"].notna()]

    # Initial active population from this class's salary_headcount
    sh = class_tables["salary_headcount"]
    valid_entry_ages = set(class_tables["entrant_profile"]["entry_age"].values)
    initial_active = sh[sh["entry_age"].isin(valid_entry_ages)][
        ["entry_age", "age", "count"]].rename(columns={"count": "n_active"}).copy()
    initial_active = initial_active[initial_active["n_active"] > 0]

    if on_stage:
        on_stage("workforce")
    cm = class_inputs["_compact_mortality"]
    wf = project_workforce(
        initial_active, class_tables["separation_rate"], ben_decisions, cm,
        class_tables["entrant_profile"], class_name,
        constants.ranges.start_year, constants.ranges.model_period,
        constants.economic.pop_growth, constants.benefit.retire_refund_ratio,
        no_new_entrants=no_new_entrants,
        constants=constants,
    )

    if on_stage:
        on_stage("liability")
    active = compute_active_liability(
        wf["wf_active"], class_tables["benefit_val"], class_name, constants)
    term = compute_term_liability(
        wf["wf_term"], class_tables["benefit_val"], class_tables["benefit"],
        class_name, constants)
    refund = compute_refund_liability(
        wf["wf_refund"], class_tables["benefit"], class_name, constants)
    retire = compute_retire_liability(
        wf["wf_retire"], class_tables["benefit"], class_tables["ann_factor"],
        class_name, constants)

    cd = constants.class_data[class_name]
    ben_payment = cd.outflow * constants.ben_payment_ratio
    retire_current = compute_current_retiree_liability(
        class_inputs["ann_factor_retire"], class_inputs["retiree_distribution"],
        cd.retiree_pop, ben_payment, constants)
    term_current = compute_current_term_vested_liability(class_name, constants)

    years = pd.DataFrame({"year": range(
        constants.ranges.start_year,
        constants.ranges.start_year + constants.ranges.model_period + 1,
    )})
    result = years.merge(active, on="year", how="left")
    result = result.merge(term, on="year", how="left")
    result = result.merge(refund, on="year", how="left")
    result = result.merge(retire, on="year", how="left")
    result = result.merge(retire_current, on="year", how="left")
    result = result.merge(term_current, on="year", how="left")
    result = result.fillna(0)
    _compute_aal_totals(result)
    return result


def _split_plan_tables_by_class(plan_tables: dict, classes: list) -> dict:
    """Split plan-wide stacked tables into per-class views in one pass each.

    Returns {class_name: {table_name: DataFrame}}.

    Uses dict(tuple(df.groupby("class_name"))) which does a single O(n) pass
    per frame instead of N full-frame boolean-index scans. Every frame,
    including separation_rate, is keyed by class_name — there is no
    sep_class indirection.

    The class_name column is stripped from the sliced frames; inside the
    per-class projection step it is redundant (every row has the same
    value) and it measurably slows downstream .iterrows() calls in
    project_workforce.
    """
    by_table_then_class: dict = {}
    for name, df in plan_tables.items():
        if "class_name" in df.columns:
            groups = dict(tuple(df.groupby("class_name", sort=False)))
            by_table_then_class[name] = {
                cn: g.drop(columns=["class_name"]).reset_index(drop=True)
                for cn, g in groups.items()
            }
        else:
            by_table_then_class[name] = {cn: df for cn in classes}

    result: dict = {}
    for cn in classes:
        result[cn] = {name: slices.get(cn)
                      for name, slices in by_table_then_class.items()}
    return result


def run_plan_pipeline(
    constants,
    baseline_dir: Path,
    *,
    no_new_entrants: bool = False,
    on_stage=None,
    progress: bool = False,
) -> dict:
    """End-to-end pipeline for an entire plan: stage 3 data → per-class liability.

    Loads inputs once per class, builds every benefit table in a single
    plan-wide stacked call via build_plan_benefit_tables, then loops the
    classes to project workforce and aggregate liabilities (which
    currently still run per-class because project_workforce uses numpy
    matrices sized per class).

    Args:
        constants: PlanConfig.
        baseline_dir: Baseline data directory.
        no_new_entrants: Rundown mode — no new hires projected.
        on_stage: Optional callback(stage_name: str) for progress reporting.
        progress: If True, print percent-done progress to stdout.

    Returns:
        Dict {class_name: liability DataFrame} — one entry per class in
        constants.classes, matching the old run_class_pipeline_e2e output
        shape per class.
    """
    from pension_model.core.data_loader import load_plan_inputs

    classes = list(constants.classes)

    # Load raw inputs for all classes; attaches reduction tables to config
    inputs_by_class = load_plan_inputs(constants)

    if on_stage:
        on_stage("benefit_tables")
    plan_tables = build_plan_benefit_tables(inputs_by_class, constants, baseline_dir)

    # Split stacked tables into per-class views once (single groupby pass
    # per frame) instead of re-scanning inside the per-class loop.
    class_tables_by_name = _split_plan_tables_by_class(plan_tables, classes)

    liability = {}
    n = len(classes)
    for i, cn in enumerate(classes):
        if progress:
            pct = int(i / n * 100)
            sys.stdout.write(f"\r    {pct:3d}%")
            sys.stdout.flush()
        liability[cn] = _project_and_aggregate_class(
            cn, class_tables_by_name[cn], inputs_by_class[cn], constants,
            no_new_entrants=no_new_entrants, on_stage=on_stage,
        )
    if progress:
        sys.stdout.write(f"\r    100% done\n")
        sys.stdout.flush()

    return liability
