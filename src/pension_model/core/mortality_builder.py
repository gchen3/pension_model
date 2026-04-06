"""
Build mortality tables from raw inputs (Excel or CSV).

Produces a CompactMortality object from:
  - Base mortality tables (PUB-2010 variants: General, Teacher, Safety)
  - Mortality improvement scales (MP-2018, MP-2021, etc.)

Supports two input formats:
  - Excel: legacy path via _read_base_mort_table / _read_mp_table
  - CSV: stage 3 format via build_compact_mortality_from_csv (base_rates.csv + improvement_scale.csv)

The result is a compact (age, year) → rate lookup for employee and retiree
mortality, with class-specific base table selection.

Class → base table mapping (FRS):
  regular: average of General and Teacher
  special, admin: Safety
  eco, eso, judges, senior_management: General
"""

import numpy as np
import pandas as pd
from pathlib import Path

from pension_model.core.compact_mortality import CompactMortality


# Class to base table mapping (R benefit model lines 258-264)
BASE_TABLE_MAP = {
    "regular": "regular",        # average of general + teacher
    "special": "safety",
    "admin": "safety",
    "eco": "general",
    "eso": "general",
    "judges": "general",
    "senior_management": "general",
}


def _read_base_mort_table(excel_path: Path, sheet_name: str) -> pd.DataFrame:
    """
    Read and clean a pub-2010 base mortality table.

    Replicates R's get_base_mort_table() (lines 144-164).
    The Excel has: rows 0-2 = title/header, row 3 = gender headers,
    row 4 = column names (Age, Employee, Healthy Retiree, etc.),
    rows 5+ = data. Female block is columns ~1-6, Male block is ~7-12.

    Returns DataFrame with columns: age, employee_female, employee_male,
        healthy_retiree_female, healthy_retiree_male
    """
    raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)

    # Row 4 has the column headers: Age, Employee, Healthy Retiree, etc.
    # Find the row with "Age" in it
    header_row = None
    for i in range(min(10, len(raw))):
        if any(str(v).strip() == "Age" for v in raw.iloc[i].values if pd.notna(v)):
            header_row = i
            break
    if header_row is None:
        raise ValueError(f"Could not find header row with 'Age' in {sheet_name}")

    # Extract data below header
    data = raw.iloc[header_row + 1:].reset_index(drop=True)
    headers = raw.iloc[header_row].values

    # Find the Age columns (there are typically 2: one for female block, one for male)
    age_cols = [i for i, h in enumerate(headers) if str(h).strip() == "Age"]
    emp_cols = [i for i, h in enumerate(headers) if str(h).strip() == "Employee"]
    ret_cols = [i for i, h in enumerate(headers) if str(h).strip() == "Healthy Retiree"]

    if len(age_cols) < 1 or len(emp_cols) < 2 or len(ret_cols) < 2:
        raise ValueError(f"Expected 2 blocks (female/male) in {sheet_name}")

    # Female is the first block, Male is the second
    result = pd.DataFrame({
        "age": pd.to_numeric(data.iloc[:, age_cols[0]], errors="coerce"),
        "employee_female": pd.to_numeric(data.iloc[:, emp_cols[0]], errors="coerce"),
        "healthy_retiree_female": pd.to_numeric(data.iloc[:, ret_cols[0]], errors="coerce"),
        "employee_male": pd.to_numeric(data.iloc[:, emp_cols[1]], errors="coerce"),
        "healthy_retiree_male": pd.to_numeric(data.iloc[:, ret_cols[1]], errors="coerce"),
    })

    result = result.dropna(subset=["age"])
    result["age"] = result["age"].astype(int)

    # Fill NaN: employee = retiree where missing, and vice versa
    for gender in ["female", "male"]:
        emp = f"employee_{gender}"
        ret = f"healthy_retiree_{gender}"
        result[emp] = result[emp].fillna(result[ret])
        result[ret] = result[ret].fillna(result[emp])

    return result


