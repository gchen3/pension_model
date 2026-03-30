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

from pension_model.core.model_constants import ModelConstants

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


def _get_salary_growth_col(class_name: str) -> str:
    """Resolve salary growth column name for a class."""
    return SALARY_GROWTH_COL_MAP.get(class_name, f"salary_increase_{class_name}")


# ---------------------------------------------------------------------------
# 1. Salary / headcount table construction
# ---------------------------------------------------------------------------

def build_salary_headcount_table(
    salary_wide: pd.DataFrame,
    headcount_wide: pd.DataFrame,
    salary_growth: pd.DataFrame,
    class_name: str,
    adjustment_ratio: float,
    start_year: int,
) -> pd.DataFrame:
    """
    Convert wide-format salary/headcount to long-format with entry_salary.

    Replicates R's get_salary_headcount_table().

    Args:
        salary_wide: Wide table with age rows, yos columns, salary values.
        headcount_wide: Wide table with age rows, yos columns, count values.
        salary_growth: Table with 'yos' and cumulative salary growth column.
        class_name: Membership class name.
        adjustment_ratio: Headcount scaling factor (total_active / raw_count).
            For most classes: class_total / class_raw_count.
            For ECO/ESO/Judges: shared_total / combined_raw_count.
        start_year: Valuation year.

    Returns:
        Long-format DataFrame: entry_year, entry_age, age, yos, count, entry_salary
    """
    growth_col = _get_salary_growth_col(class_name)

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

    # Pivot salary and headcount to long format
    sal_long = salary_wide.melt(id_vars="age", var_name="yos", value_name="salary")
    sal_long["yos"] = sal_long["yos"].astype(float).astype(int)

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


def build_salary_benefit_table(
    salary_headcount: pd.DataFrame,
    entrant_profile: pd.DataFrame,
    salary_growth: pd.DataFrame,
    class_name: str,
    constants: ModelConstants,
    get_tier: Callable,
) -> pd.DataFrame:
    """
    Build the salary/benefit table for all cohorts.

    For each (entry_year, entry_age, yos): salary, FAS, db_ee_balance.

    Args:
        salary_headcount: Output of build_salary_headcount_table().
        entrant_profile: Output of build_entrant_profile().
        salary_growth: Salary growth table with yos and class column.
        class_name: Membership class name.
        constants: Model constants.
        get_tier: Callable(class_name, entry_year, age, yos) -> tier string.

    Returns:
        DataFrame: entry_year, entry_age, yos, term_age, tier_at_term_age,
                   salary, fas, db_ee_balance, cumprod_salary_increase
    """
    r = constants.ranges
    econ = constants.economic
    ben = constants.benefit

    # Salary growth for this class: extend to full yos range, then cumprod
    growth_col = _get_salary_growth_col(class_name)
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
    max_hist_year = salary_headcount["entry_year"].max()
    df["salary"] = np.where(
        df["entry_year"] <= max_hist_year,
        df["entry_salary"] * df["cumprod_salary_increase"],
        df["start_sal"] * df["cumprod_salary_increase"]
        * (1 + econ.payroll_growth) ** (df["entry_year"] - max_hist_year),
    )

    # FAS period depends on tier
    df["fas_period"] = np.where(df["tier_at_term_age"].str.contains("tier_1"), 5, 8)

    # Drop rows with NaN salary (entry_age not in profile)
    df = df[df["salary"].notna()].copy()

    # Compute FAS and db_ee_balance within each (entry_year, entry_age) group.
    # FAS = lagged rolling mean of salary (window = fas_period, NOT including current)
    # db_ee_balance = cumulative contributions with lag (balance[0]=0, balance[i]=sum of contribs[0..i-1])
    df = df.sort_values(["entry_year", "entry_age", "yos"]).reset_index(drop=True)
    grp_keys = ["entry_year", "entry_age"]
    g = df.groupby(grp_keys)

    # FAS: R's baseR.rollmean computes mean of PREVIOUS fas_period values (lagged)
    # For tier_1 (fas_period=5), FAS[t] = mean(salary[t-5:t])
    # Use the first fas_period in each group (R does same)
    first_fas = g["fas_period"].transform("first").astype(int)

    # Compute FAS using rolling on shifted salary within groups
    # Shift salary by 1 within group (lag), then rolling mean
    sal_shifted = g["salary"].shift(1)
    # For each unique fas_period, compute rolling mean separately
    df["fas"] = np.nan
    for fp in df["fas_period"].unique():
        mask = first_fas == fp
        if mask.any():
            # Rolling mean of lagged salary with window=fp, min_periods=1
            rolled = sal_shifted.where(mask).groupby([df.loc[mask, c] for c in grp_keys]).rolling(fp, min_periods=1).mean()
            df.loc[rolled.index.get_level_values(-1), "fas"] = rolled.values

    # db_ee_balance: cumsum of lagged contributions
    # balance[0] = 0, balance[i] = balance[i-1]*(1+rate) + contrib[i-1]
    # With rate=0: balance[i] = sum(contrib[0:i])
    df["_contrib"] = ben.db_ee_cont_rate * df["salary"]
    contrib_shifted = df.groupby(grp_keys)["_contrib"].shift(1, fill_value=0)
    df["db_ee_balance"] = contrib_shifted.groupby([df[c] for c in grp_keys]).cumsum()
    df = df.drop(columns=["_contrib"])
    df = df[df["salary"].notna()].copy()

    result = df[["entry_year", "entry_age", "yos", "term_age", "tier_at_term_age",
                 "salary", "fas", "db_ee_balance", "cumprod_salary_increase"]].reset_index(drop=True)
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
    constants: ModelConstants,
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
        df["yos"].values, r.new_year,
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


