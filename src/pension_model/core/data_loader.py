"""
Generic stage 3 data loader.

Reads standardized CSV files from data/{plan}/ and returns inputs for
build_plan_benefit_tables() / run_plan_pipeline().

Entry points:
  - load_plan_inputs(constants, baseline_dir): plan-wide stacked loader.
    Returns (plan_inputs, class_meta). plan_inputs has stacked DataFrames
    with categorical class_name for the benefit-tables stage. class_meta
    has per-class objects (CompactMortality, ann_factor_retire, etc.)
    for the workforce/liability stage.
  - load_plan_data(class_name, constants): per-class loader (called
    internally by load_plan_inputs; still available for debugging).
"""
from pathlib import Path
import pandas as pd
import numpy as np

from pension_model.plan_config import PlanConfig


def _load_retiree_distribution(path: Path) -> pd.DataFrame:
    """Load retiree distribution with computed ratio columns.

    Stage 3 format has: age, count, avg_benefit, total_benefit
    Pipeline expects: age, n_retire, total_ben, avg_ben, n_retire_ratio, total_ben_ratio
    """
    df = pd.read_csv(path)
    # Map stage 3 column names to pipeline names
    rename = {}
    if "count" in df.columns:
        rename["count"] = "n_retire"
    if "avg_benefit" in df.columns:
        rename["avg_benefit"] = "avg_ben"
    if "total_benefit" in df.columns:
        rename["total_benefit"] = "total_ben"
    if rename:
        df = df.rename(columns=rename)

    # Compute ratio columns if not present
    if "n_retire_ratio" not in df.columns and "n_retire" in df.columns:
        total_n = df["n_retire"].sum()
        df["n_retire_ratio"] = df["n_retire"] / total_n if total_n > 0 else 0
    if "total_ben_ratio" not in df.columns and "total_ben" in df.columns:
        total_b = df["total_ben"].sum()
        df["total_ben_ratio"] = df["total_ben"] / total_b if total_b > 0 else 0

    return df


def load_plan_data(
    class_name: str,
    constants: PlanConfig,
) -> dict:
    """Load stage 3 data for a plan class.

    Each class owns its own decrement files ({class_name}_*.csv in the
    decrements directory). There is no sep_class indirection.

    Args:
        class_name: Membership class (e.g., 'regular', 'all')
        constants: Plan configuration

    Returns:
        dict with keys: salary, headcount, salary_growth,
            retiree_distribution, ann_factor_retire, _compact_mortality,
            and decrement keys (either term_rate_avg + retire tables,
            or _separation_rate + _entrant_profile + _reduction_tables)
    """
    data_dir = constants.resolve_data_dir()
    demo_dir = data_dir / "demographics"
    decr_dir = data_dir / "decrements"
    mort_dir = data_dir / "mortality"

    # --- Demographics (stage 3 long format) ---
    inputs = {
        "salary": pd.read_csv(demo_dir / f"{class_name}_salary.csv"),
        "headcount": pd.read_csv(demo_dir / f"{class_name}_headcount.csv"),
        "retiree_distribution": _load_retiree_distribution(demo_dir / "retiree_distribution.csv"),
    }

    # Salary growth: try class-specific first, then shared
    sg_path = demo_dir / f"{class_name}_salary_growth.csv"
    if not sg_path.exists():
        sg_path = demo_dir / "salary_growth.csv"
    inputs["salary_growth"] = pd.read_csv(sg_path)

    # Optional entrant profile
    ep_path = demo_dir / "entrant_profile.csv"
    if ep_path.exists():
        ep = pd.read_csv(ep_path)
        # Normalize column names to what pipeline expects
        if "start_salary" in ep.columns:
            ep = ep.rename(columns={"start_salary": "start_sal"})
        inputs["_entrant_profile"] = ep

    # --- Mortality (stage 3 CSV) ---
    cm = _build_mortality_from_csv(constants, mort_dir, class_name)
    from pension_model.core.mortality_builder import build_ann_factor_retire_table
    afr = build_ann_factor_retire_table(
        cm, class_name, constants.ranges.start_year, constants.ranges.model_period,
        constants.economic.dr_current, constants.benefit.cola_current_retire,
    )
    inputs["ann_factor_retire"] = afr
    inputs["_compact_mortality"] = cm

    # --- Decrements (stage 3 standard format) ---
    _load_decrements(inputs, constants, decr_dir, class_name)

    return inputs


