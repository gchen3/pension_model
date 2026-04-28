#!/usr/bin/env python3
"""
One-time conversion: TRS (Texas TRS) data → stage 3 standardized format.

Reads from:
  - R_model/R_model_txtrs/TxTRS_BM_Inputs.xlsx (all demographics + decrements)
  - R_model/R_model_txtrs/Inputs/ (mortality files)

Writes to:
  - data/txtrs/demographics/
  - data/txtrs/decrements/
  - data/txtrs/mortality/
  - data/txtrs/funding/

Run from project root:
  python scripts/convert_txtrs_to_stage3.py
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

RAW_DIR = PROJECT_ROOT / "R_model" / "R_model_txtrs"
OUT = PROJECT_ROOT / "data" / "txtrs"


def convert_salary_headcount():
    """Convert TRS salary/headcount from Excel wide matrix → long format CSVs."""
    print("Converting salary and headcount...")
    from pension_model.core.txtrs_loader import load_txtrs_salary_headcount

    xlsx_path = RAW_DIR / "TxTRS_BM_Inputs.xlsx"
    sal_wide, hc_wide = load_txtrs_salary_headcount(xlsx_path)

    # Melt salary: wide (age, yos_1, yos_2, ...) → long (age, yos, salary)
    sal_long = sal_wide.melt(id_vars="age", var_name="yos", value_name="salary")
    sal_long["yos"] = sal_long["yos"].astype(float).astype(int)
    sal_long = sal_long.dropna(subset=["salary"])
    sal_long = sal_long[sal_long["salary"] != 0].sort_values(["age", "yos"]).reset_index(drop=True)
    sal_long.to_csv(OUT / "demographics" / "all_salary.csv", index=False)
    print(f"  all_salary.csv: {len(sal_long)} rows")

    # Melt headcount
    hc_long = hc_wide.melt(id_vars="age", var_name="yos", value_name="count")
    hc_long["yos"] = hc_long["yos"].astype(float).astype(int)
    hc_long = hc_long.dropna(subset=["count"])
    hc_long = hc_long[hc_long["count"] != 0].sort_values(["age", "yos"]).reset_index(drop=True)
    hc_long.to_csv(OUT / "demographics" / "all_headcount.csv", index=False)
    print(f"  all_headcount.csv: {len(hc_long)} rows")


def convert_salary_growth():
    """Convert TRS salary growth from Excel → CSV."""
    print("Converting salary growth...")
    from pension_model.core.txtrs_loader import load_txtrs_salary_growth

    xlsx_path = RAW_DIR / "TxTRS_BM_Inputs.xlsx"
    sg = load_txtrs_salary_growth(xlsx_path)
    # Rename column to standard name
    sg = sg.rename(columns={"salary_increase_all": "salary_increase"})
    sg.to_csv(OUT / "demographics" / "salary_growth.csv", index=False)
    print(f"  salary_growth.csv: {len(sg)} rows")


def convert_entrant_profile():
    """Convert TRS entrant profile from Excel → CSV."""
    print("Converting entrant profile...")
    from pension_model.core.txtrs_loader import load_txtrs_entrant_profile

    xlsx_path = RAW_DIR / "TxTRS_BM_Inputs.xlsx"
    ep = load_txtrs_entrant_profile(xlsx_path)
    # Add entrant_dist column
    ep["entrant_dist"] = ep["count"] / ep["count"].sum()
    # Rename to standard column names
    out = pd.DataFrame({
        "entry_age": ep["entry_age"],
        "start_salary": ep["start_sal"],
        "entrant_dist": ep["entrant_dist"],
    })
    out.to_csv(OUT / "demographics" / "entrant_profile.csv", index=False)
    print(f"  entrant_profile.csv: {len(out)} rows")


def convert_retiree_distribution():
    """Convert TRS retiree distribution from Excel → CSV."""
    print("Converting retiree distribution...")
    from pension_model.core.txtrs_loader import load_txtrs_retiree_distribution

    xlsx_path = RAW_DIR / "TxTRS_BM_Inputs.xlsx"
    rd = load_txtrs_retiree_distribution(xlsx_path)
    out = pd.DataFrame({
        "age": rd["age"],
        "count": rd["n_retire"],
        "avg_benefit": rd["avg_ben"],
        "total_benefit": rd["total_ben"],
    })
    out.to_csv(OUT / "demographics" / "retiree_distribution.csv", index=False)
    print(f"  retiree_distribution.csv: {len(out)} rows")


def convert_termination_rates():
    """Convert TRS termination rates → lookup_type format.

    TRS has two structures (see docs/design/termination_rate_design.md):
      - YOS 1-10: rate by years of service
      - YOS 10+: rate by years from normal retirement
    """
    print("Converting termination rates...")
    from pension_model.core.txtrs_loader import _load_termination_rates

    xlsx_path = RAW_DIR / "TxTRS_BM_Inputs.xlsx"
    before10, after10 = _load_termination_rates(xlsx_path)

    rows = []
    # Before 10: lookup_type = "yos", lookup_value = YOS
    for _, row in before10.iterrows():
        rows.append({
            "lookup_type": "yos",
            "age": "",
            "lookup_value": int(row["yos"]),
            "term_rate": row["term_rate"],
        })

    # After 10: lookup_type = "years_from_nr", lookup_value = years from NR
    for _, row in after10.iterrows():
        rows.append({
            "lookup_type": "years_from_nr",
            "age": "",
            "lookup_value": int(row["years_from_nr"]),
            "term_rate": row["term_rate"],
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "decrements" / "termination_rates.csv", index=False)
    print(f"  termination_rates.csv: {len(out)} rows")


def convert_retirement_rates():
    """Convert TRS retirement rates → unified format."""
    print("Converting retirement rates...")
    from pension_model.core.txtrs_loader import _load_retirement_rates

    xlsx_path = RAW_DIR / "TxTRS_BM_Inputs.xlsx"
    rr = _load_retirement_rates(xlsx_path)

    # TRS retirement rates are not tier-specific in the raw data.
    # The tier-specific adjustments (10% increase per year beyond Rule of 80)
    # are applied at runtime by the model. The raw rates apply to all tiers.
    rows = []
    for _, row in rr.iterrows():
        age = int(row["age"])
        if row["normal_rate"] > 0 or True:  # Include all ages for completeness
            rows.append({
                "age": age,
                "tier": "all",
                "retire_type": "normal",
                "retire_rate": row["normal_rate"],
            })
        if row["reduced_rate"] > 0 or True:
            rows.append({
                "age": age,
                "tier": "all",
                "retire_type": "early",
                "retire_rate": row["reduced_rate"],
            })

    out = pd.DataFrame(rows).sort_values(["retire_type", "age"]).reset_index(drop=True)
    out.to_csv(OUT / "decrements" / "retirement_rates.csv", index=False)
    print(f"  retirement_rates.csv: {len(out)} rows")


def convert_reduction_tables():
    """Convert TRS early retirement reduction tables → CSV.

    These are TRS-specific: grandfathered members use a YOS × age matrix,
    others use a simple age → factor table.
    """
    print("Converting reduction tables...")
    from pension_model.core.txtrs_loader import load_txtrs_reduction_tables

    xlsx_path = RAW_DIR / "TxTRS_BM_Inputs.xlsx"
    tables = load_txtrs_reduction_tables(xlsx_path)

    # Grandfathered: wide format (yos, age_55, age_56, ..., age_60) → long format
    gft = tables["reduced_gft"]
    gft_long = gft.melt(id_vars="yos", var_name="age_col", value_name="reduce_factor")
    # Extract age from column name like "age_55" or "55"
    gft_long["age"] = gft_long["age_col"].apply(
        lambda x: int(str(x).replace("age_", "").strip())
    )
    gft_long = gft_long[["age", "yos", "reduce_factor"]].dropna()
    gft_long["tier"] = "grandfathered"
    gft_long.to_csv(OUT / "decrements" / "reduction_gft.csv", index=False)
    print(f"  reduction_gft.csv: {len(gft_long)} rows")

    # Others: simple age → factor
    others = tables["reduced_others"]
    others["tier"] = "others"
    others = others.rename(columns={"reduce_factor": "reduce_factor"})
    others.to_csv(OUT / "decrements" / "reduction_others.csv", index=False)
    print(f"  reduction_others.csv: {len(others)} rows")


def convert_mortality():
    """Convert TRS mortality tables → CSV base_rates + improvement_scale."""
    print("Converting mortality tables...")
    from pension_model.core.mortality_builder import _read_base_mort_table, _read_mp_table

    inputs_dir = RAW_DIR / "Inputs"

    # Base mortality: PUB-2010 amount-weighted teacher below-median
    pub_path = inputs_dir / "pub-2010-amount-mort-rates.xlsx"
    if not pub_path.exists():
        print(f"  WARNING: {pub_path} not found, skipping mortality")
        return

    # TRS uses sheet "PubT-2010(B)" (Teacher Below-Median)
    mort_rows = []
    try:
        df = _read_base_mort_table(pub_path, "PubT-2010(B)")
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
                            "table": "teacher_below_median",
                            "qx": qx,
                        })
    except Exception as e:
        print(f"  WARNING: Could not read PubT-2010(B): {e}")

    if mort_rows:
        mort_df = pd.DataFrame(mort_rows).sort_values(
            ["table", "gender", "member_type", "age"]
        ).reset_index(drop=True)
        mort_df.to_csv(OUT / "mortality" / "base_rates.csv", index=False)
        print(f"  base_rates.csv: {len(mort_df)} rows")

    # Improvement scale: MP-2021
    mp_path = inputs_dir / "mp-2021-rates.xlsx"
    if not mp_path.exists():
        print(f"  WARNING: {mp_path} not found, skipping improvement scale")
        return

    imp_rows = []
    for gender_sheet, gender_label in [("Male", "male"), ("Female", "female")]:
        try:
            df = _read_mp_table(mp_path, gender_sheet, min_age=20)
        except Exception as e:
            print(f"  WARNING: Could not read sheet {gender_sheet}: {e}")
            continue

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
    """Convert TRS funding data from Excel → CSV."""
    print("Converting funding data...")
    from pension_model.core.txtrs_loader import load_txtrs_funding_data

    try:
        funding = load_txtrs_funding_data(RAW_DIR)
    except Exception as e:
        print(f"  WARNING: Could not load funding data: {e}")
        return

    if "return_scenarios" in funding:
        rs = funding["return_scenarios"]
        rs.to_csv(OUT / "funding" / "return_scenarios.csv", index=False)
        print(f"  return_scenarios.csv: {len(rs)} rows")

    if "init_funding" in funding:
        init = funding["init_funding"]
        init.to_csv(OUT / "funding" / "init_funding.csv", index=False)
        print(f"  init_funding.csv: {len(init)} rows")


def main():
    print(f"Converting TRS data to stage 3 format")
    print(f"  Source: {RAW_DIR}")
    print(f"  Output: {OUT}")
    print()

    convert_salary_headcount()
    print()
    convert_salary_growth()
    print()
    convert_entrant_profile()
    print()
    convert_retiree_distribution()
    print()
    convert_termination_rates()
    print()
    convert_retirement_rates()
    print()
    convert_reduction_tables()
    print()
    convert_mortality()
    print()
    convert_funding()
    print()
    print("Done!")


if __name__ == "__main__":
    main()