# Need the vectorized tier function here
def get_tier_vectorized(class_name, entry_year, age, yos, new_year=2024):
    """Vectorized get_tier using the imported tier_logic module."""
    from pension_model.core.tier_logic import get_tier as _get_tier
    n = len(entry_year)
    result = np.empty(n, dtype=object)
    for i in range(n):
        result[i] = _get_tier(class_name, int(entry_year[i]), int(age[i]), int(yos[i]), new_year)
    return result


# ---------------------------------------------------------------------------
# 3. Annuity factor table (cumulative survival × discount)
# ---------------------------------------------------------------------------

def build_ann_factor_table(
    mort_table: pd.DataFrame,
    class_name: str,
    constants: ModelConstants,
) -> pd.DataFrame:
    """
    Build annuity factor table from mortality table.

    For each (entry_year, entry_age, yos) group, compute cumulative
    mortality-adjusted discount factors and annuity factors.

    Args:
        mort_table: Mortality table with columns:
            entry_year, entry_age, dist_year, dist_age, yos, term_year,
            mort_final, tier_at_dist_age
        constants: Model constants.

    Returns:
        DataFrame with additional columns: dr, cola, cum_dr, cum_mort,
            cum_mort_dr, cum_cola, cum_mort_dr_cola, ann_factor
    """
    ben = constants.benefit
    econ = constants.economic

    df = mort_table.copy()

    # Discount rate depends on tier
    df["dr"] = np.where(df["tier_at_dist_age"].str.contains("tier_3"), econ.dr_new, econ.dr_current)

    # COLA depends on tier
    # Tier 1: cola_tier_1_active (prorated by pre-2011 YOS unless constant)
    # Tier 2: cola_tier_2_active
    # Tier 3: cola_tier_3_active
    is_tier1 = df["tier_at_dist_age"].str.contains("tier_1")
    is_tier2 = df["tier_at_dist_age"].str.contains("tier_2")
    is_tier3 = df["tier_at_dist_age"].str.contains("tier_3")

    if ben.cola_tier_1_active_constant:
        cola_tier1 = ben.cola_tier_1_active
    else:
        # Prorated: cola * yos_before_2011 / total_yos
        yos_b4_2011 = np.clip(2011 - df["entry_year"].values, 0, df["yos"].values)
        cola_tier1 = np.where(
            df["yos"] > 0,
            ben.cola_tier_1_active * yos_b4_2011 / df["yos"],
            0.0,
        )

    df["cola"] = np.where(is_tier1, cola_tier1,
                 np.where(is_tier2, ben.cola_tier_2_active,
                 np.where(is_tier3, ben.cola_tier_3_active, 0.0)))

    # Compute cumulative factors within each (entry_year, entry_age, yos) group.
    # Vectorized: sort by group + dist_age, then use shift/cumprod within groups.
    group_cols = ["entry_year", "entry_age", "yos"]
    df = df.sort_values(group_cols + ["dist_age"]).reset_index(drop=True)

    # Lagged values: shift within each group, fill first row with 0
    g = df.groupby(group_cols)
    dr_lagged = g["dr"].shift(1, fill_value=0.0)
    mort_lagged = g["mort_final"].shift(1, fill_value=0.0)
    cola_lagged = g["cola"].shift(1, fill_value=0.0)

    # Cumulative products within groups
    df["cum_dr"] = (1 + dr_lagged).groupby([df[c] for c in group_cols]).cumprod()
    df["cum_mort"] = (1 - mort_lagged).groupby([df[c] for c in group_cols]).cumprod()
    df["cum_cola"] = (1 + cola_lagged).groupby([df[c] for c in group_cols]).cumprod()

    df["cum_mort_dr"] = df["cum_mort"] / df["cum_dr"]
    df["cum_mort_dr_cola"] = df["cum_mort_dr"] * df["cum_cola"]

    # ann_factor = reverse_cumsum(cum_mort_dr_cola) / cum_mort_dr_cola within each group.
    # Reverse cumsum trick: total_group_sum - cumsum + current_value = reverse cumsum.
    grp = df.groupby(group_cols)["cum_mort_dr_cola"]
    group_total = grp.transform("sum")
    cum_forward = grp.cumsum()
    rev_cumsum = group_total - cum_forward + df["cum_mort_dr_cola"]
    df["ann_factor"] = rev_cumsum / df["cum_mort_dr_cola"]
    df["class_name"] = class_name
    return df


