"""
TRS (Texas Teacher Retirement System) data loader.

Reads input data from TxTRS_BM_Inputs.xlsx and external mortality files,
producing the inputs dict expected by build_plan_benefit_tables / run_plan_pipeline.

Key differences from FRS:
  - Single class "all" (no per-class CSVs)
  - All decrement data in one Excel workbook
  - Termination rates: before-10 by YOS, after-10 by years-from-normal-retirement
  - Retirement rates: by age (normal/reduced × male/female, averaged)
  - Mortality: Pub-2010 teacher below-median + MP-2021
"""

from pathlib import Path
import numpy as np
import pandas as pd

from pension_model.plan_config import PlanConfig, get_tier


# ---------------------------------------------------------------------------
# Salary / headcount / salary growth
# ---------------------------------------------------------------------------

def load_txtrs_salary_headcount(xlsx_path: Path):
    """Load salary and headcount matrices from TxTRS_BM_Inputs.xlsx.

    Returns (salary_wide, headcount_wide) DataFrames in the format
    expected by build_salary_headcount_table: 'age' column + yos columns.
    """
    sal = pd.read_excel(xlsx_path, sheet_name="Salary Matrix", header=None)
    hc = pd.read_excel(xlsx_path, sheet_name="Head Count Matrix", header=None)

    def _clean_matrix(df):
        # Row 0 has column headers: Age, yos_bin_1, yos_bin_2, ...
        # Row 1+ has data
        headers = df.iloc[0].tolist()
        headers[0] = "age"
        # Convert YOS bin headers to int
        headers = [int(float(h)) if i > 0 and pd.notna(h) else h for i, h in enumerate(headers)]
        body = df.iloc[1:].copy()
        body.columns = headers
        # Drop any all-NaN columns
        body = body.dropna(axis=1, how="all")
        # Convert to numeric
        for c in body.columns:
            body[c] = pd.to_numeric(body[c], errors="coerce")
        body = body.dropna(subset=["age"]).reset_index(drop=True)
        body["age"] = body["age"].astype(int)
        return body

    return _clean_matrix(sal), _clean_matrix(hc)


def load_txtrs_salary_growth(xlsx_path: Path) -> pd.DataFrame:
    """Load salary growth by YOS, producing a table with 'yos' and 'salary_increase_all'."""
    df = pd.read_excel(xlsx_path, sheet_name="Salary Growth YOS")
    # Columns: YOS, salary_increase (or similar)
    df.columns = ["yos", "salary_increase_all"]
    df["yos"] = df["yos"].astype(int)
    df["salary_increase_all"] = pd.to_numeric(df["salary_increase_all"], errors="coerce")
    return df


def load_txtrs_entrant_profile(xlsx_path: Path) -> pd.DataFrame:
    """Load entrant profile from TxTRS_BM_Inputs.xlsx.

    Returns DataFrame with entry_age, count, start_sal columns.
    """
    df = pd.read_excel(xlsx_path, sheet_name="Entrant Profile", header=None)
    # Row 0 is headers: entry_age, Count, start_sal, ...
    # Row 1+ is data
    body = df.iloc[1:].copy().reset_index(drop=True)
    body = body.iloc[:, :3]  # first 3 columns
    body.columns = ["entry_age", "count", "start_sal"]
    for c in body.columns:
        body[c] = pd.to_numeric(body[c], errors="coerce")
    body = body.dropna(subset=["entry_age"]).reset_index(drop=True)
    body["entry_age"] = body["entry_age"].astype(int)
    return body


# ---------------------------------------------------------------------------
# Retiree distribution
# ---------------------------------------------------------------------------

