"""
Benefit table construction from raw inputs.

Builds the chain of actuarial tables needed for liability computation:
  salary_headcount → salary_benefit → ann_factor → benefit → benefit_val

Each function takes raw/intermediate DataFrames and returns the next table.
All are pure functions (no side effects, no global state).

Design for generalization:
  - Plan-specific rules (benefit multiplier, tier logic) passed as callables
  - Core actuarial computations (cumulative survival, annuity factors) are generic
  - DataFrames use consistent column naming across all plans
"""

import numpy as np
import pandas as pd

# Map class names to salary growth column names (R uses "special_risk" not "special")
SALARY_GROWTH_COL_MAP = {
    "regular": "salary_increase_regular",
    "special": "salary_increase_special_risk",
    "admin": "salary_increase_admin",
    "eco": "salary_increase_eco",
    "eso": "salary_increase_eso",
    "judges": "salary_increase_judges",
    "senior_management": "salary_increase_senior_management",
}


def _get_salary_growth_col(class_name: str, constants=None) -> str:
    """Resolve salary growth column name for a class.

    Uses config map if constants is a PlanConfig, else falls back to hardcoded FRS map.
    """
    from pension_model.plan_config import PlanConfig
    if isinstance(constants, PlanConfig):
        col_map = constants.salary_growth_col_map
        if col_map:
            return col_map.get(class_name, f"salary_increase_{class_name}")
    return SALARY_GROWTH_COL_MAP.get(class_name, f"salary_increase_{class_name}")


# ---------------------------------------------------------------------------
# 1. Salary / headcount table construction
# ---------------------------------------------------------------------------

def _is_long_format(df: pd.DataFrame, value_col: str) -> bool:
    """Check if a DataFrame is already in long format (age, yos, value)."""
    return {"age", "yos", value_col}.issubset(df.columns)


def build_salary_headcount_table(
    salary_wide: pd.DataFrame,
    headcount_wide: pd.DataFrame,
    salary_growth: pd.DataFrame,
    class_name: str,
    adjustment_ratio: float,
    start_year: int,
    constants=None,
) -> pd.DataFrame:
    """
    Build long-format salary/headcount table with entry_salary.

    Accepts salary/headcount in either format:
      - Wide: age column + YOS columns (legacy, melted internally)
      - Long: age, yos, salary/count columns (stage 3 format, used directly)

    Args:
        salary_wide: Salary data (wide or long format).
        headcount_wide: Headcount data (wide or long format).
        salary_growth: Table with 'yos' and salary growth column.
        class_name: Membership class name.
        adjustment_ratio: Headcount scaling factor (total_active / raw_count).
        start_year: Valuation year.

    Returns:
        Long-format DataFrame: entry_year, entry_age, age, yos, count, entry_salary
    """
    # Resolve salary growth column name
    if "salary_increase" in salary_growth.columns:
        growth_col = "salary_increase"
    else:
        growth_col = _get_salary_growth_col(class_name, constants)

    # Build cumulative salary growth: extend to full yos range, then cumprod
    # R extends the table with fill-forward before computing cumprod (benefit model lines 6-9)
    sg = salary_growth[["yos", growth_col]].copy()
    sg = sg.rename(columns={growth_col: "salary_increase"})

    # Extend to cover all possible yos values (up to max yos in headcount)
    max_possible_yos = 102  # max_age - min_age
    if sg["yos"].max() < max_possible_yos:
        extra = pd.DataFrame({"yos": range(sg["yos"].max() + 1, max_possible_yos + 1)})
        sg = pd.concat([sg, extra], ignore_index=True)
        sg["salary_increase"] = sg["salary_increase"].ffill()

    # cumprod(1 + lag(increase, default=0))
    lagged = np.insert(sg["salary_increase"].values[:-1], 0, 0.0)
    sg["cumprod_salary_increase"] = np.cumprod(1 + lagged)

    # Accept long or wide format for salary
    if _is_long_format(salary_wide, "salary"):
        sal_long = salary_wide[["age", "yos", "salary"]].copy()
    else:
        sal_long = salary_wide.melt(id_vars="age", var_name="yos", value_name="salary")
        sal_long["yos"] = sal_long["yos"].astype(float).astype(int)

    # Accept long or wide format for headcount
    if _is_long_format(headcount_wide, "count"):
        hc_long = headcount_wide[["age", "yos", "count"]].copy()
    else:
        hc_long = headcount_wide.melt(id_vars="age", var_name="yos", value_name="count")
        hc_long["yos"] = hc_long["yos"].astype(float).astype(int)

    # Adjust headcount using pre-computed ratio
    hc_long["count"] = hc_long["count"] * adjustment_ratio

    # Join salary and headcount
    merged = sal_long.merge(hc_long, on=["age", "yos"], how="left")
    merged["start_year"] = start_year
    merged["entry_age"] = merged["age"] - merged["yos"]
    merged["entry_year"] = start_year - merged["yos"]

    # Filter valid rows
    merged = merged[merged["salary"].notna() & (merged["entry_age"] >= 18)].copy()

    # Join salary growth to get cumulative factor, compute entry_salary
    merged = merged.merge(sg[["yos", "cumprod_salary_increase"]], on="yos", how="left")
    merged["entry_salary"] = merged["salary"] / merged["cumprod_salary_increase"]

    result = merged[["entry_year", "entry_age", "age", "yos", "count", "entry_salary"]].reset_index(drop=True)
    result["class_name"] = class_name
    return result


def build_entrant_profile(salary_headcount: pd.DataFrame) -> pd.DataFrame:
    """
    Extract entrant profile from the most recent entry year cohort.

    Args:
        salary_headcount: Output of build_salary_headcount_table().

    Returns:
        DataFrame: entry_age, start_sal, entrant_dist
    """
    max_year = salary_headcount["entry_year"].max()
    recent = salary_headcount[salary_headcount["entry_year"] == max_year].copy()
    total = recent["count"].sum()
    recent["entrant_dist"] = recent["count"] / total
    return recent[["entry_age", "entry_salary"]].rename(
        columns={"entry_salary": "start_sal"}
    ).assign(entrant_dist=recent["entrant_dist"].values).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. Salary / benefit table (per cohort: salary, FAS, db_ee_balance)
# ---------------------------------------------------------------------------

def _rolling_mean_lagged(arr: np.ndarray, window: int) -> np.ndarray:
    """
    Lagged rolling mean matching R's baseR.rollmean.

    FAS at yos=t = mean(salary[t-window : t]), i.e., the previous `window`
    values NOT including the current period. R lags the window by 1.
    For early periods with < window prior values, uses what's available.
    Returns NaN when no prior values exist (yos=0).
    """
    n = len(arr)
    result = np.full(n, np.nan)
    for i in range(1, n):
        start = max(0, i - window)
        result[i] = arr[start:i].mean()
    return result


