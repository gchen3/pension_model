#!/usr/bin/env python
"""
CLI entry point for the pension model.

Usage:
    pension-model frs              # run FRS model + validate + unit tests
    pension-model frs --no-test    # run FRS model only, skip validation and tests
    pension-model frs --test-only  # unit tests only
"""

import sys
import time
import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd


BASELINE = Path("baseline_outputs")
CLASSES = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]


def run_pipeline(e2e=True):
    """Run liability + funding pipeline for all 7 classes."""
    from pension_model.core.pipeline import run_class_pipeline, run_class_pipeline_e2e
    from pension_model.core.funding_model import load_funding_inputs, compute_funding
    from pension_model.core.model_constants import frs_constants

    constants = frs_constants()
    pipeline_fn = run_class_pipeline_e2e if e2e else run_class_pipeline
    liability = {}
    for cn in CLASSES:
        liability[cn] = pipeline_fn(cn, BASELINE, constants)
    funding_inputs = load_funding_inputs(BASELINE)
    funding = compute_funding(liability, funding_inputs, constants)
    return liability, funding


def validate(funding):
    """Compare funding results against R baseline. Returns True if all pass."""
    cols = ["total_aal", "total_ava", "total_mva", "total_er_cont", "fr_ava",
            "total_payroll", "nc_rate_db_legacy", "er_amo_cont_legacy"]
    all_ok = True
    for cn in CLASSES:
        rf = pd.read_csv(BASELINE / f"{cn}_funding.csv")
        pf = funding[cn]
        max_diff = 0
        for col in cols:
            if col in pf.columns and col in rf.columns:
                rv, pv = rf[col].values, pf[col].values
                mask = np.abs(rv) > 1e-6
                n = min(mask.sum(), len(pv))
                if n > 0:
                    pct = np.abs(pv[mask[:len(pv)]][:n] - rv[mask][:n]) / np.abs(rv[mask][:n]) * 100
                    max_diff = max(max_diff, pct.max())
        status = "PASS" if max_diff < 0.01 else "FAIL"
        if status != "PASS":
            all_ok = False
        print(f"  {cn:>20}  {status}  max_diff={max_diff:.4f}%")
    return all_ok


def run_unit_tests():
    """Run pytest unit tests."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pension_model/test_benefit_tables.py",
         "-v", "--tb=short"],
    )
    return result.returncode == 0


def cmd_frs(args):
    """Run the Florida FRS pension model."""
    if args.test_only:
        print("Running unit tests...")
        ok = run_unit_tests()
        sys.exit(0 if ok else 1)

    print("=" * 60)
    print("FRS Pension Model Pipeline")
    print("=" * 60)

    t0 = time.time()
    print("\nRunning liability + funding pipeline...")
    liability, funding = run_pipeline()
    elapsed = time.time() - t0
    print(f"Pipeline complete: {elapsed:.0f}s")

    if not args.no_test:
        print("\nValidating against R baseline:")
        all_ok = validate(funding)
        print(f"\nResult: {'ALL PASS' if all_ok else 'FAILURES'}  ({time.time() - t0:.0f}s)")

        print("\nRunning unit tests...")
        tests_ok = run_unit_tests()

        if all_ok and tests_ok:
            print("\nAll checks passed.")
            sys.exit(0)
        else:
            print("\nSome checks failed.")
            sys.exit(1)
    else:
        print(f"\nDone ({elapsed:.0f}s, validation skipped)")


def main():
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser(description="Pension model CLI")
    subparsers = parser.add_subparsers(dest="plan", help="Plan to run")

    frs = subparsers.add_parser("frs", help="Florida Retirement System")
    frs.add_argument("--no-test", action="store_true", help="Skip validation")
    frs.add_argument("--test-only", action="store_true", help="Run unit tests only")

    args = parser.parse_args()

    if args.plan is None:
        parser.print_help()
        sys.exit(1)

    if args.plan == "frs":
        cmd_frs(args)