def load_txtrs_retiree_distribution(xlsx_path: Path) -> pd.DataFrame:
    """Load retiree distribution table."""
    df = pd.read_excel(xlsx_path, sheet_name="Retiree Distribution")
    # Expected columns: age, n.retire, total_ben, avg_ben, n.retire_ratio, total_ben_ratio
    df.columns = [c.strip().replace(".", "_") for c in df.columns]
    # Rename to match pipeline expectations
    col_map = {
        "age": "age",
        "n_retire": "n_retire",
        "total_ben": "total_ben",
        "avg_ben": "avg_ben",
        "n_retire_ratio": "n_retire_ratio",
        "total_ben_ratio": "total_ben_ratio",
    }
    result = df.rename(columns=col_map)
    for c in result.columns:
        result[c] = pd.to_numeric(result[c], errors="coerce")
    result = result.dropna(subset=["age"])
    result["age"] = result["age"].astype(int)
    return result


# ---------------------------------------------------------------------------
# Reduction tables (early retirement)
# ---------------------------------------------------------------------------

def load_txtrs_reduction_tables(xlsx_path: Path) -> dict:
    """Load early retirement reduction factor tables.

    Returns dict with 'reduced_gft' and 'reduced_others' DataFrames.
    """
    gft = pd.read_excel(xlsx_path, sheet_name="Reduced GFT")
    # Row 0 is header: YOS, age_55, age_56, ..., age_60
    gft.columns = [str(c).strip() for c in gft.columns]
    first_col = gft.columns[0]
    gft = gft.rename(columns={first_col: "yos"})
    for c in gft.columns:
        gft[c] = pd.to_numeric(gft[c], errors="coerce")
    gft = gft.dropna(subset=["yos"]).reset_index(drop=True)
    gft["yos"] = gft["yos"].astype(int)

    others = pd.read_excel(xlsx_path, sheet_name="Reduced Others")
    others.columns = ["age", "reduce_factor"]
    for c in others.columns:
        others[c] = pd.to_numeric(others[c], errors="coerce")
    others = others.dropna(subset=["age"]).reset_index(drop=True)
    others["age"] = others["age"].astype(int)

    return {"reduced_gft": gft, "reduced_others": others}


# ---------------------------------------------------------------------------
# Separation rate table (TRS-specific logic)
# ---------------------------------------------------------------------------

def _load_termination_rates(xlsx_path: Path):
    """Load TRS termination rate tables.

    Returns (before10, after10) DataFrames.
    before10: columns [yos, term_rate]  (male+female averaged)
    after10: columns [years_from_nr, term_rate]  (male+female averaged)
    """
    before = pd.read_excel(xlsx_path, sheet_name="Termination Rates before 10")
    before.columns = [str(c).strip() for c in before.columns]
    # Columns: YOS, TermBefore10Male, TermBefore10Female
    before = before.iloc[:, :3].copy()
    before.columns = ["yos", "term_male", "term_female"]
    for c in before.columns:
        before[c] = pd.to_numeric(before[c], errors="coerce")
    before = before.dropna(subset=["yos"]).reset_index(drop=True)
    before["yos"] = before["yos"].astype(int)
    before["term_rate"] = (before["term_male"] + before["term_female"]) / 2

    after = pd.read_excel(xlsx_path, sheet_name="Termination Rates after 10")
    after.columns = [str(c).strip() for c in after.columns]
    after = after.iloc[:, :3].copy()
    after.columns = ["years_from_nr", "term_male", "term_female"]
    for c in after.columns:
        after[c] = pd.to_numeric(after[c], errors="coerce")
    after = after.dropna(subset=["years_from_nr"]).reset_index(drop=True)
    after["years_from_nr"] = after["years_from_nr"].astype(int)
    after["term_rate"] = (after["term_male"] + after["term_female"]) / 2

    return before, after