def _build_mortality_from_csv(
    constants: PlanConfig,
    mort_dir: Path,
    class_name: str,
) -> "CompactMortality":
    """Build CompactMortality from stage 3 CSV files."""
    from pension_model.core.mortality_builder import build_compact_mortality_from_csv

    base_path = mort_dir / "base_rates.csv"
    imp_path = mort_dir / "improvement_scale.csv"

    # Determine table name from config: per-class map takes precedence
    # (for multi-class plans with different base tables). Otherwise fall back
    # to the plan-wide mortality.base_table setting (single-table plans).
    base_table_map = constants.raw.get("base_table_map", {})
    if class_name in base_table_map:
        table_name = base_table_map[class_name]
    else:
        mort_cfg = constants.raw.get("mortality", {})
        base_table_label = mort_cfg.get("base_table", "general")
        # Map verbose config labels to CSV table names
        table_name_map = {
            "pub_2010_teacher_below_median": "teacher_below_median",
            "pub_2010_teacher": "teacher",
            "pub_2010_general_headcount": "general",
            "pub_2010_safety": "safety",
        }
        table_name = table_name_map.get(base_table_label, base_table_label)

    mp_shift = getattr(constants, "male_mp_forward_shift", 0)
    max_age = constants.ranges.max_age if hasattr(constants.ranges, "max_age") else 120
    max_year = (constants.ranges.start_year + constants.ranges.model_period
                + max_age - constants.ranges.min_age)

    return build_compact_mortality_from_csv(
        base_path, imp_path,
        class_name, table_name=table_name,
        min_age=constants.ranges.min_age,
        max_age=max_age,
        max_year=max_year,
        constants=constants,
        male_mp_forward_shift=mp_shift,
    )


def _load_decrements(
    inputs: dict,
    constants: PlanConfig,
    decr_dir: Path,
    class_name: str,
):
    """Load decrement data from stage 3 CSVs.

    Reads {class_name}_termination_rates.csv and
    {class_name}_retirement_rates.csv in the standard lookup_type format,
    falling back to unprefixed filenames for single-class plans.

    For plans with years_from_nr termination rates, builds the full
    separation rate table directly.

    For plans with yos-only termination rates, converts back to the
    term_rate_avg + retirement rate table format.
    """
    term_path = decr_dir / f"{class_name}_termination_rates.csv"
    if not term_path.exists():
        term_path = decr_dir / "termination_rates.csv"

    term_df = pd.read_csv(term_path)

    ret_path = decr_dir / f"{class_name}_retirement_rates.csv"
    if not ret_path.exists():
        ret_path = decr_dir / "retirement_rates.csv"

    ret_df = pd.read_csv(ret_path)

    # Check if plan has years_from_nr termination rates
    has_years_from_nr = "years_from_nr" in term_df["lookup_type"].values

    if has_years_from_nr:
        # Years-from-normal-retirement lookup: build separation rate table
        _build_years_from_nr_decrements(inputs, constants, term_df, ret_df, decr_dir, class_name)
    else:
        # YOS-only lookup: convert to wide format for existing builder
        _build_yos_only_decrements(inputs, constants, term_df, ret_df)


def _resolve_age_group_breaks(constants: PlanConfig) -> list:
    """Parse ``modeling.age_groups`` config into (min, max, label) tuples.

    Each group entry in config has a ``label`` plus optional ``min_age``
    and ``max_age`` (either bound can be omitted to mean open-ended).
    Returned tuples use ``-np.inf`` / ``np.inf`` for the omitted bounds,
    matching the classification logic in ``_age_to_group`` below.

    Required for plans with YOS-only termination rate tables. Raises
    ValueError with a clear message if the config field is missing.
    """
    raw = constants.raw if hasattr(constants, "raw") else {}
    groups_cfg = raw.get("modeling", {}).get("age_groups")
    if not groups_cfg:
        raise ValueError(
            "modeling.age_groups is required in plan config when the "
            "plan uses YOS-only termination rate tables. See "
            "plans/frs/config/plan_config.json for an example schema."
        )
    breaks = []
    for g in groups_cfg:
        lo = g.get("min_age", -np.inf)
        hi = g.get("max_age", np.inf)
        breaks.append((lo, hi, g["label"]))
    return breaks


