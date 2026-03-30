"""
Validate projected term/retire/refund liability components against R baseline.

Reproduces the R liability model's computation (lines 124-200) using:
  - R workforce outputs (wf_term, wf_retire, wf_refund)
  - R benefit_table data (cum_mort_dr, db_benefit, cola, db_ee_balance)
  - R ann_factor_table data (ann_factor)
  - R benefit_val_table data (pvfb_db_at_term_age)

Compares against R's aggregated liability.csv (aal_term_db_legacy_est, etc.)
"""

import json
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).parent.parent
BASELINE = BASE / "baseline_outputs"


def load_params():
    """Load model parameters and plan design ratios."""
    with open(BASE / "configs" / "calibration_params.json") as f:
        cal = json.load(f)
    with open(BASELINE / "input_params.json") as f:
        params = json.load(f)

    return {
        "dr_current": params["dr_current"][0],
        "dr_new": params.get("dr_new", params["dr_current"])[0],
        "new_year": params["new_year"][0],
        "start_year": params["start_year"][0],
        "model_period": params["model_period"][0],
        "db_ratios": cal["db_plan_ratios"],
    }


def get_db_ratios(is_special, db_ratios):
    """Return (db_before_2018, db_after_2018, db_new) plan design ratios."""
    prefix = "special" if is_special else "non_special"
    return (
        db_ratios[f"{prefix}_legacy_before_2018"],
        db_ratios[f"{prefix}_legacy_after_2018"],
        db_ratios[f"{prefix}_new"],
    )


def allocate_db_legacy(entry_year, n, db_before, db_after, new_year):
    """Allocate headcount to DB legacy based on entry year."""
    return np.where(
        entry_year < 2018, n * db_before,
        np.where(entry_year < new_year, n * db_after, 0.0)
    )


def allocate_db_new(entry_year, n, db_new, new_year):
    """Allocate headcount to DB new based on entry year."""
    return np.where(entry_year < new_year, 0.0, n * db_new)