# ---------------------------------------------------------------------------
# 4. Benefit table (db_benefit, pvfb_db_at_term_age)
# ---------------------------------------------------------------------------

def build_benefit_table(
    ann_factor_table: pd.DataFrame,
    salary_benefit_table: pd.DataFrame,
    class_name: str,
    constants: ModelConstants,
    get_ben_mult: Callable,
    get_reduce_factor: Callable,
) -> pd.DataFrame:
    """
    Build benefit table combining annuity factors with salary/benefit data.

    Args:
        ann_factor_table: Output of build_ann_factor_table().
        salary_benefit_table: Output of build_salary_benefit_table().
        class_name: Membership class name.
        constants: Model constants.
        get_ben_mult: Callable(class_name, tier, dist_age, yos, dist_year) -> multiplier
        get_reduce_factor: Callable(class_name, tier, dist_age) -> reduction factor

    Returns:
        DataFrame with db_benefit, ann_factor_term, pvfb_db_at_term_age added.
    """
    cal = constants.benefit.cal_factor

    df = ann_factor_table.copy()
    df["term_age"] = df["entry_age"] + df["yos"]

    # Join salary/benefit data for FAS and db_ee_balance
    sbt_cols = ["entry_year", "entry_age", "yos", "term_age", "fas", "db_ee_balance"]
    df = df.merge(
        salary_benefit_table[sbt_cols].drop_duplicates(),
        on=["entry_year", "entry_age", "yos", "term_age"],
        how="left",
    )

    # Compute benefit multiplier and reduction factor
    # Use vectorized loop over arrays for performance (3M rows too slow with df.apply)
    tiers = df["tier_at_dist_age"].values
    dist_ages = df["dist_age"].values.astype(int)
    yos_vals = df["yos"].values.astype(int)
    dist_years = df["dist_year"].values.astype(int)
    n = len(df)
    ben_mult_arr = np.full(n, np.nan)
    reduce_arr = np.full(n, np.nan)
    for i in range(n):
        ben_mult_arr[i] = get_ben_mult(class_name, tiers[i], dist_ages[i], yos_vals[i], dist_years[i])
        reduce_arr[i] = get_reduce_factor(class_name, tiers[i], dist_ages[i])
    df["ben_mult"] = ben_mult_arr
    df["reduce_factor"] = reduce_arr

    # db_benefit = yos * ben_mult * fas * reduce_factor * cal_factor
    df["db_benefit"] = df["yos"] * df["ben_mult"] * df["fas"] * df["reduce_factor"] * cal

    # ann_factor_term = ann_factor * cum_mort_dr (at termination age)
    df["ann_factor_term"] = df["ann_factor"] * df["cum_mort_dr"]

    # pvfb_db_at_term_age = db_benefit * ann_factor_term
    df["pvfb_db_at_term_age"] = df["db_benefit"] * df["ann_factor_term"]

    df["class_name"] = class_name
    return df