def _read_mp_table(excel_path: Path, sheet_name: str, min_age: int = 18) -> pd.DataFrame:
    """
    Read and clean an MP-2018 mortality improvement table.

    Replicates R's clean_mp_table() (lines 175-191).
    Excel format: row 0 = title, row 1 = year headers, rows 2+ = age × year data.
    Returns DataFrame with columns: age, then integer year columns.
    """
    raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)

    # Row 1 has year headers, first column has ages starting at row 2
    # Set row 1 as header
    headers = list(raw.iloc[1].values)
    headers[0] = "age"  # First column is age
    data = raw.iloc[2:].reset_index(drop=True)
    data.columns = headers

    # Clean column names: remove "+" suffix, convert to string
    new_cols = []
    for c in data.columns:
        s = str(c).replace("+", "").strip()
        # Handle float years like "2034.0"
        try:
            s = str(int(float(s)))
        except (ValueError, TypeError):
            pass
        new_cols.append(s)
    data.columns = new_cols

    # Handle "≤ 20" or "≤20" in age column
    data["age"] = data["age"].apply(lambda x: 20 if "20" in str(x) and ("≤" in str(x) or "<" in str(x)) else x)

    # Convert all to numeric
    for c in data.columns:
        data[c] = pd.to_numeric(data[c], errors="coerce")

    data = data.dropna(subset=["age"]).sort_values("age").reset_index(drop=True)

    # Extend down to min_age (R extends to 18 by filling up)
    current_min = int(data["age"].min())
    if current_min > min_age:
        extra = []
        first_row = data.iloc[0].to_dict()
        for age in range(min_age, current_min):
            row = first_row.copy()
            row["age"] = age
            extra.append(row)
        data = pd.concat([pd.DataFrame(extra), data], ignore_index=True)

    return data


def _build_mp_final(mp_table: pd.DataFrame, gender: str, base_year: int,
                    min_age: int, max_age: int, max_year: int) -> pd.DataFrame:
    """
    Build mortality improvement cumulative adjustment factors.

    Replicates R's get_mp_final_table() (lines 199-223).
    Returns DataFrame with columns: age, year, {gender}_mp_cumprod_adj
    """
    # Pivot to long format
    mp_long = mp_table.melt(id_vars="age", var_name="year", value_name="mp")
    mp_long["year"] = mp_long["year"].astype(int)

    # Ultimate rates = last year's rates
    max_mp_year = mp_long["year"].max()
    mp_ultimate = mp_long[mp_long["year"] == max_mp_year][["age", "mp"]].rename(
        columns={"mp": "mp_ultimate"})

    # Expand to full age × year grid
    ages = range(min_age, max_age + 1)
    years = range(int(mp_long["year"].min()), max_year + 1)
    grid = pd.DataFrame([(a, y) for a in ages for y in years], columns=["age", "year"])
    grid = grid.merge(mp_long, on=["age", "year"], how="left")
    grid = grid.merge(mp_ultimate, on="age", how="left")
    grid["mp_final"] = grid["mp"].fillna(grid["mp_ultimate"])

    # Cumulative product within each age group
    grid = grid.sort_values(["age", "year"]).reset_index(drop=True)
    grid["mp_cumprod_raw"] = grid.groupby("age")["mp_final"].transform(
        lambda x: (1 - x).cumprod()
    )

    # Adjust: ratio to the base year value
    base_vals = grid[grid["year"] == base_year][["age", "mp_cumprod_raw"]].rename(
        columns={"mp_cumprod_raw": "base_val"})
    grid = grid.merge(base_vals, on="age", how="left")
    adj_col = f"{gender}_mp_cumprod_adj"
    grid[adj_col] = grid["mp_cumprod_raw"] / grid["base_val"]

    return grid[["age", "year", adj_col]]