def _build_yos_only_decrements(
    inputs: dict,
    constants: PlanConfig,
    term_df: pd.DataFrame,
    ret_df: pd.DataFrame,
):
    """Convert stage 3 YOS-only termination rates to wide decrement format.

    The existing build_separation_rate_table() expects:
      - term_rate_avg: yos × age_group wide format
      - normal_retire_tier1/2: age × rate
      - early_retire_tier1/2: age × rate

    Age group bands are read from ``modeling.age_groups`` in plan config
    via ``_resolve_age_group_breaks``.
    """
    # Convert termination rates: (lookup_type=yos, age, lookup_value, term_rate) → wide format
    yos_rates = term_df[term_df["lookup_type"] == "yos"].copy()

    # Age groups come from plan config, not hardcoded
    age_group_breaks = _resolve_age_group_breaks(constants)
    age_group_labels = [label for _, _, label in age_group_breaks]
    default_label = age_group_labels[-1]

    def _age_to_group(age):
        for lo, hi, label in age_group_breaks:
            if lo <= age <= hi:
                return label
        return default_label

    yos_rates["age_group"] = yos_rates["age"].apply(_age_to_group)

    # Within each (yos, age_group), rates should be identical (same rate per group)
    # Take the first value
    grouped = yos_rates.groupby(["lookup_value", "age_group"])["term_rate"].first().reset_index()
    grouped = grouped.rename(columns={"lookup_value": "yos"})

    # Pivot to wide: yos rows, age_group columns
    term_wide = grouped.pivot(index="yos", columns="age_group", values="term_rate").reset_index()
    # Ensure column order matches the config-declared group order
    expected_cols = ["yos", *age_group_labels]
    for col in expected_cols:
        if col not in term_wide.columns:
            term_wide[col] = 0.0
    term_wide = term_wide[expected_cols]

    inputs["term_rate_avg"] = term_wide

    # Convert retirement rates: (age, tier, retire_type, retire_rate) → per-tier DataFrames
    for tier_name, tier_key in [("tier_1", "tier1"), ("tier_2", "tier2")]:
        for ret_type, input_key in [("normal", f"normal_retire_{tier_key}"),
                                     ("early", f"early_retire_{tier_key}")]:
            mask = (ret_df["tier"] == tier_name) & (ret_df["retire_type"] == ret_type)
            subset = ret_df[mask][["age", "retire_rate"]].copy()
            rate_col = f"{ret_type}_retire_rate"
            subset = subset.rename(columns={"retire_rate": rate_col})
            inputs[input_key] = subset