def _cum_fv(interest_rate: float, contributions: np.ndarray) -> np.ndarray:
    """
    Cumulative future value of contributions.

    Replicates R's get_cum_fv(interest, cashflow, first_value=0):
      cumvalue[0] = 0 (no balance at entry)
      cumvalue[i] = cumvalue[i-1] * (1+interest) + cashflow[i-1]
    The contribution at period i is credited at the END of period i,
    so balance[i] reflects contributions through period i-1.
    """
    n = len(contributions)
    balance = np.zeros(n)
    # balance[0] = 0 (default)
    for i in range(1, n):
        balance[i] = balance[i - 1] * (1 + interest_rate) + contributions[i - 1]
    return balance


def _cum_fv_vec(interest_vec: np.ndarray, contributions: np.ndarray,
                first_value: float = 0.0) -> np.ndarray:
    """
    Cumulative future value with time-varying interest rates.

    Replicates R's cumFV2(interest_vec, cashflow, first_value=0):
      balance[0] = first_value
      balance[i] = balance[i-1] * (1 + interest_vec[i]) + contributions[i-1]

    Used for cash balance account accumulation where the crediting rate
    varies by year (actual ICR).
    """
    n = len(contributions)
    balance = np.zeros(n)
    balance[0] = first_value
    for i in range(1, n):
        balance[i] = balance[i - 1] * (1 + interest_vec[i]) + contributions[i - 1]
    return balance


def build_salary_benefit_table(
    salary_headcount: pd.DataFrame,
    entrant_profile: pd.DataFrame,
    salary_growth: pd.DataFrame,
    class_name: str,
    constants,
    actual_icr_series: "Optional[pd.Series]" = None,
) -> pd.DataFrame:
    """
    Build the salary/benefit table for all cohorts.

    For each (entry_year, entry_age, yos): salary, FAS, db_ee_balance,
    and when cash balance is active: cb_ee_balance, cb_er_balance, cb_balance.

    Tier at term_age is resolved via the vectorized resolve_tiers_vec.

    Args:
        salary_headcount: Output of build_salary_headcount_table().
        entrant_profile: Output of build_entrant_profile().
        salary_growth: Salary growth table with yos and class column.
        class_name: Membership class name.
        constants: PlanConfig.
        actual_icr_series: Year→ICR series for CB accumulation (None if no CB).

    Returns:
        DataFrame: entry_year, entry_age, yos, term_age, tier_at_term_age,
                   salary, fas, db_ee_balance, cumprod_salary_increase,
                   [cb_ee_cont, cb_er_cont, cb_ee_balance, cb_er_balance, cb_balance]
    """
    from pension_model.plan_config import resolve_tiers_vec

    r = constants.ranges
    econ = constants.economic
    ben = constants.benefit

    # Salary growth for this class: extend to full yos range, then cumprod
    if "salary_increase" in salary_growth.columns:
        growth_col = "salary_increase"
    else:
        growth_col = _get_salary_growth_col(class_name, constants)
    sg = salary_growth[["yos", growth_col]].copy()
    sg = sg.rename(columns={growth_col: "salary_increase"})

    # R extends the table: fill forward to max yos (line 7-8 of benefit model)
    max_yos = r.max_yos
    if sg["yos"].max() < max_yos:
        extra = pd.DataFrame({"yos": range(sg["yos"].max() + 1, max_yos + 1)})
        sg = pd.concat([sg, extra], ignore_index=True)
        sg["salary_increase"] = sg["salary_increase"].ffill()

    # cumprod(1 + lag(increase, default=0))
    lagged = np.insert(sg["salary_increase"].values[:-1], 0, 0.0)
    sg["cumprod_salary_increase"] = np.cumprod(1 + lagged)

    entry_ages = np.asarray(entrant_profile["entry_age"].values, dtype=np.int64)

    # Vectorized cross product (entry_year, entry_age, yos) → filter term_age <= max_age
    ey_axis = np.arange(r.entry_year_range.start, r.entry_year_range.stop,
                        dtype=np.int64)
    yos_axis = np.arange(0, max_yos + 1, dtype=np.int64)
    mg_ey, mg_ea, mg_yos = np.meshgrid(ey_axis, entry_ages, yos_axis, indexing="ij")
    ey_flat = mg_ey.ravel()
    ea_flat = mg_ea.ravel()
    yos_flat = mg_yos.ravel()
    term_age_flat = ea_flat + yos_flat
    keep = term_age_flat <= r.max_age
    ey_flat = ey_flat[keep]
    ea_flat = ea_flat[keep]
    yos_flat = yos_flat[keep]
    term_age_flat = term_age_flat[keep]

    df = pd.DataFrame({
        "entry_year": ey_flat,
        "entry_age": ea_flat,
        "yos": yos_flat,
        "term_age": term_age_flat,
    })

    # Vectorized tier at term_age (resolve_tiers_vec takes (class, ey, age, yos))
    cn_arr = np.full(len(df), class_name, dtype=object)
    df["tier_at_term_age"] = resolve_tiers_vec(
        constants, cn_arr, ey_flat, term_age_flat, yos_flat,
    )

    # Join entrant profile for start_sal
    df = df.merge(entrant_profile[["entry_age", "start_sal"]], on="entry_age", how="left")

    # Join salary growth
    sg_sub = sg[sg["yos"] <= max_yos][["yos", "cumprod_salary_increase"]].copy()
    df = df.merge(sg_sub, on="yos", how="left")

    # Join historical entry_salary from salary_headcount
    sh_entry = salary_headcount[["entry_year", "entry_age", "entry_salary"]].drop_duplicates()
    df = df.merge(sh_entry, on=["entry_year", "entry_age"], how="left")

    # Compute salary
    # For historical cohorts (entry_year <= max_hist_year): salary from headcount data.
    # For future cohorts: salary from entrant profile, escalated by payroll growth.
    # max_hist_year defaults to the latest entry year in salary_headcount data,
    # but can be overridden to start_year when entrant profile salaries are already
    # at start_year level (e.g., TRS where entrant profile is read from Excel).
    max_hist_year = salary_headcount["entry_year"].max()
    if constants.plan_name != "frs":
        max_hist_year = max(max_hist_year, constants.ranges.start_year)
    df["salary"] = np.where(
        df["entry_year"] <= max_hist_year,
        df["entry_salary"] * df["cumprod_salary_increase"],
        df["start_sal"] * df["cumprod_salary_increase"]
        * (1 + econ.payroll_growth) ** (df["entry_year"] - max_hist_year),
    )

    # FAS period: config-driven from tier definition
    tier_bases = df["tier_at_term_age"].str.extract(r"^(\w+)$|^(\w+_\w+)")[1].fillna(
        df["tier_at_term_age"].str.extract(r"^(\w+_\w+)_")[0]
    ).fillna(df["tier_at_term_age"])
    df["fas_period"] = tier_bases.map(
        lambda t: constants.get_fas_years(t) if pd.notna(t) else constants.fas_years_default
    ).astype(int)

    # Drop rows with NaN salary (entry_age not in profile)
    df = df[df["salary"].notna()].copy()

    # Compute FAS and db_ee_balance within each (entry_year, entry_age) group.
    # FAS = lagged rolling mean of salary (window = fas_period, NOT including current)
    # db_ee_balance = cumulative contributions with lag (balance[0]=0, balance[i]=sum of contribs[0..i-1])
    df = df.sort_values(["entry_year", "entry_age", "yos"]).reset_index(drop=True)
    grp_keys = ["entry_year", "entry_age"]
    g = df.groupby(grp_keys)

    # FAS: R's baseR.rollmean computes mean of PREVIOUS fas_period values (lagged)
    # Use the first fas_period in each group (R does same)
    first_fas = g["fas_period"].transform("first").astype(int)

    # Compute FAS using rolling on shifted salary within groups
    sal_shifted = g["salary"].shift(1)
    df["fas"] = np.nan
    for fp in df["fas_period"].unique():
        mask = first_fas == fp
        if mask.any():
            rolled = sal_shifted.where(mask).groupby([df.loc[mask, c] for c in grp_keys]).rolling(fp, min_periods=1).mean()
            df.loc[rolled.index.get_level_values(-1), "fas"] = rolled.values

    # db_ee_balance: cumsum of lagged contributions with interest
    db_ee_interest = getattr(ben, "db_ee_interest_rate", 0.0)
    df["_contrib"] = ben.db_ee_cont_rate * df["salary"]
    if db_ee_interest == 0.0:
        # Optimization: simple cumsum when no interest
        contrib_shifted = df.groupby(grp_keys)["_contrib"].shift(1, fill_value=0)
        df["db_ee_balance"] = contrib_shifted.groupby([df[c] for c in grp_keys]).cumsum()
    else:
        # Use _cum_fv with interest (e.g., TRS db_ee_interest_rate=0.02)
        balances = []
        for _, group in df.groupby(grp_keys):
            group = group.sort_values("yos")
            group["db_ee_balance"] = _cum_fv(db_ee_interest, group["_contrib"].values)
            balances.append(group)
        df = pd.concat(balances, ignore_index=True)
    df = df.drop(columns=["_contrib"])

    # --- Cash balance columns (when CB benefit type is active) ---
    has_cb = hasattr(constants, "benefit_types") and "cb" in constants.benefit_types
    cb_cfg = getattr(constants, "cash_balance", None) if has_cb else None
    if cb_cfg is not None and actual_icr_series is not None:
        ee_credit = cb_cfg["ee_pay_credit"]
        er_credit = cb_cfg["er_pay_credit"]
        cb_vesting = cb_cfg.get("vesting_yos", 5)

        df["cb_ee_cont"] = ee_credit * df["salary"]
        df["cb_er_cont"] = er_credit * df["salary"]
        # Map calendar year for each row: year = entry_year + yos
        df["_cal_year"] = df["entry_year"] + df["yos"]

        def _apply_cb_balance(group):
            group = group.sort_values("yos")
            cal_years = group["_cal_year"].values
            # Look up actual ICR for each calendar year
            icr_vals = np.array([actual_icr_series.get(int(y), 0.04)
                                 for y in cal_years])
            group["cb_ee_balance"] = _cum_fv_vec(icr_vals, group["cb_ee_cont"].values)
            group["cb_er_balance"] = _cum_fv_vec(icr_vals, group["cb_er_cont"].values)
            group["cb_balance"] = group["cb_ee_balance"] + np.where(
                group["yos"].values >= cb_vesting, group["cb_er_balance"], 0.0)
            return group

        cb_parts = []
        for _, group in df.groupby(grp_keys):
            cb_parts.append(_apply_cb_balance(group))
        df = pd.concat(cb_parts, ignore_index=True)
        df = df.drop(columns=["_cal_year"])
    # --- End CB columns ---

    df = df[df["salary"].notna()].copy()

    out_cols = ["entry_year", "entry_age", "yos", "term_age", "tier_at_term_age",
                "salary", "fas", "db_ee_balance", "cumprod_salary_increase"]
    # Include CB columns if they were computed
    for col in ["cb_ee_cont", "cb_er_cont", "cb_ee_balance", "cb_er_balance", "cb_balance"]:
        if col in df.columns:
            out_cols.append(col)

    result = df[out_cols].reset_index(drop=True)
    result["class_name"] = class_name
    return result