def build_compact_mortality_from_excel(
    pub2010_path: Path,
    mp2018_path: Path,
    class_name: str,
    min_age: int = 18,
    max_age: int = 120,
    min_year: int = 1970,
    max_year: int = 2154,
    base_year: int = 2010,
    constants=None,
) -> CompactMortality:
    """
    Build a CompactMortality from raw Excel files.

    Args:
        pub2010_path: Path to pub-2010-headcount-mort-rates.xlsx
        mp2018_path: Path to mortality-improvement-scale-mp-2018-rates.xlsx
        class_name: Membership class name (determines which base table to use)
        min_age, max_age: Age range
        min_year, max_year: Year range
        base_year: Base year for mortality improvement adjustment (2010 for pub-2010)
        constants: Optional PlanConfig for config-driven base table lookup.

    Returns:
        CompactMortality with employee and retiree rates by (age, year)
    """
    # Read base mortality tables — use config map if available, else hardcoded FRS map
    from pension_model.plan_config import PlanConfig
    if isinstance(constants, PlanConfig) and constants.base_table_map:
        base_type = constants.get_base_table_type(class_name)
    else:
        base_type = BASE_TABLE_MAP[class_name]
    if base_type == "regular":
        general = _read_base_mort_table(pub2010_path, "PubG.H-2010")
        teacher = _read_base_mort_table(pub2010_path, "PubT.H-2010")
        # Regular = average of general and teacher
        base = general.copy()
        for col in ["employee_female", "employee_male", "healthy_retiree_female", "healthy_retiree_male"]:
            base[col] = (general[col] + teacher[col]) / 2
    elif base_type == "safety":
        base = _read_base_mort_table(pub2010_path, "PubS.H-2010")
    else:  # general
        base = _read_base_mort_table(pub2010_path, "PubG.H-2010")

    # Read and process improvement tables
    male_mp = _read_mp_table(mp2018_path, "Male", min_age)
    female_mp = _read_mp_table(mp2018_path, "Female", min_age)

    male_mp_final = _build_mp_final(male_mp, "male", base_year, min_age, max_age, max_year)
    female_mp_final = _build_mp_final(female_mp, "female", base_year, min_age, max_age, max_year)

    # Build final rates: base_rate × improvement_adjustment, averaged across genders
    # Employee rate = base_employee × mp_adj
    # Retiree rate = base_healthy_retiree × mp_adj
    ages = range(min_age, max_age + 1)
    years = range(min_year, max_year + 1)
    grid = pd.DataFrame([(a, y) for a in ages for y in years], columns=["dist_age", "dist_year"])

    # Join base rates
    grid = grid.merge(base.rename(columns={"age": "dist_age"}), on="dist_age", how="left")
    # Fill NaN for ages outside base table range
    for col in ["employee_female", "employee_male", "healthy_retiree_female", "healthy_retiree_male"]:
        grid[col] = grid[col].fillna(0)

    # Join improvement factors
    grid = grid.merge(male_mp_final.rename(columns={"age": "dist_age", "year": "dist_year"}),
                      on=["dist_age", "dist_year"], how="left")
    grid = grid.merge(female_mp_final.rename(columns={"age": "dist_age", "year": "dist_year"}),
                      on=["dist_age", "dist_year"], how="left")
    grid["male_mp_cumprod_adj"] = grid["male_mp_cumprod_adj"].fillna(1.0)
    grid["female_mp_cumprod_adj"] = grid["female_mp_cumprod_adj"].fillna(1.0)

    # Final rates: average of male and female, adjusted by improvement
    grid["employee_mort"] = (
        grid["employee_male"] * grid["male_mp_cumprod_adj"]
        + grid["employee_female"] * grid["female_mp_cumprod_adj"]
    ) / 2

    grid["retiree_mort"] = (
        grid["healthy_retiree_male"] * grid["male_mp_cumprod_adj"]
        + grid["healthy_retiree_female"] * grid["female_mp_cumprod_adj"]
    ) / 2

    employee_rates = grid[["dist_age", "dist_year", "employee_mort"]].rename(
        columns={"employee_mort": "mort_final"})
    retiree_rates = grid[["dist_age", "dist_year", "retiree_mort"]].rename(
        columns={"retiree_mort": "mort_final"})

    return CompactMortality(employee_rates, retiree_rates)


def _read_base_mort_csv(csv_path: Path, table_name: str) -> pd.DataFrame:
    """Read base mortality from stage 3 CSV format.

    CSV columns: age, gender, member_type, table, qx
    Returns DataFrame in same format as _read_base_mort_table:
        age, employee_female, employee_male, healthy_retiree_female, healthy_retiree_male
    """
    df = pd.read_csv(csv_path)
    df = df[df["table"] == table_name].copy()

    # Pivot from long (age, gender, member_type, qx) to wide
    result = df.pivot_table(
        index="age", columns=["member_type", "gender"], values="qx", aggfunc="first"
    ).reset_index()

    # Flatten MultiIndex columns: ('employee', 'female') → 'employee_female'
    result.columns = [
        f"{mt}_{g}" if g else str(mt)
        for mt, g in result.columns
    ]
    # Rename to match expected column names
    rename_map = {
        "retiree_female": "healthy_retiree_female",
        "retiree_male": "healthy_retiree_male",
    }
    result = result.rename(columns=rename_map)
    result["age"] = result["age"].astype(int)

    # Fill NaN: employee = retiree where missing, and vice versa
    for gender in ["female", "male"]:
        emp = f"employee_{gender}"
        ret = f"healthy_retiree_{gender}"
        if emp in result.columns and ret in result.columns:
            result[emp] = result[emp].fillna(result[ret])
            result[ret] = result[ret].fillna(result[emp])

    return result


