"""
Build decrement tables (withdrawal, retirement) from raw Excel inputs.

Replaces R's decrement table processing (benefit model lines 295-520).
Produces per-class rate tables for the separation_rate_table builder.

Raw inputs:
  - Florida FRS inputs.xlsx: withdrawal rate sheets (by class/gender)
  - Reports/extracted inputs/: retirement and DROP entry xlsx files
"""

import numpy as np
import pandas as pd
from pathlib import Path


# Class → search text mapping for retirement/DROP tables
_RETIRE_CLASS_MAP = {
    "regular": {"drop": "regular", "normal": "regular", "early": "regular"},
    "special": {"drop": "special", "normal": "special", "early": "special"},
    "admin": {"drop": "special", "normal": "special", "early": "special"},
    "eco": {"drop": "other", "normal": "eco_eso_jud", "early": "eco_eso_jud"},
    "eso": {"drop": "other", "normal": "eco_eso_jud", "early": "eco_eso_jud"},
    "judges": {"drop": "other", "normal": "eco_eso_jud", "early": "eco_eso_jud"},
    "senior_management": {"drop": "other", "normal": "senior_management", "early": "senior_management"},
}

# Withdrawal rate sheet names by class
_WITHDRAWAL_SHEETS = {
    "regular": ("Withdrawal Rate Regular Male", "Withdrawal Rate Regular Female"),
    "special": ("Withdrawal Rate Special Male", "Withdrawal Rate Special Female"),
    "admin": ("Withdrawal Rate Admin Male", "Withdrawal Rate Admin Female"),
    "eco": ("Withdrawal Rate Eco", "Withdrawal Rate Eco"),  # same sheet, unisex
    "eso": ("Withdrawal Rate Eso", "Withdrawal Rate Eso"),
    "judges": ("Withdrawal Rate Judges", "Withdrawal Rate Judges"),
    "senior_management": ("Withdrawal Rate Sen Man Male", "Withdrawal Rate Sen Man Female"),
}


def _clean_retire_rate_table(raw: pd.DataFrame, col_names: list) -> pd.DataFrame:
    """
    Clean a retirement/DROP rate table from Excel.

    Replicates R's clean_retire_rate_table() (lines 300-323).
    """
    # Find the row with "Age" — everything before is header
    age_row = None
    for i in range(min(20, len(raw))):
        vals = [str(v).strip() for v in raw.iloc[i].values if pd.notna(v)]
        if "Age" in vals:
            age_row = i
            break
    if age_row is None:
        raise ValueError("Could not find 'Age' row in retirement table")

    # Find last all-NA row from bottom
    last_na = len(raw)
    for i in range(len(raw) - 1, -1, -1):
        if raw.iloc[i].isna().all():
            last_na = i
            break

    # Slice to body
    body = raw.iloc[age_row + 1:last_na].copy()
    body = body.dropna(axis=1, how="all").reset_index(drop=True)

    # Apply column names
    if len(body.columns) != len(col_names):
        # Trim or pad columns
        body = body.iloc[:, :len(col_names)]
    body.columns = col_names

    # Handle "70-79" row: expand to individual ages
    idx_70_79 = body[body["age"].astype(str).str.contains("70-79|70 - 79|70–79", na=False)].index
    if len(idx_70_79) > 0:
        idx = idx_70_79[0]
        row_data = body.iloc[idx].copy()
        row_data["age"] = "70"
        extra = pd.DataFrame([row_data.to_dict()] * 10)
        extra["age"] = [str(a) for a in range(70, 80)]
        body = pd.concat([body.iloc[:idx], extra, body.iloc[idx + 1:]], ignore_index=True)

    body["age"] = pd.to_numeric(body["age"].astype(str).str.strip(), errors="coerce")
    for c in body.columns:
        if c != "age":
            body[c] = pd.to_numeric(body[c], errors="coerce")

    body = body.dropna(subset=["age"])
    body = body.ffill()
    return body


def _read_withdrawal_table(excel_path: Path, sheet_name: str, max_yos: int = 70) -> pd.DataFrame:
    """Read and clean a withdrawal rate table from Excel."""
    raw = pd.read_excel(excel_path, sheet_name=sheet_name)
    raw = raw.dropna(axis=1, how="all")

    # Standardize column names
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    if "years_of_service" in raw.columns:
        raw = raw.rename(columns={"years_of_service": "yos"})

    # Ensure all numeric
    for c in raw.columns:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")

    raw = raw.dropna(subset=["yos"])

    # Extend to max_yos by forward fill
    if raw["yos"].max() < max_yos:
        extra = pd.DataFrame({"yos": range(int(raw["yos"].max()) + 1, max_yos + 1)})
        raw = pd.concat([raw, extra], ignore_index=True)
        raw = raw.ffill()

    return raw


def build_withdrawal_rate_table(
    excel_path: Path, class_name: str, max_yos: int = 70,
) -> pd.DataFrame:
    """
    Build gender-averaged withdrawal rate table for a class.

    Returns DataFrame with yos and age group columns.
    """
    male_sheet, female_sheet = _WITHDRAWAL_SHEETS[class_name]
    male = _read_withdrawal_table(excel_path, male_sheet, max_yos)
    female = _read_withdrawal_table(excel_path, female_sheet, max_yos)

    # Average male and female
    result = male.copy()
    for c in result.columns:
        if c != "yos":
            result[c] = (male[c] + female[c]) / 2

    return result