# ---------------------------------------------------------------------------
# 2b. Separation rate table (withdrawal + retirement by tier)
# ---------------------------------------------------------------------------

def build_separation_rate_table(
    term_rate_avg: pd.DataFrame,
    normal_retire_rate_tier1: pd.DataFrame,
    normal_retire_rate_tier2: pd.DataFrame,
    early_retire_rate_tier1: pd.DataFrame,
    early_retire_rate_tier2: pd.DataFrame,
    entrant_profile: pd.DataFrame,
    class_name: str,
    constants,
) -> pd.DataFrame:
    """
    Build separation rate table combining withdrawal and retirement rates.

    Replicates R's get_separation_table() (benefit model lines 522-582).
    Tier at term_age is resolved via the vectorized resolve_tiers_vec in one
    pass over the full grid.

    Args:
        term_rate_avg: Gender-averaged withdrawal rates (yos × age_group).
        normal_retire_rate_tier1/2: Normal retirement rates by age.
        early_retire_rate_tier1/2: Early retirement rates by age.
        entrant_profile: Entrant profile with entry_age column.
        class_name: Membership class name.
        constants: PlanConfig.

    Returns:
        DataFrame: entry_year, entry_age, term_age, yos, term_year,
                   separation_rate, remaining_prob, separation_prob, class_name
    """
    from pension_model.plan_config import resolve_tiers_vec

    r = constants.ranges

    # Age group breaks and labels matching R's cut()
    breaks = [-np.inf, 24, 29, 34, 44, 54, np.inf]
    labels = list(term_rate_avg.columns[1:])  # age group column names

    # Pivot term rates to long format
    term_long = term_rate_avg.melt(id_vars="yos", var_name="age_group", value_name="term_rate")

    entry_ages = set(int(ea) for ea in entrant_profile["entry_age"].values)

    # Vectorized expand_grid: (entry_year, term_age, yos) × filter entry_age in set
    ey_axis = np.arange(r.entry_year_range.start, r.entry_year_range.stop,
                        dtype=np.int64)
    ta_axis = np.arange(r.age_range.start, r.age_range.stop, dtype=np.int64)
    yos_axis = np.arange(r.yos_range.start, r.yos_range.stop, dtype=np.int64)
    mg_ey, mg_ta, mg_yos = np.meshgrid(ey_axis, ta_axis, yos_axis, indexing="ij")
    ey_flat = mg_ey.ravel()
    ta_flat = mg_ta.ravel()
    yos_flat = mg_yos.ravel()
    ea_flat = ta_flat - yos_flat
    # Filter: entry_age must be in the entrant profile
    valid_ea = np.array(sorted(entry_ages), dtype=np.int64)
    keep = np.isin(ea_flat, valid_ea)
    ey_flat = ey_flat[keep]
    ta_flat = ta_flat[keep]
    yos_flat = yos_flat[keep]
    ea_flat = ea_flat[keep]
    term_year_flat = ey_flat + yos_flat

    df = pd.DataFrame({
        "entry_year": ey_flat,
        "term_age": ta_flat,
        "yos": yos_flat,
        "entry_age": ea_flat,
        "term_year": term_year_flat,
    })

    # Assign age groups using pd.cut (matching R's cut())
    df["age_group"] = pd.cut(df["term_age"], bins=breaks, labels=labels, right=True)
    df["age_group"] = df["age_group"].astype(str)

    df = df.sort_values(["entry_year", "entry_age", "term_age"]).reset_index(drop=True)

    # Join withdrawal rates
    df = df.merge(term_long, on=["yos", "age_group"], how="left")

    # Join retirement rates by term_age — rename the source "age" column
    # to "_ret_age" to avoid left/right collision on the join.
    for tbl, col_name in [
        (normal_retire_rate_tier1, "normal_retire_rate_tier_1"),
        (normal_retire_rate_tier2, "normal_retire_rate_tier_2"),
        (early_retire_rate_tier1, "early_retire_rate_tier_1"),
        (early_retire_rate_tier2, "early_retire_rate_tier_2"),
    ]:
        rate_col = [c for c in tbl.columns if c != "age"][0]
        sub = tbl[["age", rate_col]].rename(
            columns={"age": "_ret_age", rate_col: col_name}
        )
        df = df.merge(sub, left_on="term_age", right_on="_ret_age", how="left")
        df = df.drop(columns=["_ret_age"])

    # Fill retirement rates within each (entry_year, entry_age) group
    df = df.sort_values(["entry_year", "entry_age", "term_age"])
    retire_cols = [c for c in df.columns if "retire_rate" in c]
    df[retire_cols] = df.groupby(["entry_year", "entry_age"])[retire_cols].transform(
        lambda x: x.ffill().bfill()
    )

    # Vectorized tier at term_age
    n = len(df)
    cn_arr = np.full(n, class_name, dtype=object)
    df["tier_at_term_age"] = resolve_tiers_vec(
        constants,
        cn_arr,
        df["entry_year"].values.astype(np.int64),
        df["term_age"].values.astype(np.int64),
        df["yos"].values.astype(np.int64),
    )

    # Separation rate depends on tier
    tier = df["tier_at_term_age"]
    df["separation_rate"] = np.where(
        tier.isin(["tier_3_norm", "tier_2_norm"]), df["normal_retire_rate_tier_2"],
        np.where(
            tier.isin(["tier_3_early", "tier_2_early"]), df["early_retire_rate_tier_2"],
            np.where(
                tier == "tier_1_norm", df["normal_retire_rate_tier_1"],
                np.where(
                    tier == "tier_1_early", df["early_retire_rate_tier_1"],
                    df["term_rate"],  # vested or non_vested
                ),
            ),
        ),
    )

    # Compute remaining_prob = cumprod(1 - lag(separation_rate, default=0))
    df = df.sort_values(["entry_year", "entry_age", "yos"]).reset_index(drop=True)
    grp = df.groupby(["entry_year", "entry_age"])
    sep_lagged = grp["separation_rate"].shift(1, fill_value=0.0)
    df["remaining_prob"] = (1 - sep_lagged).groupby([df["entry_year"], df["entry_age"]]).cumprod()
    rp_lagged = grp["remaining_prob"].shift(1, fill_value=1.0)
    df["separation_prob"] = rp_lagged - df["remaining_prob"]

    df["class_name"] = class_name
    return df[["entry_year", "entry_age", "term_age", "yos", "term_year",
               "separation_rate", "remaining_prob", "separation_prob",
               "class_name"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Annuity factor table (cumulative survival × discount)
# ---------------------------------------------------------------------------

def build_ann_factor_table(
    salary_benefit_table: pd.DataFrame,
    compact_mortality_by_class: dict,
    constants,
    expected_icr_by_class: "Optional[dict]" = None,
) -> pd.DataFrame:
    """Build annuity factor table for one or more classes in a single pass.

    Stacked / vectorized replacement for the former per-class
    ``build_ann_factor_table_compact``. The input ``salary_benefit_table``
    carries a ``class_name`` column; the output carries it through. All tier,
    COLA, mortality, discount, and cumulative-product resolution is done
    via numpy/pandas vectorized ops — no per-row Python loops.

    Args:
        salary_benefit_table: stacked salary/benefit frame with at least
            (class_name, entry_year, entry_age, yos). One or more classes.
        compact_mortality_by_class: dict of class_name -> CompactMortality.
            Each class has its own base table so mortality is resolved per
            class slice (vectorized within each slice).
        constants: PlanConfig.
        expected_icr_by_class: optional dict of class_name -> expected_icr
            for classes with cash-balance benefits. Classes not present in
            the dict do not get CB columns.

    Returns:
        DataFrame with columns (class_name, entry_year, entry_age, yos,
        dist_age, dist_year, term_year, tier_at_dist_age, dr, cola,
        mort_final, cum_dr, cum_mort, cum_cola, cum_mort_dr,
        cum_mort_dr_cola, ann_factor) plus (surv_icr, ann_factor_acr)
        when CB is active for any class.
    """
    from pension_model.plan_config import resolve_tiers_vec, resolve_cola_vec

    econ = constants.economic
    r = constants.ranges
    max_age = r.max_age
    expected_icr_by_class = expected_icr_by_class or {}

    # --- 1. Unique cohorts, filter to term_age <= max_age ---
    cohorts = salary_benefit_table[
        ["class_name", "entry_year", "entry_age", "yos"]
    ].drop_duplicates().reset_index(drop=True)
    term_age_c = cohorts["entry_age"].values + cohorts["yos"].values
    cohorts = cohorts[term_age_c <= max_age].reset_index(drop=True)

    # --- 2. Cross-join with dist_age range, filter dist_age >= term_age ---
    # np.repeat + per-cohort dist_age range via concatenation (avoids 2x waste)
    term_ages = cohorts["entry_age"].values + cohorts["yos"].values
    n_per_cohort = max_age - term_ages + 1
    # Repeat cohort columns
    cn_arr = np.repeat(cohorts["class_name"].values, n_per_cohort)
    ey_arr = np.repeat(cohorts["entry_year"].values, n_per_cohort).astype(np.int64)
    ea_arr = np.repeat(cohorts["entry_age"].values, n_per_cohort).astype(np.int64)
    yos_arr = np.repeat(cohorts["yos"].values, n_per_cohort).astype(np.int64)
    # dist_age ranges concatenated
    dist_age_arr = np.concatenate([
        np.arange(ta, max_age + 1, dtype=np.int64) for ta in term_ages
    ])

    dist_year_arr = ey_arr + dist_age_arr - ea_arr
    term_year_arr = ey_arr + yos_arr

    # --- 3. Vectorized tier-at-dist-age resolution ---
    tier_arr = resolve_tiers_vec(constants, cn_arr, ey_arr, dist_age_arr, yos_arr)

    # --- 4. Discount rate (single value across all current plans) ---
    dr_arr = np.full(len(dist_age_arr), econ.dr_current, dtype=np.float64)

    # --- 5. Vectorized COLA ---
    cola_arr = resolve_cola_vec(constants, tier_arr, ey_arr, yos_arr)

    # --- 6. Mortality — per-class slice (each class has its own CompactMortality) ---
    tier_s = pd.Series(tier_arr)
    is_retiree_arr = (tier_s.str.contains("norm", regex=False, na=False)
                      | tier_s.str.contains("early", regex=False, na=False)).values
    mort_arr = np.zeros(len(dist_age_arr), dtype=np.float64)
    for cn, cm in compact_mortality_by_class.items():
        cmask = cn_arr == cn
        if not cmask.any():
            continue
        sub_ages = dist_age_arr[cmask]
        sub_years = np.clip(dist_year_arr[cmask], cm.min_year, cm.max_year)
        sub_is_ret = is_retiree_arr[cmask]
        # Fetch both statuses vectorized, then select per row
        emp_rates = cm.get_rates_vec(sub_ages, sub_years, is_retiree=False)
        ret_rates = cm.get_rates_vec(sub_ages, sub_years, is_retiree=True)
        mort_arr[cmask] = np.where(sub_is_ret, ret_rates, emp_rates)

    # --- 7. Assemble DataFrame, sort, compute cumulative products ---
    df = pd.DataFrame({
        "class_name": cn_arr,
        "entry_year": ey_arr,
        "entry_age": ea_arr,
        "dist_year": dist_year_arr,
        "dist_age": dist_age_arr,
        "yos": yos_arr,
        "term_year": term_year_arr,
        "mort_final": mort_arr,
        "tier_at_dist_age": tier_arr,
        "dr": dr_arr,
        "cola": cola_arr,
    })

    group_cols = ["class_name", "entry_year", "entry_age", "yos"]
    df = df.sort_values(group_cols + ["dist_age"]).reset_index(drop=True)

    g = df.groupby(group_cols)
    dr_lagged = g["dr"].shift(1, fill_value=0.0)
    mort_lagged = g["mort_final"].shift(1, fill_value=0.0)
    cola_lagged = g["cola"].shift(1, fill_value=0.0)

    df["cum_dr"] = (1 + dr_lagged).groupby([df[c] for c in group_cols]).cumprod()
    df["cum_mort"] = (1 - mort_lagged).groupby([df[c] for c in group_cols]).cumprod()
    df["cum_cola"] = (1 + cola_lagged).groupby([df[c] for c in group_cols]).cumprod()

    df["cum_mort_dr"] = df["cum_mort"] / df["cum_dr"]
    df["cum_mort_dr_cola"] = df["cum_mort_dr"] * df["cum_cola"]

    grp = df.groupby(group_cols)["cum_mort_dr_cola"]
    group_total = grp.transform("sum")
    cum_forward = grp.cumsum()
    rev_cumsum = group_total - cum_forward + df["cum_mort_dr_cola"]
    df["ann_factor"] = rev_cumsum / df["cum_mort_dr_cola"]

    # --- 8. CB annuity factors (per class that has CB) ---
    if expected_icr_by_class:
        cb_cfg = getattr(constants, "cash_balance", None)
        if cb_cfg is not None:
            acr = cb_cfg.get("annuity_conversion_rate", 0.04)
            surv_icr_col = np.full(len(df), np.nan, dtype=np.float64)
            ann_factor_acr_col = np.full(len(df), np.nan, dtype=np.float64)

            for cn, expected_icr in expected_icr_by_class.items():
                cmask = (df["class_name"].values == cn)
                if not cmask.any():
                    continue
                sub = df.loc[cmask]
                periods = sub.groupby(group_cols).cumcount().values

                surv_icr = sub["cum_mort"].values / (1 + expected_icr) ** periods
                surv_acr = sub["cum_mort"].values / (1 + acr) ** periods
                surv_acr_cola = surv_acr * sub["cum_cola"].values

                sac = pd.Series(surv_acr_cola, index=sub.index)
                grp2 = sac.groupby([sub[c] for c in group_cols])
                gt = grp2.transform("sum")
                cf = grp2.cumsum()
                rev_cumsum_acr = gt - cf + sac
                ann_factor_acr = (rev_cumsum_acr / sac).values

                positions = np.where(cmask)[0]
                surv_icr_col[positions] = surv_icr
                ann_factor_acr_col[positions] = ann_factor_acr

            if not np.all(np.isnan(surv_icr_col)):
                df["surv_icr"] = surv_icr_col
                df["ann_factor_acr"] = ann_factor_acr_col

    return df


# ---------------------------------------------------------------------------
# 4. Benefit table (db_benefit, pvfb_db_at_term_age)
# ---------------------------------------------------------------------------

def build_benefit_table(
    ann_factor_table: pd.DataFrame,
    salary_benefit_table: pd.DataFrame,
    constants,
) -> pd.DataFrame:
    """Build benefit table combining annuity factors with salary/benefit data.

    Stacked / vectorized: ben_mult and reduce_factor are resolved via
    resolve_ben_mult_vec / resolve_reduce_factor_vec in one call each.
    class_name is carried through from ann_factor_table (which already has
    it as a key column).

    When CB is active, also computes cb_benefit and pv_cb_benefit.

    Args:
        ann_factor_table: stacked output of build_ann_factor_table, with
            class_name column.
        salary_benefit_table: stacked output of build_salary_benefit_table,
            with class_name column.
        constants: PlanConfig.

    Returns:
        DataFrame with db_benefit, ann_factor_term, pvfb_db_at_term_age, and
        optionally cb_benefit, pv_cb_benefit added. class_name is preserved.
    """
    from pension_model.plan_config import (
        resolve_ben_mult_vec, resolve_reduce_factor_vec,
    )

    cal = constants.benefit.cal_factor

    df = ann_factor_table.copy()
    df["term_age"] = df["entry_age"] + df["yos"]

    # Join salary/benefit data for FAS and db_ee_balance (+ CB columns if present).
    # Join key includes class_name so the merge is stacked-correct.
    sbt_cols = ["class_name", "entry_year", "entry_age", "yos", "term_age",
                "fas", "db_ee_balance"]
    has_cb = "cb_balance" in salary_benefit_table.columns
    if has_cb:
        sbt_cols.extend(["cb_balance", "cb_ee_balance", "cb_er_balance",
                         "cb_ee_cont", "cb_er_cont"])
    df = df.merge(
        salary_benefit_table[sbt_cols].drop_duplicates(),
        on=["class_name", "entry_year", "entry_age", "yos", "term_age"],
        how="left",
    )

    # Vectorized benefit multiplier and reduction factor
    df["ben_mult"] = resolve_ben_mult_vec(
        constants,
        df["class_name"].values,
        df["tier_at_dist_age"].values,
        df["dist_age"].values.astype(np.int64),
        df["yos"].values.astype(np.int64),
        df["dist_year"].values.astype(np.int64),
    )
    df["reduce_factor"] = resolve_reduce_factor_vec(
        constants,
        df["class_name"].values,
        df["tier_at_dist_age"].values,
        df["dist_age"].values.astype(np.int64),
        df["yos"].values.astype(np.int64),
        df["entry_year"].values.astype(np.int64),
    )

    # db_benefit = yos * ben_mult * fas * reduce_factor * cal_factor
    df["db_benefit"] = df["yos"] * df["ben_mult"] * df["fas"] * df["reduce_factor"] * cal

    # ann_factor_term = ann_factor * cum_mort_dr (at termination age)
    df["ann_factor_term"] = df["ann_factor"] * df["cum_mort_dr"]

    # pvfb_db_at_term_age = db_benefit * ann_factor_term
    df["pvfb_db_at_term_age"] = df["db_benefit"] * df["ann_factor_term"]

    # --- CB benefit columns ---
    if has_cb and "surv_icr" in df.columns and "ann_factor_acr" in df.columns:
        # cb_balance_final: project CB balance to retirement via expected ICR
        df["cb_balance_final"] = df["cb_balance"] / df["surv_icr"].replace(0, np.nan)

        # cb_benefit: annuitize at ACR
        df["cb_benefit"] = df["cb_balance_final"] / df["ann_factor_acr"].replace(0, np.nan)

        # pv_cb_benefit: depends on vesting status
        cb_vesting = 5
        cb_cfg = getattr(constants, "cash_balance", None)
        if cb_cfg is not None:
            cb_vesting = cb_cfg.get("vesting_yos", 5)
        is_vested = (df["yos"] >= cb_vesting).astype(float)
        df["pv_cb_benefit"] = (
            is_vested * df["cb_benefit"] * df["ann_factor_term"]
            + (1 - is_vested) * df["cb_balance"]
        )

    return df


def build_final_benefit_table(benefit_table: pd.DataFrame,
                              use_earliest_retire: bool = False) -> pd.DataFrame:
    """
    Determine distribution age and extract final benefit for each cohort.

    Replicates R's dist_age_table + final_benefit_table (lines 832-854).

    For vested members: dist_age = earliest normal retirement age.
    For non-vested and retirees: dist_age = term_age.

    Stacked: group keys include class_name so the function is correct for
    a stacked benefit_table with multiple classes.

    Args:
        benefit_table: stacked output of build_benefit_table, with class_name.

    Returns:
        DataFrame: class_name, entry_year, entry_age, term_age, dist_age,
                   db_benefit, pvfb_db_at_term_age, ann_factor_term
    """
    bt = benefit_table.copy()
    bt["term_age"] = bt["entry_age"] + bt["yos"]

    # FRS R uses earliest NORMAL retirement age for vested distribution
    # (is_norm_retire_elig). TRS R uses earliest ANY retirement age including
    # early (can_retire). We use can_retire when use_earliest_retire=True.
    if use_earliest_retire:
        bt["can_retire"] = bt["tier_at_dist_age"].str.contains("norm|early|reduced")
    else:
        bt["can_retire"] = bt["tier_at_dist_age"].str.contains("norm")

    # Determine distribution age per (class_name, entry_year, entry_age, term_age)
    # R formula: retire_age = n() - sum(can_retire) + min(retire_age)
    grp_keys = ["class_name", "entry_year", "entry_age", "term_age"]
    g = bt.groupby(grp_keys)
    dist_age_df = pd.DataFrame({
        "count": g["can_retire"].transform("count"),
        "retire_count": g["can_retire"].transform("sum"),
        "min_dist_age": g["dist_age"].transform("min"),
        "term_status": g["tier_at_dist_age"].transform("first"),
    })
    dist_age_df["earliest_retire_age"] = (
        dist_age_df["count"] - dist_age_df["retire_count"] + dist_age_df["min_dist_age"]
    )
    # Get one row per group
    dist_age_df = bt[grp_keys].join(dist_age_df).drop_duplicates(subset=grp_keys)

    # For vested (not non_vested): use earliest_norm_retire_age
    # For non_vested and retirees: use term_age
    is_vested = (dist_age_df["term_status"].str.contains("vested")
                 & ~dist_age_df["term_status"].str.contains("non_vested"))
    dist_age_df["dist_age"] = np.where(
        is_vested, dist_age_df["earliest_retire_age"], dist_age_df["term_age"]
    ).astype(int)

    # Semi-join: keep only rows matching
    # (class_name, entry_year, entry_age, term_age, dist_age)
    fbt = bt.merge(
        dist_age_df[grp_keys + ["dist_age"]],
        on=grp_keys + ["dist_age"],
        how="inner",
    )

    # Replace NaN benefits with 0
    fbt["db_benefit"] = fbt["db_benefit"].fillna(0)
    fbt["pvfb_db_at_term_age"] = fbt["pvfb_db_at_term_age"].fillna(0)

    out_cols = ["class_name", "entry_year", "entry_age", "term_age", "dist_age",
                "db_benefit", "pvfb_db_at_term_age", "ann_factor_term"]
    # Pass through CB columns if present
    for col in ["cb_benefit", "pv_cb_benefit", "cb_balance"]:
        if col in fbt.columns:
            fbt[col] = fbt[col].fillna(0)
            out_cols.append(col)

    return fbt[out_cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 5. Benefit valuation table (PVFB, PVFS, NC)
# ---------------------------------------------------------------------------

def _npv(rate: float, cashflows: np.ndarray) -> float:
    """R's npv(): sum of cashflows[i] / (1+rate)^(i+1) for i=0..n-1."""
    if len(cashflows) == 0:
        return 0.0
    disc = (1 + rate) ** np.arange(1, len(cashflows) + 1)
    return (cashflows / disc).sum()


def _get_pvfb(sep_rate: np.ndarray, dr: np.ndarray, values: np.ndarray) -> np.ndarray:
    """
    Present value of future benefits at each yos.

    Replicates R's get_pvfb() (utility_functions.R lines 226-238):
      For each i, take sep_rate[i:], compute sep_prob with double lag,
      multiply by values, then npv the result (excluding first element).
    """
    n = len(sep_rate)
    pvfb = np.zeros(n)
    for i in range(n):
        sr = sep_rate[i:]
        m = len(sr)
        # sep_prob = cumprod(1 - lag(sr, n=2, default=0)) * lag(sr, default=0)
        # lag(sr, n=2, default=0): shift right by 2, fill with 0
        lag2 = np.zeros(m)
        if m > 2:
            lag2[2:] = sr[:-2]
        elif m > 1:
            pass  # all zeros
        cum_surv = np.cumprod(1 - lag2)

        # lag(sr, default=0): shift right by 1, fill with 0
        lag1 = np.zeros(m)
        if m > 1:
            lag1[1:] = sr[:-1]
        sep_prob = cum_surv * lag1

        val = values[i:]
        val_adjusted = val * sep_prob
        # npv of val_adjusted[1:] (skip first element)
        interest = dr[i]
        pvfb[i] = _npv(interest, val_adjusted[1:])
    return pvfb


def _get_pvfs(remaining_prob: np.ndarray, dr: np.ndarray, salary: np.ndarray) -> np.ndarray:
    """
    Present value of future salary at each yos.

    Replicates R's get_pvfs() (utility_functions.R lines 287-298):
      For each i, normalize remaining_prob[i:] to start at 1.0,
      multiply by salary, then npv.
    """
    n = len(remaining_prob)
    pvfs = np.zeros(n)
    for i in range(n):
        rp = remaining_prob[i:]
        rp_norm = rp / rp[0] if rp[0] > 0 else rp
        sal = salary[i:]
        sal_adjusted = sal * rp_norm
        interest = dr[i]
        pvfs[i] = _npv(interest, sal_adjusted)
    return pvfs


def _get_pvfb_cb(
    cb_ee_balance: np.ndarray, cb_ee_cont: np.ndarray,
    cb_er_balance: np.ndarray, cb_er_cont: np.ndarray,
    vesting_yos: int, retire_refund_ratio: float,
    yos: np.ndarray,
    sep_type: np.ndarray,
    sep_rate: np.ndarray,
    dr: np.ndarray,
    expected_icr: float,
    surv_icr: np.ndarray,
    ann_factor_acr: np.ndarray,
    ann_factor_adj_dr: np.ndarray,
) -> np.ndarray:
    """
    Present value of future CB benefits at each YOS.

    Matches R's get_pvfb_cb_vec (Rcpp_functions.cpp lines 219-243).
    For each starting YOS i:
      1. Re-project CBBalance from i forward at expected_icr
      2. Compute PV_CB_Benefit at each future age
      3. Compute CBWealth based on sep_type (retire/vested/non_vested)
      4. NPV the sep-probability-weighted wealth
    """
    n = len(cb_ee_balance)
    pvfb_cb = np.zeros(n)

    for i in range(n):
        m = n - i
        if m <= 0:
            continue

        # Re-project CB balance from position i forward at expected_icr
        ee_cont_slice = cb_ee_cont[i:]
        er_cont_slice = cb_er_cont[i:]
        icr_vec = np.full(m, expected_icr)
        cb_ee_proj = _cum_fv_vec(icr_vec, ee_cont_slice, first_value=cb_ee_balance[i])
        cb_er_proj = _cum_fv_vec(icr_vec, er_cont_slice, first_value=cb_er_balance[i])
        yos_slice = yos[i:]
        cb_bal_proj = cb_ee_proj + np.where(yos_slice >= vesting_yos, cb_er_proj, 0.0)

        # PV_CB_Benefit at each future age
        surv_icr_slice = surv_icr[i:]
        ann_acr_slice = ann_factor_acr[i:]
        ann_adj_slice = ann_factor_adj_dr[i:]

        # pv_cb_benefit = CBBalance / surv_icr / ann_factor_acr * ann_factor_adj_dr
        with np.errstate(divide="ignore", invalid="ignore"):
            pv_cb_benefit = np.where(
                (surv_icr_slice != 0) & (ann_acr_slice != 0),
                cb_bal_proj / surv_icr_slice / ann_acr_slice * ann_adj_slice,
                0.0,
            )

        # CB wealth by separation type
        sep_slice = sep_type[i:]
        cb_wealth = np.where(
            sep_slice == "retire", pv_cb_benefit,
            np.where(
                sep_slice == "vested",
                retire_refund_ratio * pv_cb_benefit + (1 - retire_refund_ratio) * cb_bal_proj,
                cb_bal_proj,  # non_vested → refund of balance
            ),
        )

        # NPV with separation probabilities (same algorithm as _get_pvfb)
        sr = sep_rate[i:]
        lag2 = np.zeros(m)
        if m > 2:
            lag2[2:] = sr[:-2]
        cum_surv = np.cumprod(1 - lag2)
        lag1 = np.zeros(m)
        if m > 1:
            lag1[1:] = sr[:-1]
        sep_prob = cum_surv * lag1

        val_adjusted = cb_wealth * sep_prob
        pvfb_cb[i] = _npv(dr[i], val_adjusted[1:])

    return pvfb_cb


def _resolve_sep_type_vec(tier: np.ndarray) -> np.ndarray:
    """Vectorized get_sep_type — bit-identical to the scalar version.

    Scalar logic: retire if tier contains any of (early, norm, reduced);
    else non_vested if tier contains 'non_vested';
    else vested if tier contains 'vested';
    else non_vested.
    """
    tier_s = pd.Series(tier)
    has_retire = (tier_s.str.contains("early", regex=False, na=False)
                  | tier_s.str.contains("norm", regex=False, na=False)
                  | tier_s.str.contains("reduced", regex=False, na=False)).values
    has_nonvested = tier_s.str.contains("non_vested", regex=False, na=False).values
    has_vested = tier_s.str.contains("vested", regex=False, na=False).values

    result = np.full(len(tier), "non_vested", dtype=object)
    # Order matches scalar: retire > non_vested > vested > fallthrough(non_vested)
    result[has_vested & ~has_nonvested] = "vested"
    result[has_nonvested] = "non_vested"
    result[has_retire] = "retire"
    return result


def build_benefit_val_table(
    salary_benefit_table: pd.DataFrame,
    benefit_table: pd.DataFrame,
    sep_rate_table: pd.DataFrame,
    constants,
    expected_icr: "Optional[float]" = None,
    ann_factor_table: "Optional[pd.DataFrame]" = None,
) -> pd.DataFrame:
    """
    Build benefit valuation table with PVFB, PVFS, and normal cost.

    Stacked: all merges and groupbys include class_name so the function is
    correct for stacked inputs with multiple classes. sep_type is resolved
    with a vectorized mask-based helper (no per-row Python dispatch).

    When CB is active, also computes pvfb_cb_at_current_age,
    indv_norm_cost_cb, and pvfnc_cb.

    Args:
        salary_benefit_table: stacked output of build_salary_benefit_table.
        benefit_table: stacked output of build_final_benefit_table.
        sep_rate_table: stacked separation rate table.
        constants: PlanConfig.
        expected_icr: Expected ICR for CB PVFB projection (None if no CB).
        ann_factor_table: full stacked ann_factor_table (needed for CB
            surv_icr, ann_factor_acr, ann_factor_term at each term_age).

    Returns:
        DataFrame with pvfb_db_wealth_at_current_age, pvfs_at_current_age,
            indv_norm_cost, pvfnc_db,
            [pvfb_cb_at_current_age, indv_norm_cost_cb, pvfnc_cb]
    """
    r = constants.benefit.retire_refund_ratio
    econ = constants.economic

    has_cb = (expected_icr is not None
              and "cb_balance" in salary_benefit_table.columns
              and ann_factor_table is not None
              and "surv_icr" in ann_factor_table.columns)

    cb_vesting = 5
    if has_cb:
        cb_cfg = getattr(constants, "cash_balance", None)
        if cb_cfg is not None:
            cb_vesting = cb_cfg.get("vesting_yos", 5)

    # Start from salary_benefit_table
    sbt = salary_benefit_table.copy()
    sbt["term_year"] = sbt["entry_year"] + sbt["yos"]

    # Join final_benefit_table on (class_name, entry_year, entry_age, term_age)
    fbt_cols = ["class_name", "entry_year", "entry_age", "term_age",
                "db_benefit", "pvfb_db_at_term_age"]
    sbt = sbt.merge(
        benefit_table[fbt_cols].drop_duplicates(),
        on=["class_name", "entry_year", "entry_age", "term_age"],
        how="left",
    )

    # Join separation rates. sep_rate_table is keyed by sep_class, not
    # class_name: FRS eco / eso / judges all share the "regular" sep rates
    # via constants.sep_class_map. The caller (build_plan_benefit_tables)
    # attaches a sep_class column to salary_benefit_table; we rename the
    # sep_rate_table's own class_name column to sep_class and join on the
    # full compound key so rows from different sep_classes with the same
    # (entry_year, entry_age, term_age, yos, term_year) tuple cannot cross
    # into each other's joins.
    sep_rename = sep_rate_table.rename(columns={"class_name": "sep_class"})
    sbt = sbt.merge(
        sep_rename,
        on=["sep_class", "entry_year", "entry_age", "term_age", "yos",
            "term_year"],
        how="left",
    )

    # Vectorized separation type
    sbt["sep_type"] = _resolve_sep_type_vec(sbt["tier_at_term_age"].values)
    sbt["dr"] = np.where(
        sbt["tier_at_term_age"].str.contains("tier_3"), econ.dr_new, econ.dr_current
    )

    # PVFB at termination: mix of annuity and refund based on sep_type.
    # Retirees get full annuity PV; vested get retire_refund_ratio-weighted
    # mix of annuity PV and refund (DBEEBalance); non-vested get refund only.
    sbt["pvfb_db_wealth_at_term_age"] = np.where(
        sbt["sep_type"] == "retire", sbt["pvfb_db_at_term_age"],
        np.where(
            sbt["sep_type"] == "vested",
            r * sbt["pvfb_db_at_term_age"] + (1 - r) * sbt["db_ee_balance"],
            sbt["db_ee_balance"],  # non_vested
        ),
    )

    # --- Extract CB annuity factors at term_age from the full ann_factor_table ---
    if has_cb:
        aft = ann_factor_table
        aft_term = aft[aft["dist_age"] == aft["entry_age"] + aft["yos"]].copy()
        aft_term["ann_factor_adj_dr"] = aft_term["ann_factor"] * aft_term["cum_mort_dr"]
        aft_cb_keys = ["class_name", "entry_year", "entry_age", "yos"]
        cb_join_cols = ["surv_icr", "ann_factor_acr", "ann_factor_adj_dr"]
        sbt = sbt.merge(
            aft_term[aft_cb_keys + cb_join_cols].drop_duplicates(subset=aft_cb_keys),
            on=aft_cb_keys,
            how="left",
        )
        for col in cb_join_cols:
            sbt[col] = sbt[col].fillna(0.0)

    # Compute PVFB, PVFS, NC within each (class_name, entry_year, entry_age) group
    def _compute_pv(g):
        g = g.sort_values("yos")
        sep = np.nan_to_num(g["separation_rate"].values.astype(float), 0.0)
        rp = np.nan_to_num(g["remaining_prob"].values.astype(float), 0.0)
        dr_arr = g["dr"].values.astype(float)
        val = np.nan_to_num(g["pvfb_db_wealth_at_term_age"].values.astype(float), 0.0)
        sal = g["salary"].values.astype(float)

        pvfb = _get_pvfb(sep, dr_arr, val)
        pvfs = _get_pvfs(rp, dr_arr, sal)

        nc_rate = pvfb[0] / pvfs[0] if pvfs[0] > 0 else 0.0

        g["pvfb_db_wealth_at_current_age"] = pvfb
        g["pvfs_at_current_age"] = pvfs
        g["indv_norm_cost"] = nc_rate
        g["pvfnc_db"] = nc_rate * pvfs

        # CB PVFB — using real annuity factor data from ann_factor_table
        if has_cb:
            cb_ee_bal = np.nan_to_num(g["cb_ee_balance"].values.astype(float), 0.0)
            cb_ee_cont = np.nan_to_num(g["cb_ee_cont"].values.astype(float), 0.0)
            cb_er_bal = np.nan_to_num(g["cb_er_balance"].values.astype(float), 0.0)
            cb_er_cont = np.nan_to_num(g["cb_er_cont"].values.astype(float), 0.0)
            yos_arr = g["yos"].values.astype(float)
            sep_type_arr = g["sep_type"].values
            surv_icr_arr = np.nan_to_num(g["surv_icr"].values.astype(float), 0.0)
            ann_acr_arr = np.nan_to_num(g["ann_factor_acr"].values.astype(float), 0.0)
            ann_adj_arr = np.nan_to_num(g["ann_factor_adj_dr"].values.astype(float), 0.0)

            pvfb_cb = _get_pvfb_cb(
                cb_ee_bal, cb_ee_cont, cb_er_bal, cb_er_cont,
                cb_vesting, r,
                yos_arr, sep_type_arr, sep, dr_arr, expected_icr,
                surv_icr_arr, ann_acr_arr, ann_adj_arr,
            )
            nc_rate_cb = pvfb_cb[0] / pvfs[0] if pvfs[0] > 0 else 0.0
            g["pvfb_cb_at_current_age"] = pvfb_cb
            g["indv_norm_cost_cb"] = nc_rate_cb
            g["pvfnc_cb"] = nc_rate_cb * pvfs

        return g

    result_parts = []
    for _, g in sbt.groupby(["class_name", "entry_year", "entry_age"]):
        result_parts.append(_compute_pv(g))
    return pd.concat(result_parts, ignore_index=True)