def _read_mp_csv(csv_path: Path, gender: str, min_age: int = 18) -> pd.DataFrame:
    """Read mortality improvement scale from stage 3 CSV format.

    CSV columns: age, year, gender, improvement
    Returns DataFrame in same format as _read_mp_table:
        age column + integer year columns
    """
    df = pd.read_csv(csv_path)
    df = df[df["gender"] == gender].copy()

    # Pivot from long (age, year, improvement) to wide (age, year_1, year_2, ...)
    result = df.pivot_table(
        index="age", columns="year", values="improvement", aggfunc="first"
    ).reset_index()

    # Make column names strings (matching _read_mp_table output)
    result.columns = ["age"] + [str(int(c)) for c in result.columns[1:]]
    result["age"] = result["age"].astype(int)

    # Extend down to min_age if needed
    current_min = int(result["age"].min())
    if current_min > min_age:
        extra = []
        first_row = result.iloc[0].to_dict()
        for age in range(min_age, current_min):
            row = first_row.copy()
            row["age"] = age
            extra.append(row)
        result = pd.concat([pd.DataFrame(extra), result], ignore_index=True)

    return result


def build_compact_mortality_from_csv(
    base_rates_path: Path,
    improvement_path: Path,
    class_name: str,
    table_name: str,
    min_age: int = 18,
    max_age: int = 120,
    min_year: int = 1970,
    max_year: int = 2154,
    base_year: int = 2010,
    constants=None,
    male_mp_forward_shift: int = 0,
) -> CompactMortality:
    """Build CompactMortality from stage 3 CSV files.

    Args:
        base_rates_path: Path to base_rates.csv (age, gender, member_type, table, qx)
        improvement_path: Path to improvement_scale.csv (age, year, gender, improvement)
        class_name: Membership class name
        table_name: Which table to use from base_rates.csv (e.g. 'general', 'teacher_below_median')
        min_age, max_age, min_year, max_year, base_year: Range parameters
        constants: Optional PlanConfig
        male_mp_forward_shift: Shift male MP table forward by N years (TRS uses 2)
    """
    # For FRS "regular" class: average of general and teacher
    from pension_model.plan_config import PlanConfig
    if isinstance(constants, PlanConfig) and constants.base_table_map:
        base_type = constants.get_base_table_type(class_name)
    else:
        base_type = BASE_TABLE_MAP.get(class_name, "general")

    if base_type == "regular":
        general = _read_base_mort_csv(base_rates_path, "general")
        teacher = _read_base_mort_csv(base_rates_path, "teacher")
        base = general.copy()
        for col in ["employee_female", "employee_male",
                     "healthy_retiree_female", "healthy_retiree_male"]:
            base[col] = (general[col] + teacher[col]) / 2
    else:
        base = _read_base_mort_csv(base_rates_path, table_name)

    # Read improvement scale from CSV
    male_mp = _read_mp_csv(improvement_path, "male", min_age)
    female_mp = _read_mp_csv(improvement_path, "female", min_age)

    # Apply male MP forward shift if configured (TRS: 2 years)
    if male_mp_forward_shift > 0:
        year_cols = [c for c in male_mp.columns if c != "age"]
        new_names = {c: str(int(c) - male_mp_forward_shift) for c in year_cols}
        male_mp = male_mp.rename(columns=new_names)
        last_year = max(int(c) for c in male_mp.columns if c != "age")
        ultimate = male_mp[str(last_year)].values
        for y in range(last_year + 1, last_year + 1 + male_mp_forward_shift):
            male_mp[str(y)] = ultimate

    male_mp_final = _build_mp_final(male_mp, "male", base_year, min_age, max_age, max_year)
    female_mp_final = _build_mp_final(female_mp, "female", base_year, min_age, max_age, max_year)

    # Build final rates (same logic as build_compact_mortality_from_excel)
    ages = range(min_age, max_age + 1)
    years = range(min_year, max_year + 1)
    grid = pd.DataFrame([(a, y) for a in ages for y in years],
                        columns=["dist_age", "dist_year"])

    grid = grid.merge(base.rename(columns={"age": "dist_age"}), on="dist_age", how="left")
    for col in ["employee_female", "employee_male",
                "healthy_retiree_female", "healthy_retiree_male"]:
        grid[col] = grid[col].fillna(0)

    grid = grid.merge(
        male_mp_final.rename(columns={"age": "dist_age", "year": "dist_year"}),
        on=["dist_age", "dist_year"], how="left")
    grid = grid.merge(
        female_mp_final.rename(columns={"age": "dist_age", "year": "dist_year"}),
        on=["dist_age", "dist_year"], how="left")
    grid["male_mp_cumprod_adj"] = grid["male_mp_cumprod_adj"].fillna(1.0)
    grid["female_mp_cumprod_adj"] = grid["female_mp_cumprod_adj"].fillna(1.0)

    grid["employee_mort"] = (
        grid["employee_male"] * grid["male_mp_cumprod_adj"]
        + grid["employee_female"] * grid["female_mp_cumprod_adj"]
    ) / 2

    grid["retiree_mort"] = (
        grid["healthy_retiree_male"] * grid["male_mp_cumprod_adj"]
        + grid["healthy_retiree_female"] * grid["female_mp_cumprod_adj"]
    ) / 2

    employee_rates = grid[["dist_age", "dist_year", "employee_mort"]].rename(
        columns={"employee_mort": "mort_final"})
    retiree_rates = grid[["dist_age", "dist_year", "retiree_mort"]].rename(
        columns={"retiree_mort": "mort_final"})

    return CompactMortality(employee_rates, retiree_rates)