def build_final_benefit_table(benefit_table: pd.DataFrame) -> pd.DataFrame:
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
    bt["is_norm_retire_elig"] = bt["tier_at_dist_age"].str.contains("norm")
    bt["term_age"] = bt["entry_age"] + bt["yos"]

    # Determine distribution age per (entry_year, entry_age, term_age)
    # earliest_norm_retire_age = n() - sum(is_norm_retire_elig) + min(dist_age)
    grp_keys = ["entry_year", "entry_age", "term_age"]
    g = bt.groupby(grp_keys)
    dist_age_df = pd.DataFrame({
        "count": g["is_norm_retire_elig"].transform("count"),
        "norm_count": g["is_norm_retire_elig"].transform("sum"),
        "min_dist_age": g["dist_age"].transform("min"),
        "term_status": g["tier_at_dist_age"].transform("first"),
    })
    dist_age_df["earliest_norm_retire_age"] = dist_age_df["count"] - dist_age_df["norm_count"] + dist_age_df["min_dist_age"]
    # Get one row per group
    dist_age_df = bt[grp_keys].join(dist_age_df).drop_duplicates(subset=grp_keys)

    # For vested (not non_vested): use earliest_norm_retire_age
    # For non_vested and retirees: use term_age
    is_vested = (dist_age_df["term_status"].str.contains("vested")
                 & ~dist_age_df["term_status"].str.contains("non_vested"))
    dist_age_df["dist_age"] = np.where(
        is_vested, dist_age_df["earliest_norm_retire_age"], dist_age_df["term_age"]
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

    return fbt[["entry_year", "entry_age", "term_age", "dist_age",
                "db_benefit", "pvfb_db_at_term_age", "ann_factor_term"]].reset_index(drop=True)


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


def build_benefit_val_table(
    salary_benefit_table: pd.DataFrame,
    benefit_table: pd.DataFrame,
    sep_rate_table: pd.DataFrame,
    class_name: str,
    constants: ModelConstants,
    get_sep_type: Callable,
) -> pd.DataFrame:
    """
    Build benefit valuation table with PVFB, PVFS, and normal cost.

    Args:
        salary_benefit_table: Output of build_salary_benefit_table().
        benefit_table: Output of build_benefit_table() — needs final_benefit_table subset.
        sep_rate_table: Separation rate table with columns:
            entry_year, entry_age, term_age, yos, term_year,
            separation_rate, remaining_prob
        constants: Model constants.
        get_sep_type: Callable(tier_str) -> "retire"|"vested"|"non_vested"

    Returns:
        DataFrame with pvfb_db_wealth_at_current_age, pvfs_at_current_age,
            indv_norm_cost, pvfnc_db
    """
    r = constants.benefit.retire_refund_ratio
    econ = constants.economic

    # Build final_benefit_table: for each (entry_year, entry_age, term_age),
    # pick the distribution age where benefit is collected
    # This is complex — delegated to build_final_benefit_table()

    # Start from salary_benefit_table
    sbt = salary_benefit_table.copy()
    sbt["term_year"] = sbt["entry_year"] + sbt["yos"]

    # Join final_benefit_table
    fbt = benefit_table  # Assumes already filtered to final dist_age
    sbt = sbt.merge(
        fbt[["entry_year", "entry_age", "term_age", "db_benefit",
             "pvfb_db_at_term_age"]].drop_duplicates(),
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
    sbt["pvfb_db_wealth_at_term_age"] = np.where(
        sbt["sep_type"] == "retire", sbt["pvfb_db_at_term_age"],
        np.where(
            sbt["sep_type"] == "vested",
            r * sbt["pvfb_db_at_term_age"] + (1 - r) * sbt["db_ee_balance"],
            sbt["db_ee_balance"],  # non_vested
        ),
    )

    # Compute PVFB, PVFS, NC within each (entry_year, entry_age) group
    def _compute_pv(g):
        g = g.sort_values("yos")
        sep = g["separation_rate"].values.astype(float)
        rp = g["remaining_prob"].values.astype(float)
        dr = g["dr"].values.astype(float)
        val = g["pvfb_db_wealth_at_term_age"].values.astype(float)
        sal = g["salary"].values.astype(float)

        # Replace NaN with 0
        val = np.nan_to_num(val, 0.0)
        sep = np.nan_to_num(sep, 0.0)
        rp = np.nan_to_num(rp, 0.0)

        pvfb = _get_pvfb(sep, dr, val)
        pvfs = _get_pvfs(rp, dr, sal)

        nc_rate = pvfb[0] / pvfs[0] if pvfs[0] > 0 else 0.0

        g["pvfb_db_wealth_at_current_age"] = pvfb
        g["pvfs_at_current_age"] = pvfs
        g["indv_norm_cost"] = nc_rate
        g["pvfnc_db"] = nc_rate * pvfs
        return g

    result_parts = []
    for _, g in sbt.groupby(["entry_year", "entry_age"]):
        result_parts.append(_compute_pv(g))
    sbt = pd.concat(result_parts, ignore_index=True)
    sbt["class_name"] = class_name
    return sbt
