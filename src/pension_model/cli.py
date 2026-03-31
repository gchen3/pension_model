#!/usr/bin/env python
"""
CLI entry point for the pension model.

Usage:
    pension-model frs              # run FRS model + tests
    pension-model frs --no-test    # run FRS model only
    pension-model frs --test-only  # tests only (no model run)
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
OUTPUT_DIR = Path("output")


def _fmt_dollars(val):
    """Format a dollar value in billions."""
    return f"${val / 1e9:.1f}B"


def _fmt_pct(val):
    """Format a ratio as percentage."""
    return f"{val * 100:.1f}%"


def run_pipeline(e2e=True):
    """Run liability + funding pipeline for all groups."""
    from pension_model.core.pipeline import run_class_pipeline, run_class_pipeline_e2e
    from pension_model.core.funding_model import load_funding_inputs, compute_funding
    from pension_model.core.model_constants import frs_constants

    constants = frs_constants()
    pipeline_fn = run_class_pipeline_e2e if e2e else run_class_pipeline

    n = len(CLASSES)
    liability = {}

    print("  Building benefit tables, workforce, and liabilities (this may take a while)...")
    for i, cn in enumerate(CLASSES):
        pct = int(i / n * 100)
        sys.stdout.write(f"\r    {pct:3d}%")
        sys.stdout.flush()
        liability[cn] = pipeline_fn(cn, BASELINE, constants)
    sys.stdout.write(f"\r    100% done\n")
    sys.stdout.flush()

    print("  Computing funding...")
    funding_inputs = load_funding_inputs(BASELINE)
    funding = compute_funding(liability, funding_inputs, constants)

    return liability, funding, constants


def print_parameters(constants):
    """Print key model parameters."""
    ec = constants.economic
    bn = constants.benefit
    fn = constants.funding
    rn = constants.ranges

    print(f"\n  Parameters (baseline defaults):")
    print(f"    Discount rate:          {ec.dr_current:.1%}")
    print(f"    Investment return:      {ec.model_return:.1%}")
    print(f"    Payroll growth:         {ec.payroll_growth:.2%}")
    print(f"    Inflation:              {ec.inflation:.1%}")
    print(f"    COLA (current retire):  {bn.cola_current_retire:.0%}")
    print(f"    Funding policy:         {fn.funding_policy}")
    print(f"    Amortization method:    {fn.amo_method}, {fn.amo_period_new}-year period")
    print(f"    Projection horizon:     {rn.model_period} years ({rn.start_year}-{rn.start_year + rn.model_period})")
    print(f"    Mortality table:        Pub-2010, MP-2018 improvement scale")


def write_output(funding):
    """Write summary CSV and print console summary."""
    # Aggregate across all groups by year
    frames = []
    for cn in CLASSES:
        df = funding[cn][["year", "total_aal", "total_ava", "total_ual_ava",
                          "total_er_cont", "total_payroll", "fr_ava"]].copy()
        df["group"] = cn
        frames.append(df)
    all_groups = pd.concat(frames, ignore_index=True)

    totals = all_groups.groupby("year").agg(
        aal=("total_aal", "sum"),
        ava=("total_ava", "sum"),
        ual=("total_ual_ava", "sum"),
        er_cont=("total_er_cont", "sum"),
        payroll=("total_payroll", "sum"),
    ).reset_index()
    totals["funded_ratio"] = np.divide(
        totals["ava"].values, totals["aal"].values,
        out=np.zeros(len(totals)), where=totals["aal"].values != 0)

    # Write detailed CSV
    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUT_DIR / "funding_summary.csv"
    totals.to_csv(csv_path, index=False)

    # Also write per-group detail
    all_groups.to_csv(OUTPUT_DIR / "funding_by_group.csv", index=False)

    # Console summary
    y1 = totals.iloc[0]
    y30 = totals.iloc[min(29, len(totals) - 1)]

    print(f"\n  Summary (all groups combined):")
    print(f"  {'':30s} {'Year 1 (' + str(int(y1['year'])) + ')':>16s}  {'Year 30 (' + str(int(y30['year'])) + ')':>16s}")
    print(f"  {'Assets (AVA)':30s} {_fmt_dollars(y1['ava']):>16s}  {_fmt_dollars(y30['ava']):>16s}")
    print(f"  {'Liabilities (AAL)':30s} {_fmt_dollars(y1['aal']):>16s}  {_fmt_dollars(y30['aal']):>16s}")
    print(f"  {'Unfunded liability (UAL)':30s} {_fmt_dollars(y1['ual']):>16s}  {_fmt_dollars(y30['ual']):>16s}")
    print(f"  {'Funded ratio':30s} {_fmt_pct(y1['funded_ratio']):>16s}  {_fmt_pct(y30['funded_ratio']):>16s}")
    print(f"  {'Employer contribution':30s} {_fmt_dollars(y1['er_cont']):>16s}  {_fmt_dollars(y30['er_cont']):>16s}")

    print(f"\n  Files:")
    print(f"    output/funding_summary.csv   - plan-wide totals by year")
    print(f"    output/funding_by_group.csv  - detail by group and year")
    print(f"    baseline_outputs/            - input data and R baseline for validation")


def run_tests():
    """Run all baseline validation and unit tests via pytest."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pension_model/", "-v", "--tb=short"],
    )
    return result.returncode == 0


def cmd_frs(args):
    """Run the Florida FRS pension model."""
    if args.test_only:
        print("Running tests...")
        ok = run_tests()
        sys.exit(0 if ok else 1)

    print("=" * 60)
    print("FRS Pension Model Pipeline")
    print("=" * 60)

    t0 = time.time()
    liability, funding, constants = run_pipeline()
    elapsed = time.time() - t0
    print(f"  Pipeline complete: {elapsed:.0f}s")

    print_parameters(constants)
    write_output(funding)

    if not args.no_test:
        print("\nRunning tests...")
        tests_ok = run_tests()
        sys.exit(0 if tests_ok else 1)


def main():
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser(description="Pension model CLI")
    subparsers = parser.add_subparsers(dest="plan", help="Plan to run")

    frs = subparsers.add_parser("frs", help="Florida Retirement System")
    frs.add_argument("--no-test", action="store_true", help="Skip tests")
    frs.add_argument("--test-only", action="store_true", help="Run tests only")

    args = parser.parse_args()

    if args.plan is None:
        parser.print_help()
        sys.exit(1)

    if args.plan == "frs":
        cmd_frs(args)