def _build_years_from_nr_decrements(
    inputs: dict,
    constants: PlanConfig,
    term_df: pd.DataFrame,
    ret_df: pd.DataFrame,
    decr_dir: Path,
    class_name: str,
):
    """Build separation rate table using years-from-normal-retirement lookup.

    Uses the existing build_txtrs_separation_rate_table logic but reads
    from CSV instead of Excel.
    """
    from pension_model.plan_config import get_tier

    r = constants.ranges
    yos_rates = term_df[term_df["lookup_type"] == "yos"].copy()
    nr_rates = term_df[term_df["lookup_type"] == "years_from_nr"].copy()

    # Build before10 and after10 tables for years-from-NR separation rate logic
    before10 = yos_rates[["lookup_value", "term_rate"]].copy()
    before10 = before10.rename(columns={"lookup_value": "yos"})

    after10 = nr_rates[["lookup_value", "term_rate"]].copy()
    after10 = after10.rename(columns={"lookup_value": "years_from_nr"})

    # Retirement rates: extract normal and reduced (early) rates
    normal_mask = ret_df["retire_type"] == "normal"
    early_mask = ret_df["retire_type"] == "early"
    retire_rates = pd.DataFrame({
        "age": ret_df[normal_mask]["age"].values,
        "normal_rate": ret_df[normal_mask]["retire_rate"].values,
    })
    early_rates = ret_df[early_mask][["age", "retire_rate"]].rename(
        columns={"retire_rate": "reduced_rate"})
    retire_rates = retire_rates.merge(early_rates, on="age", how="outer").fillna(0)

    # Get entrant profile for entry_ages
    if "_entrant_profile" in inputs:
        entry_ages = set(inputs["_entrant_profile"]["entry_age"].values)
    else:
        # Derive from headcount
        hc = inputs["headcount"]
        entry_ages = set((hc["age"] - hc["yos"]).unique())

    # Build the grid (same logic as build_txtrs_separation_rate_table)
    rows = []
    for ey in r.entry_year_range:
        for ta in r.age_range:
            for yos in r.yos_range:
                ea = ta - yos
                if ea in entry_ages:
                    rows.append((ey, ta, yos, ea, ey + yos))

    df = pd.DataFrame(rows, columns=["entry_year", "term_age", "yos", "entry_age", "term_year"])
    df = df.sort_values(["entry_year", "entry_age", "term_age"]).reset_index(drop=True)

    # Determine tier
    tiers = np.empty(len(df), dtype=object)
    for i in range(len(df)):
        tiers[i] = get_tier(
            constants, class_name,
            int(df.iloc[i]["entry_year"]), int(df.iloc[i]["term_age"]),
            int(df.iloc[i]["yos"]),
            entry_age=int(df.iloc[i]["entry_age"]),
        )
    df["tier"] = tiers

    df["is_normal_retire"] = df["tier"].str.contains("norm")
    df["is_early_retire"] = df["tier"].str.contains("early|reduced")

    # Find years from normal retirement
    first_normal = df[df["is_normal_retire"]].groupby(
        ["entry_year", "entry_age"])["term_age"].min().reset_index()
    first_normal = first_normal.rename(columns={"term_age": "first_normal_age"})
    df = df.merge(first_normal, on=["entry_year", "entry_age"], how="left")
    df["first_normal_age"] = df["first_normal_age"].fillna(r.max_age)
    df["years_from_nr"] = (df["first_normal_age"] - df["term_age"]).clip(lower=0).astype(int)

    # Join rates
    df = df.merge(before10[["yos", "term_rate"]].rename(columns={"term_rate": "before10_rate"}),
                  on="yos", how="left")
    df = df.merge(after10[["years_from_nr", "term_rate"]].rename(columns={"term_rate": "after10_rate"}),
                  on="years_from_nr", how="left")
    df = df.merge(retire_rates, left_on="term_age", right_on="age", how="left")
    df = df.drop(columns=["age"], errors="ignore")

    for c in ["before10_rate", "after10_rate", "reduced_rate", "normal_rate"]:
        df[c] = df[c].fillna(0)

    df["separation_rate"] = np.where(
        df["is_normal_retire"], df["normal_rate"],
        np.where(
            df["is_early_retire"], df["reduced_rate"],
            np.where(
                df["yos"] < 10, df["before10_rate"],
                df["after10_rate"],
            ),
        ),
    )

    # Compute remaining_prob and separation_prob
    df = df.sort_values(["entry_year", "entry_age", "yos"]).reset_index(drop=True)
    grp = df.groupby(["entry_year", "entry_age"])
    sep_lagged = grp["separation_rate"].shift(1, fill_value=0.0)
    df["remaining_prob"] = (1 - sep_lagged).groupby(
        [df["entry_year"], df["entry_age"]]).cumprod()
    rp_lagged = grp["remaining_prob"].shift(1, fill_value=1.0)
    df["separation_prob"] = rp_lagged - df["remaining_prob"]

    df["class_name"] = class_name
    inputs["_separation_rate"] = df[
        ["entry_year", "entry_age", "term_age", "yos", "term_year",
         "separation_rate", "remaining_prob", "separation_prob",
         "class_name"]
    ].reset_index(drop=True)

    # Load reduction tables if they exist
    gft_path = decr_dir / "reduction_gft.csv"
    others_path = decr_dir / "reduction_others.csv"
    if gft_path.exists() and others_path.exists():
        gft = pd.read_csv(gft_path)
        # Pivot back to wide format expected by get_reduce_factor
        gft_wide = gft.pivot(index="yos", columns="age", values="reduce_factor").reset_index()
        gft_wide.columns = ["yos"] + [int(c) for c in gft_wide.columns[1:]]

        others = pd.read_csv(others_path)
        others = others[["age", "reduce_factor"]]
        inputs["_reduction_tables"] = {"reduced_gft": gft_wide, "reduced_others": others}


# ---------------------------------------------------------------------------
# Plan-wide stacked loader
# ---------------------------------------------------------------------------

def load_plan_inputs(constants: PlanConfig) -> dict:
    """Load stage 3 data for an entire plan.

    This is the recommended entry point. Calls load_plan_data once per
    class, attaches plan-wide reduction tables to ``constants``, and
    returns the per-class inputs dicts that downstream functions
    (build_plan_benefit_tables, _project_and_aggregate_class) consume.

    Args:
        constants: PlanConfig for the plan. Modified in place to attach
            ``_reduce_tables`` if the plan provides reduction tables.

    Returns:
        {class_name: inputs dict from load_plan_data}
    """
    classes = list(constants.classes)

    raw_inputs_by_class: dict = {}

    for cn in classes:
        inputs = load_plan_data(cn, constants)
        raw_inputs_by_class[cn] = inputs

    # Attach reduction tables (early-retire factor lookup) to config.
    # These are plan-wide, not per-class; take from the first class that
    # provides them.
    for cn in classes:
        rt = raw_inputs_by_class[cn].get("_reduction_tables")
        if rt is not None:
            object.__setattr__(constants, "_reduce_tables", rt)
            break

    return raw_inputs_by_class
