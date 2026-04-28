#!/usr/bin/env python3
"""
One-time conversion: FRS current data → stage 3 standardized format.

Reads from:
  - baseline_outputs/ (CSVs: salary, headcount, salary_growth, retiree_distribution)
  - baseline_outputs/decrement_tables/ (termination and retirement rate CSVs)
  - R_model/R_model_frs/ (Excel: mortality base table, improvement scale)

Writes to:
  - data/frs/demographics/
  - data/frs/decrements/
  - data/frs/mortality/
  - data/frs/funding/

Run from project root:
  python scripts/convert_frs_to_stage3.py
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

BASELINE = PROJECT_ROOT / "baseline_outputs"
RAW_DIR = PROJECT_ROOT / "R_model" / "R_model_frs"
OUT = PROJECT_ROOT / "data" / "frs"

CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]

# Map class → separation class (some share decrement tables)
SEP_CLASS_MAP = {
    "regular": "regular",
    "special": "special",
    "admin": "admin",
    "eco": "eco",
    "eso": "regular",  # ESO uses regular separation rates
    "judges": "judges",
    "senior_management": "senior_management",
}


def convert_salary_headcount():
    """Convert wide-format salary/headcount → long format."""
    print("Converting salary and headcount...")
    for cls in CLASSES:
        for kind, val_col in [("salary", "salary"), ("headcount", "count")]:
            src = pd.read_csv(BASELINE / f"{cls}_{kind}.csv")
            # Melt from wide (age, yos_1, yos_2, ...) to long (age, yos, value)
            long = src.melt(id_vars="age", var_name="yos", value_name=val_col)
            long["yos"] = long["yos"].astype(float).astype(int)
            long = long.dropna(subset=[val_col])
            long = long[long[val_col] != 0].reset_index(drop=True)
            long = long.sort_values(["age", "yos"]).reset_index(drop=True)
            out_path = OUT / "demographics" / f"{cls}_{kind}.csv"
            long.to_csv(out_path, index=False)
            print(f"  {out_path.name}: {len(long)} rows")


def convert_salary_growth():
    """Convert multi-column salary growth → one file per class."""
    print("Converting salary growth...")
    src = pd.read_csv(BASELINE / "salary_growth_table.csv")

    # Column name mapping
    col_map = {
        "regular": "salary_increase_regular",
        "special": "salary_increase_special_risk",
        "admin": "salary_increase_admin",
        "eco": "salary_increase_eco",
        "eso": "salary_increase_eso",
        "judges": "salary_increase_judges",
        "senior_management": "salary_increase_senior_management",
    }

    # Check if all classes have the same growth rates
    cols = [col_map[c] for c in CLASSES]
    values = src[cols].values
    all_same = all(np.allclose(values[:, 0], values[:, i], equal_nan=True) for i in range(1, len(cols)))

    if all_same:
        # Single file for all classes
        out = src[["yos"]].copy()
        out["salary_increase"] = src[col_map["regular"]]
        out.to_csv(OUT / "demographics" / "salary_growth.csv", index=False)
        print("  salary_growth.csv (shared): {} rows".format(len(out)))
    else:
        # Separate files per class
        for cls in CLASSES:
            out = src[["yos"]].copy()
            out["salary_increase"] = src[col_map[cls]]
            out.to_csv(OUT / "demographics" / f"{cls}_salary_growth.csv", index=False)
            print(f"  {cls}_salary_growth.csv: {len(out)} rows")


def convert_retiree_distribution():
    """Convert retiree distribution to standard columns."""
    print("Converting retiree distribution...")
    src = pd.read_csv(BASELINE / "retiree_distribution.csv")
    out = pd.DataFrame({
        "age": src["age"],
        "count": src["n_retire"],
        "avg_benefit": src["avg_ben"],
        "total_benefit": src["total_ben"],
    })
    out.to_csv(OUT / "demographics" / "retiree_distribution.csv", index=False)
    print(f"  retiree_distribution.csv: {len(out)} rows")


def convert_termination_rates():
    """Convert age-group-banded termination rates → lookup_type format.

    FRS termination rates use YOS + age-group bands. We expand age groups to
    individual ages and use lookup_type='yos' with an age column.
    See docs/design/termination_rate_design.md for rationale.
    """
    print("Converting termination rates...")

    # Age group breaks matching R's cut() and build_separation_rate_table
    # breaks = [-inf, 24, 29, 34, 44, 54, inf]
    age_group_ranges = {
        "under_25": (18, 24),
        "25_to_29": (25, 29),
        "30_to_34": (30, 34),
        "35_to_44": (35, 44),
        "45_to_54": (45, 54),
        "over_55": (55, 80),  # Use 80 as practical max
    }

    seen_sep_classes = set()
    for cls in CLASSES:
        sep_cls = SEP_CLASS_MAP[cls]
        if sep_cls in seen_sep_classes:
            continue
        seen_sep_classes.add(sep_cls)

        src = pd.read_csv(BASELINE / "decrement_tables" / f"{sep_cls}_term_rate_avg.csv")
        age_group_cols = [c for c in src.columns if c != "yos"]

        rows = []
        for _, row in src.iterrows():
            yos = int(row["yos"])
            for col in age_group_cols:
                rate = row[col]
                if pd.isna(rate):
                    continue
                lo, hi = age_group_ranges[col]
                for age in range(lo, hi + 1):
                    rows.append({
                        "lookup_type": "yos",
                        "age": age,
                        "lookup_value": yos,
                        "term_rate": rate,
                    })

        out = pd.DataFrame(rows).sort_values(["age", "lookup_value"]).reset_index(drop=True)
        out_path = OUT / "decrements" / f"{sep_cls}_termination_rates.csv"
        out.to_csv(out_path, index=False)
        print(f"  {out_path.name}: {len(out)} rows")


def convert_retirement_rates():
    """Convert tier-specific retirement rate files → unified retirement_rates.csv per class."""
    print("Converting retirement rates...")

    seen_sep_classes = set()
    for cls in CLASSES:
        sep_cls = SEP_CLASS_MAP[cls]
        if sep_cls in seen_sep_classes:
            continue
        seen_sep_classes.add(sep_cls)

        rows = []
        for tier_num in [1, 2]:
            tier_name = f"tier_{tier_num}"
            for retire_type, prefix in [("normal", "normal_retire_rate"),
                                         ("early", "early_retire_rate")]:
                fname = f"{sep_cls}_{prefix}_tier{tier_num}.csv"
                fpath = BASELINE / "decrement_tables" / fname
                if not fpath.exists():
                    print(f"  WARNING: {fname} not found, skipping")
                    continue
                src = pd.read_csv(fpath)
                rate_col = [c for c in src.columns if c != "age"][0]
                for _, row in src.iterrows():
                    rate = row[rate_col]
                    if pd.notna(rate):
                        rows.append({
                            "age": int(row["age"]),
                            "tier": tier_name,
                            "retire_type": retire_type,
                            "retire_rate": rate,
                        })

        out = pd.DataFrame(rows).sort_values(["tier", "retire_type", "age"]).reset_index(drop=True)
        out_path = OUT / "decrements" / f"{sep_cls}_retirement_rates.csv"
        out.to_csv(out_path, index=False)
        print(f"  {out_path.name}: {len(out)} rows")


def convert_mortality():
    """Convert Excel mortality tables → CSV base_rates + improvement_scale.

    Uses the existing mortality_builder parsers which already handle the
    complex Excel layouts correctly.
    """
    print("Converting mortality tables...")
    from pension_model.core.mortality_builder import _read_base_mort_table, _read_mp_table

    # Base mortality: PUB-2010 headcount-weighted
    pub_path = RAW_DIR / "pub-2010-headcount-mort-rates.xlsx"
    if not pub_path.exists():
        print(f"  WARNING: {pub_path} not found, skipping mortality conversion")
        return

    # FRS uses three sheets: PubG.H-2010 (general), PubT.H-2010 (teacher), PubS.H-2010 (safety)
    sheet_map = {
        "PubG.H-2010": "general",
        "PubT.H-2010": "teacher",
        "PubS.H-2010": "safety",
    }

    mort_rows = []
    for sheet_name, table_label in sheet_map.items():
        try:
            df = _read_base_mort_table(pub_path, sheet_name)
        except Exception as e:
            print(f"  WARNING: Could not read sheet {sheet_name}: {e}")
            continue

        # df has columns: age, employee_female, healthy_retiree_female,
        #                  employee_male, healthy_retiree_male
        for _, row in df.iterrows():
            age = int(row["age"])
            for gender in ["female", "male"]:
                for member_type, col_prefix in [("employee", "employee"),
                                                 ("retiree", "healthy_retiree")]:
                    col = f"{col_prefix}_{gender}"
                    qx = row.get(col)
                    if pd.notna(qx):
                        mort_rows.append({
                            "age": age,
                            "gender": gender,
                            "member_type": member_type,
                            "table": table_label,
                            "qx": qx,
                        })

    if mort_rows:
        mort_df = pd.DataFrame(mort_rows).sort_values(
            ["table", "gender", "member_type", "age"]
        ).reset_index(drop=True)
        mort_df.to_csv(OUT / "mortality" / "base_rates.csv", index=False)
        print(f"  base_rates.csv: {len(mort_df)} rows")

    # Improvement scale: MP-2018
    mp_path = RAW_DIR / "mortality-improvement-scale-mp-2018-rates.xlsx"
    if not mp_path.exists():
        print(f"  WARNING: {mp_path} not found, skipping improvement scale")
        return

    imp_rows = []
    for gender_sheet, gender_label in [("Male", "male"), ("Female", "female")]:
        try:
            df = _read_mp_table(mp_path, gender_sheet, min_age=18)
        except Exception as e:
            print(f"  WARNING: Could not read sheet {gender_sheet}: {e}")
            continue

        # df has columns: age, then year columns (integers)
        year_cols = [c for c in df.columns if c != "age"]
        for _, row in df.iterrows():
            age = int(row["age"])
            for yr_col in year_cols:
                imp = row[yr_col]
                if pd.notna(imp):
                    imp_rows.append({
                        "age": age,
                        "year": int(yr_col),
                        "gender": gender_label,
                        "improvement": imp,
                    })

    if imp_rows:
        imp_df = pd.DataFrame(imp_rows).sort_values(
            ["gender", "age", "year"]
        ).reset_index(drop=True)
        imp_df.to_csv(OUT / "mortality" / "improvement_scale.csv", index=False)
        print(f"  improvement_scale.csv: {len(imp_df)} rows")


def convert_funding():
    """Convert funding data to stage 3 format."""
    print("Converting funding data...")

    # Amortization layers
    amort_src = BASELINE / "current_amort_layers.csv"
    if amort_src.exists():
        src = pd.read_csv(amort_src)
        # Standardize column names
        out = src.rename(columns={
            "class": "class",
            "amo_period": "amo_period",
            "amo_balance": "amo_balance",
        })
        # Keep only the columns we need
        keep_cols = ["class", "amo_period", "amo_balance"]
        extra = [c for c in out.columns if c in ["date"]]
        out = out[keep_cols + extra] if extra else out[keep_cols]
        out.to_csv(OUT / "funding" / "amort_layers.csv", index=False)
        print(f"  amort_layers.csv: {len(out)} rows")

    # Return scenarios - FRS uses constant return, but check if file exists
    # For FRS, the return is defined in config (model_return = 0.067)
    # Create a minimal return scenarios file
    print("  return_scenarios.csv: using config-defined constant return (no file needed)")


def main():
    print(f"Converting FRS data to stage 3 format")
    print(f"  Source: {BASELINE}")
    print(f"  Output: {OUT}")
    print()

    convert_salary_headcount()
    print()
    convert_salary_growth()
    print()
    convert_retiree_distribution()
    print()
    convert_termination_rates()
    print()
    convert_retirement_rates()
    print()
    convert_mortality()
    print()
    convert_funding()
    print()
    print("Done!")


if __name__ == "__main__":
    main()