def _load_retirement_rates(xlsx_path: Path) -> pd.DataFrame:
    """Load TRS retirement rates.

    Returns DataFrame with columns [age, reduced_rate, normal_rate]
    (male+female averaged).
    """
    df = pd.read_excel(xlsx_path, sheet_name="Retirement Rates")
    # Columns: Age, ReducedMale, ReducedFemale, NormalMale, NormalFemale
    df.columns = [str(c).strip() for c in df.columns]
    df = df.iloc[:, :5].copy()
    df.columns = ["age", "reduced_male", "reduced_female", "normal_male", "normal_female"]
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["age"]).reset_index(drop=True)
    df["age"] = df["age"].astype(int)
    df["reduced_rate"] = (df["reduced_male"] + df["reduced_female"]) / 2
    df["normal_rate"] = (df["normal_male"] + df["normal_female"]) / 2
    return df[["age", "reduced_rate", "normal_rate"]]


def build_txtrs_separation_rate_table(
    xlsx_path: Path,
    entrant_profile: pd.DataFrame,
    constants: PlanConfig,
) -> pd.DataFrame:
    """Build TRS separation rate table.

    TRS logic (from R's TxTRS_R_BModel revised.R lines 409-446):
      - If retirement eligible (normal): use normal retirement rate
      - If retirement eligible (early): use reduced retirement rate
      - If YOS < 10: use TermBefore10 rate (by YOS, averaged male+female)
      - If YOS >= 10: use TermAfter10 rate (by years from normal retirement)

    Returns DataFrame matching FRS separation_rate table format:
        entry_year, entry_age, term_age, yos, term_year,
        separation_rate, remaining_prob, separation_prob, class_name
    """
    before10, after10 = _load_termination_rates(xlsx_path)
    retire_rates = _load_retirement_rates(xlsx_path)

    r = constants.ranges
    entry_ages = set(entrant_profile["entry_age"].values)
    class_name = "all"

    # Build the grid
    rows = []
    for ey in r.entry_year_range:
        for ta in r.age_range:
            for yos in r.yos_range:
                ea = ta - yos
                if ea in entry_ages:
                    rows.append((ey, ta, yos, ea, ey + yos))

    df = pd.DataFrame(rows, columns=["entry_year", "term_age", "yos", "entry_age", "term_year"])
    df = df.sort_values(["entry_year", "entry_age", "term_age"]).reset_index(drop=True)

    # Determine tier for each row using config-driven tier logic
    tiers = np.empty(len(df), dtype=object)
    for i in range(len(df)):
        tiers[i] = get_tier(
            constants, class_name,
            int(df.iloc[i]["entry_year"]), int(df.iloc[i]["term_age"]),
            int(df.iloc[i]["yos"]),
            entry_age=int(df.iloc[i]["entry_age"]),
        )
    df["tier"] = tiers

    # Determine retirement type from tier
    df["is_normal_retire"] = df["tier"].str.contains("norm")
    df["is_early_retire"] = df["tier"].str.contains("early|reduced")

    # Find years from normal retirement for after-10 termination
    # For each (entry_year, entry_age), find the first age at normal retirement
    first_normal = df[df["is_normal_retire"]].groupby(
        ["entry_year", "entry_age"])["term_age"].min().reset_index()
    first_normal = first_normal.rename(columns={"term_age": "first_normal_age"})
    df = df.merge(first_normal, on=["entry_year", "entry_age"], how="left")
    # If never reaches normal retirement, set to max_age
    df["first_normal_age"] = df["first_normal_age"].fillna(r.max_age)
    df["years_from_nr"] = (df["first_normal_age"] - df["term_age"]).clip(lower=0).astype(int)

    # Join rates
    df = df.merge(before10[["yos", "term_rate"]].rename(columns={"term_rate": "before10_rate"}),
                  on="yos", how="left")
    df = df.merge(after10[["years_from_nr", "term_rate"]].rename(columns={"term_rate": "after10_rate"}),
                  on="years_from_nr", how="left")
    df = df.merge(retire_rates, left_on="term_age", right_on="age", how="left")
    df = df.drop(columns=["age"], errors="ignore")

    # Fill NaN rates with 0
    for c in ["before10_rate", "after10_rate", "reduced_rate", "normal_rate"]:
        df[c] = df[c].fillna(0)

    # Apply R's logic: retirement overrides termination
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

    # Compute remaining_prob and separation_prob per (entry_year, entry_age) group
    df = df.sort_values(["entry_year", "entry_age", "yos"]).reset_index(drop=True)
    grp = df.groupby(["entry_year", "entry_age"])
    sep_lagged = grp["separation_rate"].shift(1, fill_value=0.0)
    df["remaining_prob"] = (1 - sep_lagged).groupby(
        [df["entry_year"], df["entry_age"]]).cumprod()
    rp_lagged = grp["remaining_prob"].shift(1, fill_value=1.0)
    df["separation_prob"] = rp_lagged - df["remaining_prob"]

    df["class_name"] = class_name
    return df[["entry_year", "entry_age", "term_age", "yos", "term_year",
               "separation_rate", "remaining_prob", "separation_prob",
               "class_name"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Assemble complete inputs dict
# ---------------------------------------------------------------------------

def build_txtrs_inputs(raw_dir: Path, constants: PlanConfig) -> dict:
    """Build the complete inputs dict for TRS pipeline.

    Args:
        raw_dir: Path to R_model/R_model_txtrs/
        constants: Loaded TRS PlanConfig.

    Returns:
        inputs dict compatible with build_plan_benefit_tables / run_plan_pipeline.
    """
    xlsx_path = raw_dir / "TxTRS_BM_Inputs.xlsx"

    salary_wide, headcount_wide = load_txtrs_salary_headcount(xlsx_path)
    salary_growth = load_txtrs_salary_growth(xlsx_path)
    retiree_dist = load_txtrs_retiree_distribution(xlsx_path)

    # Entrant profile from Excel sheet (R reads this directly, not derived from salary_headcount)
    entrant_raw = load_txtrs_entrant_profile(xlsx_path)
    entrant_profile = entrant_raw.copy()
    entrant_profile["entrant_dist"] = entrant_profile["count"] / entrant_profile["count"].sum()
    entrant_profile = entrant_profile[["entry_age", "start_sal", "entrant_dist"]]

    # Store start_year so the pipeline can set max_hist_year correctly.
    # Without this, new entrant salaries get inflated by (1+payroll_growth)^gap
    # where gap = start_year - max_entry_year_in_headcount.

    # Separation rate table (TRS-specific construction)
    sep = build_txtrs_separation_rate_table(xlsx_path, entrant_raw, constants)

    return {
        "salary": salary_wide,
        "headcount": headcount_wide,
        "salary_growth": salary_growth,
        "retiree_distribution": retiree_dist,
        # Pre-built separation rate table (bypasses FRS's build_separation_rate_table)
        "_separation_rate": sep,
        # Entrant profile from Excel (overrides derived profile)
        "_entrant_profile": entrant_profile,
        # Reduction tables for early retirement factor lookups
        "_reduction_tables": load_txtrs_reduction_tables(xlsx_path),
    }


# ---------------------------------------------------------------------------
# Funding data loader
# ---------------------------------------------------------------------------

def load_txtrs_funding_data(raw_dir: Path) -> dict:
    """Load TRS funding inputs from Excel workbook.

    Reads:
      - "Funding Data" sheet: initial values (1 row) for all funding variables
      - "Return Scenarios" sheet: investment return scenarios by year

    Returns dict with 'init_funding' (DataFrame) and 'return_scenarios' (DataFrame).
    """
    xlsx_path = raw_dir / "TxTRS_BM_Inputs.xlsx"

    init = pd.read_excel(xlsx_path, sheet_name="Funding Data")
    # R reads this as a single-row table; columns become variable names
    # Ensure numeric types
    for col in init.columns:
        init[col] = pd.to_numeric(init[col], errors="coerce").fillna(0)

    ret_scen = pd.read_excel(xlsx_path, sheet_name="Return Scenarios")

    return {
        "init_funding": init,
        "return_scenarios": ret_scen,
    }
