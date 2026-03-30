"""
Validate current retiree AAL computation against R baseline.

Reproduces R liability model lines 204-234:
  1. Initialize retirees from distribution (age, n_retire_ratio, total_ben_ratio)
  2. Project forward with mortality (recur_grow, lagged) and COLA (recur_grow2, no lag)
  3. PVFB = avg_ben * (ann_factor_retire - 1)
  4. AAL = sum(n_retire * pvfb) by year

Uses R's ann_factor_retire_table (already extracted) which has:
  mort_final, cola, ann_factor_retire per (base_age, age, year)
"""

import json
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).parent.parent
BASELINE = BASE / "baseline_outputs"


def recur_grow(x, g):
    """R's recur_grow: x[i] = x[i-1] * (1 + g[i-1]) — lagged growth."""
    out = x.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] * (1 + g[i - 1])
    return out


def recur_grow2(x, g):
    """R's recur_grow2: x[i] = x[i-1] * (1 + g[i]) — no lag."""
    out = x.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] * (1 + g[i])
    return out


def compute_retire_current(class_name, params, cal):
    """Reproduce R's current retiree AAL calculation."""
    # Load retiree distribution and ann_factor_retire table
    retiree_dist = pd.read_csv(BASELINE / "retiree_distribution.csv")
    afr = pd.read_csv(BASELINE / f"{class_name}_ann_factor_retire.csv")

    retiree_pop = cal["retiree_population"][class_name]
    ben_payment = cal["benefit_payments_current"][class_name]

    start_year = params["start_year"]
    model_period = params["model_period"]

    # Step 1: Initialize current retirees (R lines 205-212)
    retire_init = retiree_dist[["age", "n_retire_ratio", "total_ben_ratio"]].copy()
    retire_init["n_retire_current"] = retire_init["n_retire_ratio"] * retiree_pop
    retire_init["total_ben_current"] = retire_init["total_ben_ratio"] * ben_payment
    retire_init["avg_ben_current"] = (
        retire_init["total_ben_current"] / retire_init["n_retire_current"]
    )
    retire_init["year"] = start_year

    # Step 2: Join with ann_factor_retire_table (R lines 215-218)
    # Filter to projection period
    afr_filt = afr[afr["year"] <= start_year + model_period].copy()

    # Join initialization data on (age, year)
    merged = afr_filt.merge(
        retire_init[["age", "year", "n_retire_current", "avg_ben_current", "total_ben_current"]],
        on=["age", "year"],
        how="left",
    )

    # Step 3: Within each base_age group, project forward (R lines 219-226)
    results = []
    for base_age, group in merged.groupby("base_age"):
        g = group.sort_values("year").copy()
        n = g["n_retire_current"].values.copy()
        avg = g["avg_ben_current"].values.copy()
        mort = g["mort_final"].values
        cola = g["cola"].values

        # recur_grow: n[i] = n[i-1] * (1 + (-mort[i-1])) = n[i-1] * (1 - mort[i-1])
        n = recur_grow(n, -mort)

        # recur_grow2: avg[i] = avg[i-1] * (1 + cola[i])
        avg = recur_grow2(avg, cola)

        g["n_retire_current"] = n
        g["avg_ben_current"] = avg
        g["total_ben_current"] = n * avg
        g["pvfb_retire_current"] = avg * (g["ann_factor_retire"].values - 1)

        # Filter out NaN (rows before initialization)
        g = g[g["n_retire_current"].notna()]
        results.append(g)

    projected = pd.concat(results, ignore_index=True)

    # Step 4: Aggregate by year (R lines 229-234)
    summary = projected.groupby("year").agg(
        retire_ben_current_est=("total_ben_current", "sum"),
        aal_retire_current_est=pd.NamedAgg(
            column="pvfb_retire_current",
            aggfunc=lambda x: (x * projected.loc[x.index, "n_retire_current"]).sum(),
        ),
    ).reset_index()

    return summary


def main():
    with open(BASE / "configs" / "calibration_params.json") as f:
        cal = json.load(f)
    with open(BASELINE / "input_params.json") as f:
        params_raw = json.load(f)

    params = {
        "start_year": params_raw["start_year"][0],
        "model_period": params_raw["model_period"][0],
    }

    classes = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]

    print("=" * 80)
    print("Current Retiree AAL Validation: Python vs R Baseline")
    print("=" * 80)

    all_pass = True
    for cls in classes:
        print(f"\n  {cls.upper()}")

        try:
            py = compute_retire_current(cls, params, cal)
            lib = pd.read_csv(BASELINE / f"{cls}_liability.csv")
        except Exception as e:
            print(f"    ERROR: {e}")
            import traceback
            traceback.print_exc()
            all_pass = False
            continue

        # Compare retire_ben_current_est
        comp = py.merge(lib[["year", "retire_ben_current_est", "aal_retire_current_est"]],
                        on="year", suffixes=("_py", "_r"))

        for label, py_col, r_col in [
            ("retire_ben_current", "retire_ben_current_est_py", "retire_ben_current_est_r"),
            ("aal_retire_current", "aal_retire_current_est_py", "aal_retire_current_est_r"),
        ]:
            mask = comp[r_col].abs() > 1e-6
            if mask.any():
                pct = ((comp.loc[mask, py_col] - comp.loc[mask, r_col]).abs()
                       / comp.loc[mask, r_col].abs() * 100)
                max_pct = pct.max()
                mean_pct = pct.mean()
            else:
                max_pct = mean_pct = 0.0

            status = "PASS" if max_pct < 0.001 else "FAIL"
            if status != "PASS":
                all_pass = False
            print(f"    {label:30s}  max={max_pct:10.6f}%  mean={mean_pct:10.6f}%  {status}")

        # Show first 5 years detail for aal
        print(f"    {'Year':>6} {'Python':>20} {'R':>20} {'Diff%':>12}")
        for _, row in comp.head(5).iterrows():
            r_val = row["aal_retire_current_est_r"]
            py_val = row["aal_retire_current_est_py"]
            pct = abs(py_val - r_val) / abs(r_val) * 100 if abs(r_val) > 1e-6 else 0
            print(f"    {int(row['year']):>6} {py_val:>20,.2f} {r_val:>20,.2f} {pct:>11.6f}%")

    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")


if __name__ == "__main__":
    main()