def compute_term_liability(class_name, params):
    """
    Reproduce R's wf_term_df_final (liability model lines 124-149).

    Term liability = sum(pvfb_db_at_term_age / cum_mort_dr * n_term_db_legacy)
    where cum_mort_dr discounts from term age to current age.
    """
    wf_term = pd.read_csv(BASELINE / f"{class_name}_wf_term.csv")
    bt_term = pd.read_csv(BASELINE / f"{class_name}_bt_term.csv")
    bvt_term = pd.read_csv(BASELINE / f"{class_name}_bvt_term.csv")

    # Filter to projection period, positive counts
    max_year = params["start_year"] + params["model_period"]
    wf = wf_term[(wf_term["year"] <= max_year) & (wf_term["n_term"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join with benefit_val_table to get pvfb_db_at_term_age
    # R joins on (entry_age, term_year, entry_year)
    wf = wf.merge(
        bvt_term[["entry_age", "entry_year", "term_year", "pvfb_db_at_term_age"]],
        on=["entry_age", "term_year", "entry_year"],
        how="left",
    )

    # Join with benefit_table to get cum_mort_dr at current age/year
    # R joins on (entry_age, dist_age=age, dist_year=year, term_year, entry_year)
    wf = wf.merge(
        bt_term[["entry_age", "entry_year", "dist_age", "dist_year", "term_year", "cum_mort_dr"]],
        left_on=["entry_age", "entry_year", "age", "year", "term_year"],
        right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"],
        how="left",
    )

    # pvfb_db_term = pvfb_db_at_term_age / cum_mort_dr_current
    wf["pvfb_db_term"] = wf["pvfb_db_at_term_age"] / wf["cum_mort_dr"]

    # Allocate to plan designs
    is_special = class_name == "special"
    db_before, db_after, db_new_ratio = get_db_ratios(is_special, params["db_ratios"])

    wf["n_term_db_legacy"] = allocate_db_legacy(
        wf["entry_year"], wf["n_term"], db_before, db_after, params["new_year"]
    )
    wf["n_term_db_new"] = allocate_db_new(
        wf["entry_year"], wf["n_term"], db_new_ratio, params["new_year"]
    )

    # Aggregate by year
    result = wf.groupby("year").agg(
        aal_term_db_legacy_est=("pvfb_db_term", lambda x: (x * wf.loc[x.index, "n_term_db_legacy"]).sum()),
        aal_term_db_new_est=("pvfb_db_term", lambda x: (x * wf.loc[x.index, "n_term_db_new"]).sum()),
    ).reset_index()

    return result


def compute_refund_liability(class_name, params):
    """
    Reproduce R's wf_refund_df_final (liability model lines 154-169).

    Refund = sum(db_ee_balance * n_refund_db_legacy)
    """
    wf_refund = pd.read_csv(BASELINE / f"{class_name}_wf_refund.csv")
    bt_refund = pd.read_csv(BASELINE / f"{class_name}_bt_refund.csv")

    max_year = params["start_year"] + params["model_period"]
    wf = wf_refund[(wf_refund["year"] <= max_year) & (wf_refund["n_refund"] > 0)].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # Join with benefit_table to get db_ee_balance
    # R joins on (entry_age, age=dist_age, year=dist_year, term_year, entry_year)
    wf = wf.merge(
        bt_refund[["entry_age", "entry_year", "dist_age", "dist_year", "term_year", "db_ee_balance"]],
        left_on=["entry_age", "entry_year", "age", "year", "term_year"],
        right_on=["entry_age", "entry_year", "dist_age", "dist_year", "term_year"],
        how="left",
    )

    # Allocate to plan designs
    is_special = class_name == "special"
    db_before, db_after, db_new_ratio = get_db_ratios(is_special, params["db_ratios"])

    wf["n_refund_db_legacy"] = allocate_db_legacy(
        wf["entry_year"], wf["n_refund"], db_before, db_after, params["new_year"]
    )
    wf["n_refund_db_new"] = allocate_db_new(
        wf["entry_year"], wf["n_refund"], db_new_ratio, params["new_year"]
    )

    result = wf.groupby("year").agg(
        refund_db_legacy_est=("db_ee_balance", lambda x: (x * wf.loc[x.index, "n_refund_db_legacy"]).sum()),
        refund_db_new_est=("db_ee_balance", lambda x: (x * wf.loc[x.index, "n_refund_db_new"]).sum()),
    ).reset_index()

    return result


def compute_retire_liability(class_name, params):
    """
    Reproduce R's wf_retire_df_final (liability model lines 174-200).

    retire benefit = db_benefit * (1+cola)^(year-retire_year)
    retire PVFB = db_benefit_final * (ann_factor - 1)
    """
    wf_retire = pd.read_csv(BASELINE / f"{class_name}_wf_retire.csv")
    bt_retire = pd.read_csv(BASELINE / f"{class_name}_bt_retire.csv")
    af_retire = pd.read_csv(BASELINE / f"{class_name}_af_retire.csv")

    max_year = params["start_year"] + params["model_period"]
    wf = wf_retire[wf_retire["year"] <= max_year].copy()
    wf["entry_year"] = wf["year"] - (wf["age"] - wf["entry_age"])

    # First join: benefit_table by (entry_age, entry_year, term_year, retire_year=dist_year)
    # Gets db_benefit and cola at retirement
    wf = wf.merge(
        bt_retire[["entry_age", "entry_year", "term_year", "dist_year", "db_benefit", "cola"]],
        left_on=["entry_age", "entry_year", "term_year", "retire_year"],
        right_on=["entry_age", "entry_year", "term_year", "dist_year"],
        how="left",
    )

    # Second join: ann_factor_table by (entry_age, entry_year, term_year, year=dist_year)
    # Gets ann_factor at current year
    # Note: R code selects(-cola) from ann_factor_table to avoid conflict
    wf = wf.merge(
        af_retire[["entry_age", "entry_year", "term_year", "dist_year", "ann_factor"]],
        left_on=["entry_age", "entry_year", "term_year", "year"],
        right_on=["entry_age", "entry_year", "term_year", "dist_year"],
        how="left",
        suffixes=("_bt", "_af"),
    )

    # Compute final benefit with COLA adjustment
    wf["db_benefit_final"] = wf["db_benefit"] * (1 + wf["cola"]) ** (wf["year"] - wf["retire_year"])

    # PVFB for retirees: benefit * (ann_factor - 1)
    # "ann_factor - 1" because the first payment has already been delivered
    wf["pvfb_db_retire"] = wf["db_benefit_final"] * (wf["ann_factor"] - 1)

    # Allocate to plan designs
    is_special = class_name == "special"
    db_before, db_after, db_new_ratio = get_db_ratios(is_special, params["db_ratios"])

    wf["n_retire_db_legacy"] = allocate_db_legacy(
        wf["entry_year"], wf["n_retire"], db_before, db_after, params["new_year"]
    )
    wf["n_retire_db_new"] = allocate_db_new(
        wf["entry_year"], wf["n_retire"], db_new_ratio, params["new_year"]
    )

    result = wf.groupby("year").agg(
        retire_ben_db_legacy_est=("db_benefit_final", lambda x: (x * wf.loc[x.index, "n_retire_db_legacy"]).sum()),
        retire_ben_db_new_est=("db_benefit_final", lambda x: (x * wf.loc[x.index, "n_retire_db_new"]).sum()),
        aal_retire_db_legacy_est=("pvfb_db_retire", lambda x: (x * wf.loc[x.index, "n_retire_db_legacy"]).sum()),
        aal_retire_db_new_est=("pvfb_db_retire", lambda x: (x * wf.loc[x.index, "n_retire_db_new"]).sum()),
    ).reset_index()

    return result


def validate_class(class_name, params):
    """Validate all projected liability components for one class."""
    # Load R target values
    lib = pd.read_csv(BASELINE / f"{class_name}_liability.csv")

    # Compute Python values
    term = compute_term_liability(class_name, params)
    refund = compute_refund_liability(class_name, params)
    retire = compute_retire_liability(class_name, params)

    # Merge all components
    result = lib[["year"]].copy()
    result = result.merge(term, on="year", how="left")
    result = result.merge(refund, on="year", how="left")
    result = result.merge(retire, on="year", how="left")
    result = result.fillna(0)

    # Compare with R values
    components = [
        ("aal_term_db_legacy", "aal_term_db_legacy_est"),
        ("aal_term_db_new", "aal_term_db_new_est"),
        ("refund_db_legacy", "refund_db_legacy_est"),
        ("refund_db_new", "refund_db_new_est"),
        ("retire_ben_db_legacy", "retire_ben_db_legacy_est"),
        ("retire_ben_db_new", "retire_ben_db_new_est"),
        ("aal_retire_db_legacy", "aal_retire_db_legacy_est"),
        ("aal_retire_db_new", "aal_retire_db_new_est"),
    ]

    diffs = {}
    for label, col in components:
        r_vals = lib[col].values
        py_vals = result[col].values if col in result.columns else np.zeros(len(lib))
        # Percent diff where R is nonzero
        mask = np.abs(r_vals) > 1e-6
        if mask.any():
            pct = np.abs(py_vals[mask] - r_vals[mask]) / np.abs(r_vals[mask]) * 100
            diffs[label] = {"max_pct": pct.max(), "mean_pct": pct.mean(), "n_compared": int(mask.sum())}
        else:
            diffs[label] = {"max_pct": 0.0, "mean_pct": 0.0, "n_compared": 0}

    return result, lib, diffs


def main():
    params = load_params()
    classes = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]

    print("=" * 90)
    print("Projected Liability Validation: Python vs R Baseline")
    print("=" * 90)

    all_pass = True
    summary_rows = []

    for cls in classes:
        print(f"\n{'='*70}")
        print(f"  {cls.upper()}")
        print(f"{'='*70}")

        try:
            result, lib, diffs = validate_class(cls, params)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            all_pass = False
            continue

        cls_pass = True
        for label, info in diffs.items():
            status = "PASS" if info["max_pct"] < 0.01 else ("CLOSE" if info["max_pct"] < 0.1 else "FAIL")
            if info["n_compared"] == 0:
                status = "N/A"
            elif status != "PASS":
                cls_pass = False

            print(f"  {label:30s}  max={info['max_pct']:8.4f}%  mean={info['mean_pct']:8.4f}%  n={info['n_compared']:3d}  {status}")
            summary_rows.append({"class": cls, "component": label, **info, "status": status})

        # Show year-by-year detail for first few years
        print(f"\n  Year-by-year detail (first 5 years with data):")
        for col_label, col in [("aal_term_legacy", "aal_term_db_legacy_est"),
                                ("refund_legacy", "refund_db_legacy_est"),
                                ("aal_retire_legacy", "aal_retire_db_legacy_est")]:
            r_vals = lib[col].values
            py_vals = result[col].values if col in result.columns else np.zeros(len(lib))
            print(f"\n  {col_label}:")
            print(f"  {'Year':>6} {'Python':>18} {'R':>18} {'Diff%':>10}")
            shown = 0
            for i, year in enumerate(lib["year"]):
                if abs(r_vals[i]) > 1e-6:
                    pct = abs(py_vals[i] - r_vals[i]) / abs(r_vals[i]) * 100
                    print(f"  {year:>6} {py_vals[i]:>18,.0f} {r_vals[i]:>18,.0f} {pct:>9.4f}%")
                    shown += 1
                    if shown >= 5:
                        break

        if not cls_pass:
            all_pass = False

    # Summary table
    print(f"\n{'='*90}")
    print("SUMMARY")
    print(f"{'='*90}")
    summary = pd.DataFrame(summary_rows)
    for cls in classes:
        cls_data = summary[summary["class"] == cls]
        max_pct = cls_data["max_pct"].max()
        status = "PASS" if max_pct < 0.01 else ("CLOSE" if max_pct < 0.1 else "FAIL")
        print(f"  {cls:25s}  max_diff={max_pct:8.4f}%  {status}")

    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")


if __name__ == "__main__":
    main()