def build_ann_factor_retire_table(
    mortality: CompactMortality,
    class_name: str,
    start_year: int,
    model_period: int,
    dr: float,
    cola: float,
    min_retiree_age: int = 40,
    max_age: int = 120,
) -> pd.DataFrame:
    """
    Build annuity factor table for current retirees.

    Replicates R's get_mort_retire_table() + ann_factor_retire_table construction
    (benefit model lines 268-291, 696-709).

    Returns DataFrame with columns: base_age, age, year, mort_final, cola, dr,
        cum_mort, cum_dr, cum_mort_dr, ann_factor_retire
    """
    rows = []
    for base_age in range(min_retiree_age, max_age + 1):
        n_future = max_age - base_age + 1
        future_ages = np.arange(base_age, max_age + 1)
        future_years = np.arange(start_year, start_year + n_future)

        # Get retiree mortality rates
        mort = mortality.get_rates_vec(
            future_ages,
            np.clip(future_years, mortality.min_year, mortality.max_year),
            is_retiree=True,
        )

        # Cumulative products (lagged)
        cum_mort = np.cumprod(np.concatenate([[1.0], 1 - mort[:-1]]))
        cum_dr = (1 + dr) ** np.arange(n_future)
        cum_mort_dr = cum_mort / cum_dr

        # Annuity factor with COLA (R's annfactor function)
        # For constant COLA: ann_factor uses cum_mort_dr * cum_cola
        cum_cola = (1 + cola) ** np.arange(n_future)
        cum_mort_dr_cola = cum_mort_dr * cum_cola
        rev_cumsum = np.flip(np.cumsum(np.flip(cum_mort_dr_cola)))
        ann_factor = rev_cumsum / cum_mort_dr_cola

        for k in range(min(n_future, model_period + 1)):
            age = base_age + k
            year = start_year + k
            if year <= start_year + model_period:
                rows.append({
                    "base_age": base_age,
                    "age": age,
                    "year": year,
                    "mort_final": mort[k],
                    "cola": cola,
                    "dr": dr,
                    "cum_mort": cum_mort[k],
                    "cum_dr": cum_dr[k],
                    "cum_mort_dr": cum_mort_dr[k],
                    "ann_factor_retire": ann_factor[k],
                })

    return pd.DataFrame(rows)
