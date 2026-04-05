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
from typing import Callable

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
    get_tier: Callable,
    actual_icr_series: "Optional[pd.Series]" = None,
) -> pd.DataFrame:
    """
    Build the salary/benefit table for all cohorts.

    For each (entry_year, entry_age, yos): salary, FAS, db_ee_balance,
    and when cash balance is active: cb_ee_balance, cb_er_balance, cb_balance.

    Args:
        salary_headcount: Output of build_salary_headcount_table().
        entrant_profile: Output of build_entrant_profile().
        salary_growth: Salary growth table with yos and class column.
        class_name: Membership class name.
        constants: Model constants or PlanConfig.
        get_tier: Callable(class_name, entry_year, age, yos) -> tier string.
        actual_icr_series: Year→ICR series for CB accumulation (None if no CB).

    Returns:
        DataFrame: entry_year, entry_age, yos, term_age, tier_at_term_age,
                   salary, fas, db_ee_balance, cumprod_salary_increase,
                   [cb_ee_cont, cb_er_cont, cb_ee_balance, cb_er_balance, cb_balance]
    """
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

    entry_ages = entrant_profile["entry_age"].values

    # Build the expand_grid equivalent
    rows = []
    for ey in r.entry_year_range:
        for ea in entry_ages:
            for yos in range(0, max_yos + 1):
                term_age = ea + yos
                if term_age <= r.max_age:
                    rows.append((ey, ea, yos, term_age))

    df = pd.DataFrame(rows, columns=["entry_year", "entry_age", "yos", "term_age"])

    # Add tier at termination age
    df["tier_at_term_age"] = df.apply(
        lambda row: get_tier(class_name, row["entry_year"], row["term_age"], row["yos"]),
        axis=1,
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
    get_tier_fn=None,
) -> pd.DataFrame:
    """
    Build separation rate table combining withdrawal and retirement rates.

    Replicates R's get_separation_table() (benefit model lines 522-582).

    Args:
        term_rate_avg: Gender-averaged withdrawal rates (yos × age_group).
        normal_retire_rate_tier1/2: Normal retirement rates by age.
        early_retire_rate_tier1/2: Early retirement rates by age.
        entrant_profile: Entrant profile with entry_age column.
        class_name: Membership class name.
        constants: Model constants.

    Returns:
        DataFrame: entry_year, entry_age, term_age, yos, term_year,
                   separation_rate, remaining_prob, separation_prob, class_name
    """
    r = constants.ranges

    # Age group breaks and labels matching R's cut()
    breaks = [-np.inf, 24, 29, 34, 44, 54, np.inf]
    labels = list(term_rate_avg.columns[1:])  # age group column names

    # Pivot term rates to long format
    term_long = term_rate_avg.melt(id_vars="yos", var_name="age_group", value_name="term_rate")

    entry_ages = entrant_profile["entry_age"].values

    # Build expand_grid: (entry_year, term_age, yos)
    rows = []
    for ey in r.entry_year_range:
        for ta in r.age_range:
            for yos in r.yos_range:
                ea = ta - yos
                if ea in entry_ages:
                    rows.append((ey, ta, yos, ea, ey + yos))

    df = pd.DataFrame(rows, columns=["entry_year", "term_age", "yos", "entry_age", "term_year"])

    # Assign age groups using pd.cut (matching R's cut())
    df["age_group"] = pd.cut(df["term_age"], bins=breaks, labels=labels, right=True)
    df["age_group"] = df["age_group"].astype(str)

    df = df.sort_values(["entry_year", "entry_age", "term_age"]).reset_index(drop=True)

    # Join withdrawal rates
    df = df.merge(term_long, on=["yos", "age_group"], how="left")

    # Join retirement rates by term_age
    for tbl, col_name in [
        (normal_retire_rate_tier1, "normal_retire_rate_tier_1"),
        (normal_retire_rate_tier2, "normal_retire_rate_tier_2"),
        (early_retire_rate_tier1, "early_retire_rate_tier_1"),
        (early_retire_rate_tier2, "early_retire_rate_tier_2"),
    ]:
        rate_col = [c for c in tbl.columns if c != "age"][0]
        tbl_renamed = tbl.rename(columns={rate_col: col_name})
        df = df.merge(tbl_renamed[["age", col_name]], left_on="term_age", right_on="age", how="left")
        if "age_y" in df.columns:
            df = df.drop(columns=["age_y"])
        if "age" in df.columns and "age" != "term_age":
            # Remove the extra 'age' column from the join
            if df.columns.tolist().count("age") > 0 and "term_age" in df.columns:
                df = df.drop(columns=["age"], errors="ignore")

    # Fill retirement rates within each (entry_year, entry_age) group
    df = df.sort_values(["entry_year", "entry_age", "term_age"])
    retire_cols = [c for c in df.columns if "retire_rate" in c]
    df[retire_cols] = df.groupby(["entry_year", "entry_age"])[retire_cols].transform(
        lambda x: x.ffill().bfill()
    )

    # Determine tier and separation rate
    df["tier_at_term_age"] = get_tier_vectorized(
        class_name, df["entry_year"].values, df["term_age"].values,
        df["yos"].values, r.new_year, get_tier_fn=get_tier_fn,
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
    # Vectorized using groupby shift + cumprod
    df = df.sort_values(["entry_year", "entry_age", "yos"]).reset_index(drop=True)
    grp = df.groupby(["entry_year", "entry_age"])
    sep_lagged = grp["separation_rate"].shift(1, fill_value=0.0)
    df["remaining_prob"] = (1 - sep_lagged).groupby([df["entry_year"], df["entry_age"]]).cumprod()
    # separation_prob = lag(remaining_prob, default=1) - remaining_prob
    rp_lagged = grp["remaining_prob"].shift(1, fill_value=1.0)
    df["separation_prob"] = rp_lagged - df["remaining_prob"]

    df["class_name"] = class_name
    return df[["entry_year", "entry_age", "term_age", "yos", "term_year",
               "separation_rate", "remaining_prob", "separation_prob", "class_name"]].reset_index(drop=True)


def get_tier_vectorized(class_name, entry_year, age, yos, new_year=2024, get_tier_fn=None):
    """Vectorized get_tier. Uses provided callable or falls back to FRS config."""
    if get_tier_fn is None:
        from pension_model.plan_config import load_frs_config, get_tier as _pc_get_tier
        _cfg = load_frs_config()
        get_tier_fn = lambda cn, ey, a, y, ny=None: _pc_get_tier(_cfg, cn, ey, a, y)
    n = len(entry_year)
    result = np.empty(n, dtype=object)
    for i in range(n):
        result[i] = get_tier_fn(class_name, int(entry_year[i]), int(age[i]), int(yos[i]), new_year)
    return result


# ---------------------------------------------------------------------------
# 3. Annuity factor table (cumulative survival × discount)
# ---------------------------------------------------------------------------

def build_ann_factor_table_compact(
    salary_benefit_table: pd.DataFrame,
    compact_mortality,
    class_name: str,
    constants,
    expected_icr: "Optional[float]" = None,
    get_tier_fn: "Optional[Callable]" = None,
) -> pd.DataFrame:
    """
    Build annuity factor table using CompactMortality (no 3M-row CSV needed).

    For each (entry_year, entry_age, yos) from the salary_benefit_table,
    generates mortality/COLA/discount vectors and computes annuity factors.

    When CB is active (expected_icr is not None), also computes:
      - surv_icr: survival discounted by expected ICR
      - ann_factor_acr: annuity factor at the annuity conversion rate (ACR)

    Reads COLA, discount rate, and tier assignments from the PlanConfig.
    """
    econ = constants.economic
    r = constants.ranges
    cola_cutoff = constants.cola_proration_cutoff_year

    # Resolve tier function (PlanConfig-driven by default)
    if get_tier_fn is None:
        from pension_model.plan_config import get_tier as _pc_get_tier
        get_tier_fn = lambda cn, ey, da, yos: _pc_get_tier(constants, cn, ey, da, yos)

    # CB parameters (if active)
    has_cb = expected_icr is not None
    acr = None
    if has_cb:
        cb_cfg = getattr(constants, "cash_balance", None)
        if cb_cfg is not None:
            acr = cb_cfg.get("annuity_conversion_rate", 0.04)

    # COLA lookup: match tier name to cola_key in the tier definitions
    def _get_cola(tier, ey, yos):
        for td in constants.tier_defs:
            if td["name"] in tier:
                cola_key = td.get("cola_key", "tier_1_active")
                raw_cola = constants.cola.get(cola_key, 0.0)
                # COLA proration: tier_1 COLA prorated by pre-cutoff YOS
                if (cola_key == "tier_1_active"
                        and not constants.cola.get("tier_1_active_constant", False)
                        and cola_cutoff is not None
                        and raw_cola > 0 and yos > 0):
                    yos_b4 = min(max(cola_cutoff - ey, 0), yos)
                    return raw_cola * yos_b4 / yos
                return raw_cola
        return 0.0

    # Get unique cohorts from salary_benefit_table
    sbt = salary_benefit_table[["entry_year", "entry_age", "yos"]].drop_duplicates()

    rows = []
    for _, cohort in sbt.iterrows():
        ey = int(cohort["entry_year"])
        ea = int(cohort["entry_age"])
        yos = int(cohort["yos"])
        term_age = ea + yos
        term_year = ey + yos

        if term_age > r.max_age:
            continue

        # Generate dist_age range
        for dist_age in range(term_age, r.max_age + 1):
            dist_year = ey + dist_age - ea

            # Determine tier and mortality status
            tier = get_tier_fn(class_name, ey, dist_age, yos)
            is_retiree = "norm" in tier or "early" in tier
            mort = compact_mortality.get_rate(dist_age, dist_year, is_retiree)

            # Discount rate (all current plans use a single rate)
            dr = econ.dr_current

            cola = _get_cola(tier, ey, yos)

            rows.append((ey, ea, dist_year, dist_age, yos, term_year, mort, tier, dr, cola))

    df = pd.DataFrame(rows, columns=[
        "entry_year", "entry_age", "dist_year", "dist_age", "yos",
        "term_year", "mort_final", "tier_at_dist_age", "dr", "cola",
    ])

    # Vectorized cumulative products within each cohort
    group_cols = ["entry_year", "entry_age", "yos"]
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

    # --- CB annuity factors (when cash balance is active) ---
    if has_cb and acr is not None:
        # periods = dist_age - term_age (0, 1, 2, ... within each group)
        g_term = df.groupby(group_cols)
        periods = g_term.cumcount()

        # surv_icr: survival / (1 + expected_icr)^periods
        df["surv_icr"] = df["cum_mort"] / (1 + expected_icr) ** periods

        # ACR-based survival and annuity factor
        # surv_acr = cum_mort / (1 + acr)^periods
        surv_acr = df["cum_mort"] / (1 + acr) ** periods
        surv_acr_cola = surv_acr * df["cum_cola"]

        # ann_factor_acr = rev_cumsum(surv_acr_cola) / surv_acr_cola
        grp_acr = surv_acr_cola.groupby([df[c] for c in group_cols])
        group_total_acr = grp_acr.transform("sum")
        cum_forward_acr = grp_acr.cumsum()
        rev_cumsum_acr = group_total_acr - cum_forward_acr + surv_acr_cola
        df["ann_factor_acr"] = rev_cumsum_acr / surv_acr_cola

    df["class_name"] = class_name
    return df


# ---------------------------------------------------------------------------
# 4. Benefit table (db_benefit, pvfb_db_at_term_age)
# ---------------------------------------------------------------------------

def build_benefit_table(
    ann_factor_table: pd.DataFrame,
    salary_benefit_table: pd.DataFrame,
    class_name: str,
    constants,
    get_ben_mult: Callable,
    get_reduce_factor: Callable,
) -> pd.DataFrame:
    """
    Build benefit table combining annuity factors with salary/benefit data.

    When CB is active, also computes cb_benefit and pv_cb_benefit.

    Args:
        ann_factor_table: Output of build_ann_factor_table_compact().
        salary_benefit_table: Output of build_salary_benefit_table().
        class_name: Membership class name.
        constants: PlanConfig.
        get_ben_mult: Callable(class_name, tier, dist_age, yos, dist_year) -> multiplier
        get_reduce_factor: Callable(class_name, tier, dist_age) -> reduction factor

    Returns:
        DataFrame with db_benefit, ann_factor_term, pvfb_db_at_term_age,
        and optionally cb_benefit, pv_cb_benefit added.
    """
    cal = constants.benefit.cal_factor

    df = ann_factor_table.copy()
    df["term_age"] = df["entry_age"] + df["yos"]

    # Join salary/benefit data for FAS and db_ee_balance (+ CB columns if present)
    sbt_cols = ["entry_year", "entry_age", "yos", "term_age", "fas", "db_ee_balance"]
    has_cb = "cb_balance" in salary_benefit_table.columns
    if has_cb:
        sbt_cols.extend(["cb_balance", "cb_ee_balance", "cb_er_balance",
                         "cb_ee_cont", "cb_er_cont"])
    df = df.merge(
        salary_benefit_table[sbt_cols].drop_duplicates(),
        on=["entry_year", "entry_age", "yos", "term_age"],
        how="left",
    )

    # Compute benefit multiplier and reduction factor
    tiers = df["tier_at_dist_age"].values
    dist_ages = df["dist_age"].values.astype(int)
    yos_vals = df["yos"].values.astype(int)
    dist_years = df["dist_year"].values.astype(int)
    n = len(df)
    ben_mult_arr = np.full(n, np.nan)
    reduce_arr = np.full(n, np.nan)
    entry_years = df["entry_year"].values.astype(int)
    for i in range(n):
        ben_mult_arr[i] = get_ben_mult(class_name, tiers[i], dist_ages[i], yos_vals[i], dist_years[i])
        reduce_arr[i] = get_reduce_factor(class_name, tiers[i], dist_ages[i],
                                          yos_vals[i], entry_years[i])
    df["ben_mult"] = ben_mult_arr
    df["reduce_factor"] = reduce_arr

    # db_benefit = yos * ben_mult * fas * reduce_factor * cal_factor
    df["db_benefit"] = df["yos"] * df["ben_mult"] * df["fas"] * df["reduce_factor"] * cal

    # ann_factor_term = ann_factor * cum_mort_dr (at termination age)
    df["ann_factor_term"] = df["ann_factor"] * df["cum_mort_dr"]

    # pvfb_db_at_term_age = db_benefit * ann_factor_term
    df["pvfb_db_at_term_age"] = df["db_benefit"] * df["ann_factor_term"]

    # --- CB benefit columns ---
    if has_cb and "surv_icr" in df.columns and "ann_factor_acr" in df.columns:
        # cb_balance_final: project CB balance to retirement via expected ICR
        # R: CBBalance_final = CBBalance / surv_actual_ICR
        df["cb_balance_final"] = df["cb_balance"] / df["surv_icr"].replace(0, np.nan)

        # cb_benefit: annuitize at ACR
        # R: CB_Benefit = CBBalance_final / AnnuityFactor_ACR
        df["cb_benefit"] = df["cb_balance_final"] / df["ann_factor_acr"].replace(0, np.nan)

        # pv_cb_benefit: depends on vesting status
        # R: is_after_CB_vesting * CB_Benefit * AnnFactorAdj_DR + (1 - is_after_CB_vesting) * CBBalance
        cb_vesting = 5
        cb_cfg = getattr(constants, "cash_balance", None)
        if cb_cfg is not None:
            cb_vesting = cb_cfg.get("vesting_yos", 5)
        is_vested = (df["yos"] >= cb_vesting).astype(float)
        df["pv_cb_benefit"] = (
            is_vested * df["cb_benefit"] * df["ann_factor_term"]
            + (1 - is_vested) * df["cb_balance"]
        )

    df["class_name"] = class_name
    return df


def build_final_benefit_table(benefit_table: pd.DataFrame,
                              use_earliest_retire: bool = False) -> pd.DataFrame:
    """
    Determine distribution age and extract final benefit for each cohort.

    Replicates R's dist_age_table + final_benefit_table (lines 832-854).

    For vested members: dist_age = earliest normal retirement age.
    For non-vested and retirees: dist_age = term_age.

    Args:
        benefit_table: Output of build_benefit_table().

    Returns:
        DataFrame: entry_year, entry_age, term_age, dist_age,
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

    # Determine distribution age per (entry_year, entry_age, term_age)
    # R formula: retire_age = n() - sum(can_retire) + min(retire_age)
    grp_keys = ["entry_year", "entry_age", "term_age"]
    g = bt.groupby(grp_keys)
    dist_age_df = pd.DataFrame({
        "count": g["can_retire"].transform("count"),
        "retire_count": g["can_retire"].transform("sum"),
        "min_dist_age": g["dist_age"].transform("min"),
        "term_status": g["tier_at_dist_age"].transform("first"),
    })
    dist_age_df["earliest_retire_age"] = dist_age_df["count"] - dist_age_df["retire_count"] + dist_age_df["min_dist_age"]
    # Get one row per group
    dist_age_df = bt[grp_keys].join(dist_age_df).drop_duplicates(subset=grp_keys)

    # For vested (not non_vested): use earliest_norm_retire_age
    # For non_vested and retirees: use term_age
    is_vested = (dist_age_df["term_status"].str.contains("vested")
                 & ~dist_age_df["term_status"].str.contains("non_vested"))
    dist_age_df["dist_age"] = np.where(
        is_vested, dist_age_df["earliest_retire_age"], dist_age_df["term_age"]
    ).astype(int)

    # Semi-join: keep only rows in benefit_table matching (entry_year, entry_age, term_age, dist_age)
    bt["term_age"] = bt["entry_age"] + bt["yos"]
    fbt = bt.merge(
        dist_age_df[["entry_year", "entry_age", "term_age", "dist_age"]],
        on=["entry_year", "entry_age", "term_age", "dist_age"],
        how="inner",
    )

    # Replace NaN benefits with 0
    fbt["db_benefit"] = fbt["db_benefit"].fillna(0)
    fbt["pvfb_db_at_term_age"] = fbt["pvfb_db_at_term_age"].fillna(0)

    out_cols = ["entry_year", "entry_age", "term_age", "dist_age",
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


def build_benefit_val_table(
    salary_benefit_table: pd.DataFrame,
    benefit_table: pd.DataFrame,
    sep_rate_table: pd.DataFrame,
    class_name: str,
    constants,
    get_sep_type: Callable,
    expected_icr: "Optional[float]" = None,
    ann_factor_table: "Optional[pd.DataFrame]" = None,
) -> pd.DataFrame:
    """
    Build benefit valuation table with PVFB, PVFS, and normal cost.

    When CB is active, also computes pvfb_cb_at_current_age, indv_norm_cost_cb,
    and pvfnc_cb.

    Args:
        salary_benefit_table: Output of build_salary_benefit_table().
        benefit_table: Output of build_final_benefit_table().
        sep_rate_table: Separation rate table.
        class_name: Membership class name.
        constants: Model constants or PlanConfig.
        get_sep_type: Callable(tier_str) -> "retire"|"vested"|"non_vested"
        expected_icr: Expected ICR for CB PVFB projection (None if no CB).
        ann_factor_table: Full ann_factor_table (needed for CB surv_icr,
            ann_factor_acr, ann_factor_term at each term_age).

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

    # Join final_benefit_table
    fbt = benefit_table
    fbt_cols = ["entry_year", "entry_age", "term_age", "db_benefit", "pvfb_db_at_term_age"]
    sbt = sbt.merge(
        fbt[fbt_cols].drop_duplicates(),
        on=["entry_year", "entry_age", "term_age"],
        how="left",
    )

    # Join separation rates
    sbt = sbt.merge(sep_rate_table, on=["entry_year", "entry_age", "term_age", "yos", "term_year"],
                     how="left")

    # Determine separation type and benefit decision
    sbt["sep_type"] = sbt["tier_at_term_age"].apply(get_sep_type)
    sbt["dr"] = np.where(sbt["tier_at_term_age"].str.contains("tier_3"), econ.dr_new, econ.dr_current)

    # PVFB at termination: mix of annuity and refund based on sep_type
    # Wealth at termination: retirees get full annuity PV, vested get a mix
    # of annuity PV and refund (DBEEBalance), non-vested get refund only.
    # retire_refund_ratio weights the annuity PV; (1-r) weights the refund.
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
        # At each cohort's term_age, dist_age == term_age (first row per cohort in aft).
        # Extract surv_icr, ann_factor_acr, and ann_factor_term at that point.
        aft = ann_factor_table
        aft_term = aft[aft["dist_age"] == aft["entry_age"] + aft["yos"]].copy()
        aft_term["ann_factor_adj_dr"] = aft_term["ann_factor"] * aft_term["cum_mort_dr"]
        aft_cb_cols = ["entry_year", "entry_age", "yos"]
        cb_join_cols = ["surv_icr", "ann_factor_acr", "ann_factor_adj_dr"]
        sbt = sbt.merge(
            aft_term[aft_cb_cols + cb_join_cols].drop_duplicates(subset=aft_cb_cols),
            on=aft_cb_cols,
            how="left",
        )
        for col in cb_join_cols:
            sbt[col] = sbt[col].fillna(0.0)

    # Compute PVFB, PVFS, NC within each (entry_year, entry_age) group
    def _compute_pv(g):
        g = g.sort_values("yos")
        sep = g["separation_rate"].values.astype(float)
        rp = g["remaining_prob"].values.astype(float)
        dr_arr = g["dr"].values.astype(float)
        val = g["pvfb_db_wealth_at_term_age"].values.astype(float)
        sal = g["salary"].values.astype(float)

        # Replace NaN with 0
        val = np.nan_to_num(val, 0.0)
        sep = np.nan_to_num(sep, 0.0)
        rp = np.nan_to_num(rp, 0.0)

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
    for _, g in sbt.groupby(["entry_year", "entry_age"]):
        result_parts.append(_compute_pv(g))
    sbt = pd.concat(result_parts, ignore_index=True)
    sbt["class_name"] = class_name
    return sbt
