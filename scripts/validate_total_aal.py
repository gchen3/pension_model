"""
Validate total AAL = sum of all components against R baseline.

Components (all validated individually):
  1. aal_active_db_legacy_est     (validated 0.00%)
  2. aal_term_db_legacy_est       (validated 0.00% - projected term)
  3. aal_retire_db_legacy_est     (validated 0.00% - projected retire)
  4. aal_retire_current_est       (validated ~0.004% - current retirees)
  5. aal_term_current_est         (validated 0.00% - current term vested)
  + new components for db_new (aal_active_db_new_est, aal_term_db_new_est, aal_retire_db_new_est)

aal_legacy = (1) + (2) + (3) + (4) + (5)
aal_new    = aal_active_db_new + aal_term_db_new + aal_retire_db_new
total_aal  = aal_legacy + aal_new

Also validates: tot_ben_refund (benefit payments + refunds)
"""

import json
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).parent.parent
BASELINE = BASE / "baseline_outputs"


def validate_class(class_name):
    """Check that R's total_aal equals sum of individual components."""
    lib = pd.read_csv(BASELINE / f"{class_name}_liability.csv")

    # R computes total_aal as sum of components - let's verify that decomposition
    # matches what's in the liability file

    # aal_legacy = active + term_proj + retire_proj + retire_current + term_current
    lib["py_aal_legacy"] = (
        lib["aal_active_db_legacy_est"]
        + lib["aal_term_db_legacy_est"]
        + lib["aal_retire_db_legacy_est"]
        + lib["aal_retire_current_est"]
        + lib["aal_term_current_est"]
    )

    # aal_new = active_new + term_new + retire_new
    lib["py_aal_new"] = (
        lib["aal_active_db_new_est"]
        + lib["aal_term_db_new_est"]
        + lib["aal_retire_db_new_est"]
    )

    lib["py_total_aal"] = lib["py_aal_legacy"] + lib["py_aal_new"]

    # Compare
    results = {}
    for label, py_col, r_col in [
        ("aal_legacy", "py_aal_legacy", "aal_legacy_est"),
        ("aal_new", "py_aal_new", "aal_new_est"),
        ("total_aal", "py_total_aal", "total_aal_est"),
    ]:
        mask = np.abs(lib[r_col]) > 1e-6
        if mask.any():
            pct = np.abs(lib.loc[mask, py_col] - lib.loc[mask, r_col]) / np.abs(lib.loc[mask, r_col]) * 100
            results[label] = {"max_pct": pct.max(), "mean_pct": pct.mean()}
        else:
            results[label] = {"max_pct": 0.0, "mean_pct": 0.0}

    # Also verify benefit payment totals
    lib["py_tot_ben_legacy"] = (
        lib["refund_db_legacy_est"]
        + lib["retire_ben_db_legacy_est"]
        + lib["retire_ben_current_est"]
        + lib["retire_ben_term_est"]
    )
    lib["py_tot_ben_new"] = lib["refund_db_new_est"] + lib["retire_ben_db_new_est"]

    for label, py_col, r_col in [
        ("tot_ben_legacy", "py_tot_ben_legacy", "tot_ben_refund_legacy_est"),
        ("tot_ben_new", "py_tot_ben_new", "tot_ben_refund_new_est"),
    ]:
        mask = np.abs(lib[r_col]) > 1e-6
        if mask.any():
            pct = np.abs(lib.loc[mask, py_col] - lib.loc[mask, r_col]) / np.abs(lib.loc[mask, r_col]) * 100
            results[label] = {"max_pct": pct.max(), "mean_pct": pct.mean()}
        else:
            results[label] = {"max_pct": 0.0, "mean_pct": 0.0}

    # Verify liability gain/loss = 0 (experience = assumptions)
    lib_gl = lib["total_liability_gain_loss_est"].abs().max()
    results["liability_gain_loss"] = {"max_abs": lib_gl}

    return lib, results


def main():
    classes = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]

    print("=" * 80)
    print("Total AAL Aggregation Validation")
    print("=" * 80)

    all_pass = True
    for cls in classes:
        lib, results = validate_class(cls)

        all_ok = all(
            v.get("max_pct", 0) < 0.01 for k, v in results.items() if k != "liability_gain_loss"
        )
        status = "PASS" if all_ok else "FAIL"
        if not all_ok:
            all_pass = False

        print(f"\n  {cls.upper():25s}  {status}")
        for label, info in results.items():
            if "max_pct" in info:
                print(f"    {label:25s}  max={info['max_pct']:8.4f}%  mean={info['mean_pct']:8.4f}%")
            elif "max_abs" in info:
                print(f"    {label:25s}  max_abs={info['max_abs']:12.1f}")

        # Show total AAL for first and last year
        yr1 = lib.iloc[0]
        yr_last = lib.iloc[-1]
        print(f"    Year {int(yr1['year'])}: total_aal = {yr1['total_aal_est']:20,.0f}")
        print(f"    Year {int(yr_last['year'])}: total_aal = {yr_last['total_aal_est']:20,.0f}")

    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")


if __name__ == "__main__":
    main()