def build_retirement_rate_tables(
    frs_inputs_path: Path, extracted_inputs_dir: Path, class_name: str,
) -> dict:
    """
    Build per-class normal and early retirement rate tables.

    Combines DROP entry + normal retirement rates, averages across genders.

    Returns dict with keys:
      'normal_retire_tier1', 'normal_retire_tier2',
      'early_retire_tier1', 'early_retire_tier2'
    Each is a DataFrame with columns: age, normal_retire_rate (or early_retire_rate)
    """
    mapping = _RETIRE_CLASS_MAP[class_name]

    # Column name templates
    drop_col_names = ["age", "regular_inst_female", "regular_inst_male",
                      "regular_non_inst_female", "regular_non_inst_male",
                      "special_risk_non_leo_female", "special_risk_non_leo_male",
                      "special_risk_leo_female", "special_risk_leo_male",
                      "other_female", "other_male"]

    normal_col_names = ["age", "regular_inst_female", "regular_inst_male",
                        "regular_non_inst_female", "regular_non_inst_male",
                        "special_risk_female", "special_risk_male",
                        "eco_eso_jud_female", "eco_eso_jud_male",
                        "senior_management_female", "senior_management_male"]

    early_col_names = ["age", "regular_non_inst_female", "regular_non_inst_male",
                       "special_risk_female", "special_risk_male",
                       "eco_eso_jud_female", "eco_eso_jud_male",
                       "senior_management_female", "senior_management_male"]

    result = {}
    for tier_num in [1, 2]:
        # Read raw tables
        drop_raw = pd.read_excel(extracted_inputs_dir / f"drop entry tier {tier_num}.xlsx", header=None)
        normal_raw = pd.read_excel(extracted_inputs_dir / f"normal retirement tier {tier_num}.xlsx", header=None)
        early_raw = pd.read_excel(extracted_inputs_dir / f"early retirement tier {tier_num}.xlsx", header=None)

        drop_table = _clean_retire_rate_table(drop_raw, drop_col_names)
        normal_table = _clean_retire_rate_table(normal_raw, normal_col_names)
        early_table = _clean_retire_rate_table(early_raw, early_col_names)

        # For tier 2 normal: add ages 45-49 with 0 rates
        if tier_num == 2:
            extra_ages = pd.DataFrame({"age": range(45, 50)})
            for c in normal_table.columns:
                if c != "age":
                    extra_ages[c] = 0.0
            normal_table = pd.concat([extra_ages, normal_table], ignore_index=True)
            normal_table = normal_table.sort_values("age").reset_index(drop=True)

        # Special handling for special_risk DROP (average LEO and non-LEO)
        if mapping["drop"] == "special":
            # R pre-averages LEO and non-LEO into single female/male columns
            sr_cols_f = [c for c in drop_table.columns if "special_risk" in c and "female" in c]
            sr_cols_m = [c for c in drop_table.columns if "special_risk" in c and "male" in c and "female" not in c]
            drop_table["special_risk_female"] = drop_table[sr_cols_f].mean(axis=1)
            drop_table["special_risk_male"] = drop_table[sr_cols_m].mean(axis=1)
            # Use ONLY the averaged columns, not the originals
            drop_cols = ["special_risk_female", "special_risk_male"]
        else:
            drop_search = mapping["drop"]
            drop_cols = [c for c in drop_table.columns if drop_search in c and c != "age"]

        normal_search = mapping["normal"]
        normal_cols = [c for c in normal_table.columns if normal_search in c and c != "age"]

        # Sum DROP + normal rates, then average across all gender columns
        combined = pd.DataFrame({"age": drop_table["age"]})
        drop_vals = drop_table[drop_cols].values
        # Align normal_table to same ages
        normal_aligned = normal_table.set_index("age").reindex(drop_table["age"]).fillna(0)
        normal_vals = normal_aligned[normal_cols].values

        # R adds the matrices element-wise, then averages all columns
        # The columns may differ in count between drop and normal
        # R: (drop_entry_table %>% select(contains(search_drop)) +
        #      normal_retire_rate_table %>% select(contains(search_normal)))
        # Then rowwise mean across all resulting columns

        # Build the sum: each drop col + each normal col? No — R adds them positionally.
        # Both have 2 cols (female, male) for the class. Sum pairwise, then average.
        n_drop = len(drop_cols)
        n_normal = len(normal_cols)

        if n_drop == n_normal and n_drop > 0:
            summed = drop_vals + normal_vals
            combined["normal_retire_rate"] = summed.mean(axis=1)
        elif n_drop > 0 and n_normal > 0:
            # R concatenates the columns and averages ALL of them
            all_vals = np.concatenate([drop_vals, normal_vals], axis=1)
            combined["normal_retire_rate"] = all_vals.mean(axis=1)
        else:
            combined["normal_retire_rate"] = 0.0

        result[f"normal_retire_tier{tier_num}"] = combined

        # Build early retirement rate: select class columns, average across genders
        early_search = mapping["early"]
        early_cols = [c for c in early_table.columns if early_search in c and c != "age"]
        early_result = pd.DataFrame({"age": early_table["age"]})
        if early_cols:
            early_result["early_retire_rate"] = early_table[early_cols].mean(axis=1)
        else:
            early_result["early_retire_rate"] = 0.0

        result[f"early_retire_tier{tier_num}"] = early_result

    return result
