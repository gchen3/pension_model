#!/usr/bin/env python
"""
CLI entry point for the pension model.

Usage:
    pension-model run <plan>              # run plan model + tests
    pension-model run <plan> --no-test    # run plan model only
    pension-model run <plan> --test-only  # tests only (no model run)
    pension-model calibrate <plan>        # compute calibration factors
    pension-model list                    # list discovered plans

Plans are auto-discovered from ``configs/<plan>/plan_config.json``.
"""

import sys
import time
import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd


BASELINE = Path("baseline_outputs")
OUTPUT_BASE = Path("output")


def _fmt_dollars(val):
    """Format a dollar value in billions."""
    return f"${val / 1e9:.1f}B"


def _fmt_pct(val):
    """Format a ratio as percentage."""
    return f"{val * 100:.1f}%"


def run_pipeline(constants):
    """Run liability + funding pipeline for all groups in a plan."""
    from pension_model.core.pipeline import run_class_pipeline_e2e
    from pension_model.core.funding_model import load_funding_inputs, compute_funding

    classes = list(constants.classes)
    n = len(classes)
    liability_frames = []

    print("  Building benefit tables, workforce, and liabilities (this may take a while)...")
    for i, cn in enumerate(classes):
        pct = int(i / n * 100)
        sys.stdout.write(f"\r    {pct:3d}%")
        sys.stdout.flush()
        df = run_class_pipeline_e2e(cn, BASELINE, constants)
        df["plan_name"] = constants.plan_name
        df["class_name"] = cn
        liability_frames.append(df)
    sys.stdout.write(f"\r    100% done\n")
    sys.stdout.flush()

    # Stacked liability: single DataFrame with plan_name + class_name columns
    liability_stacked = pd.concat(liability_frames, ignore_index=True)

    # Per-class dict for funding model (until funding is also stacked)
    liability = {cn: liability_stacked[liability_stacked["class_name"] == cn].drop(
        columns=["plan_name", "class_name"]).reset_index(drop=True) for cn in classes}

    print("  Computing funding...")
    funding_inputs = load_funding_inputs(BASELINE)
    funding = compute_funding(liability, funding_inputs, constants)

    return liability, funding, liability_stacked


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
    print(f"    Plan config:            {constants.plan_name}")
    print(f"    Mortality table:        Pub-2010, MP-2018 improvement scale")


def write_output(funding, classes, output_dir):
    """Write summary CSV and print console summary."""
    # Aggregate across all groups by year
    frames = []
    for cn in classes:
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
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "funding_summary.csv"
    totals.to_csv(csv_path, index=False)

    # Also write per-group detail
    all_groups.to_csv(output_dir / "funding_by_group.csv", index=False)

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

    rel = output_dir.relative_to(Path.cwd()) if output_dir.is_relative_to(Path.cwd()) else output_dir
    print(f"\n  Files:")
    print(f"    {rel}/funding_summary.csv   - plan-wide totals by year")
    print(f"    {rel}/funding_by_group.csv  - detail by group and year")
    print(f"    {rel}/liability_stacked.csv - liability by class and year")


def run_tests():
    """Run all baseline validation and unit tests via pytest."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pension_model/", "-v", "--tb=short"],
    )
    return result.returncode == 0


def _emit_truth_table(plan_name, liability, funding, constants, output_dir):
    """Build the Python truth table, write CSV + Excel sheet, log to stdout.

    Called before tests run so users always see the aggregate comparison
    even when tests are skipped. Failures here are logged but do not abort
    the run — the truth table is a diagnostic aid, not a gate.
    """
    try:
        from pension_model.truth_table import (
            build_python_truth_table,
            format_truth_table_for_log,
            upsert_sheet_to_excel,
        )

        df = build_python_truth_table(plan_name, liability, funding, constants)

        # CSV next to the other outputs
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "truth_table.csv"
        df.to_csv(csv_path, index=False)

        # Python sheet in the shared workbook (preserves frozen R sheets)
        xlsx_path = OUTPUT_BASE / "truth_tables.xlsx"
        upsert_sheet_to_excel(df, xlsx_path, f"{plan_name}_Py")

        print("\n  Truth table (Python, plan-wide):")
        print(format_truth_table_for_log(df))
        rel_csv = csv_path.relative_to(Path.cwd()) if csv_path.is_relative_to(Path.cwd()) else csv_path
        rel_xlsx = xlsx_path.relative_to(Path.cwd()) if xlsx_path.is_relative_to(Path.cwd()) else xlsx_path
        print(f"\n  Wrote {rel_csv}")
        print(f"  Updated sheet '{plan_name}_Py' in {rel_xlsx}")
    except Exception as e:  # noqa: BLE001 — diagnostic aid must not crash the run
        print(f"\n  WARNING: truth table could not be written: {type(e).__name__}: {e}")


def cmd_calibrate(args):
    """Run calibration: compute nc_cal and pvfb_term_current from AV targets."""
    from pension_model.core.pipeline import run_class_pipeline_e2e
    from pension_model.plan_config import discover_plans, load_plan_config
    from pension_model.core.funding_model import load_funding_inputs
    from pension_model.core.calibration import (
        load_targets_from_init_funding, run_calibration, format_diagnostics,
        write_calibration_json,
    )

    plan_name = args.plan_name
    if plan_name != "frs":
        print(f"  Calibration for '{plan_name}' is not yet supported. Only 'frs' is available.")
        sys.exit(1)

    plans = discover_plans()
    if plan_name not in plans:
        print(f"  Config not found for plan {plan_name!r}. Discovered: {sorted(plans)}")
        sys.exit(1)
    config_path = plans[plan_name]

    print("=" * 60)
    print(f"{plan_name.upper()} Calibration")
    print("=" * 60)

    t0 = time.time()

    # Load config without calibration → neutral (nc_cal=1.0, pvfb_term_current=0)
    constants = load_plan_config(config_path, calibration_path=Path("__no_calibration__"))
    cal_factor = constants.benefit.cal_factor
    classes = list(constants.classes)

    # Build calibration targets from init_funding_data + known AV NC rates
    funding_inputs = load_funding_inputs(BASELINE)
    val_norm_costs = {cn: constants.class_data[cn].val_norm_cost for cn in classes}
    targets = load_targets_from_init_funding(funding_inputs["init_funding"], val_norm_costs)

    # Run pipeline with neutral calibration
    n = len(classes)
    liability = {}
    print("  Running uncalibrated pipeline...")
    for i, cn in enumerate(classes):
        pct = int(i / n * 100)
        sys.stdout.write(f"\r    {pct:3d}%")
        sys.stdout.flush()
        liability[cn] = run_class_pipeline_e2e(cn, BASELINE, constants)
    sys.stdout.write(f"\r    100% done\n")
    sys.stdout.flush()

    # Compute calibration
    results = run_calibration(liability, targets, constants.ranges.start_year)

    elapsed = time.time() - t0
    print(f"  Calibration complete: {elapsed:.0f}s\n")

    # Print diagnostics
    print(format_diagnostics(results, targets, cal_factor))

    # Write calibration JSON if requested
    if args.write:
        output_path = Path(args.output) if args.output else Path(f"configs/{plan_name}/calibration.json")
        write_calibration_json(cal_factor, results, output_path)
        print(f"\n  Calibration written to {output_path}")


# ---------------------------------------------------------------------------
# Per-plan runners
#
# Each plan currently has its own funding pipeline shape (FRS uses the
# per-class dict + compute_funding; TRS uses compute_funding_trs on the
# single 'all' class), so we dispatch internally. Collapsing these into a
# single generic runner is goal 2b — removing the legacy loaders — which
# will come next on its own branch.
# ---------------------------------------------------------------------------

def _run_frs(constants, args):
    """Run the FRS liability + funding pipeline and emit outputs."""
    print("=" * 60)
    print("FRS Pension Model Pipeline")
    print("=" * 60)

    t0 = time.time()
    liability, funding, liability_stacked = run_pipeline(constants)
    elapsed = time.time() - t0
    print(f"  Pipeline complete: {elapsed:.0f}s")

    output_dir = OUTPUT_BASE / constants.plan_name
    print_parameters(constants)
    write_output(funding, list(constants.classes), output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    liability_stacked.to_csv(output_dir / "liability_stacked.csv", index=False)

    # Truth table BEFORE tests so it prints regardless of --no-test
    _emit_truth_table(constants.plan_name, liability, funding, constants, output_dir)


def _run_txtrs(constants, args):
    """Run the Texas TRS liability + funding pipeline and emit outputs."""
    from pension_model.core.pipeline import run_class_pipeline_e2e
    from pension_model.core.funding_model import compute_funding_trs
    from pension_model.core.txtrs_loader import load_txtrs_funding_data

    print("=" * 60)
    print("Texas TRS Pension Model Pipeline")
    print("=" * 60)

    t0 = time.time()

    # Run liability pipeline for each class (TRS has only "all")
    print("  Building benefit tables, workforce, and liabilities...")
    liability_results = {}
    liability_frames = []
    for cn in constants.classes:
        df = run_class_pipeline_e2e(cn, BASELINE, constants)
        df["plan_name"] = constants.plan_name
        df["class_name"] = cn
        liability_results[cn] = df
        liability_frames.append(df)

    liability_stacked = pd.concat(liability_frames, ignore_index=True)

    print("  Running funding model...")
    raw_dir = Path("R_model/R_model_txtrs")
    funding_inputs = load_txtrs_funding_data(raw_dir)
    funding_df = compute_funding_trs(liability_results["all"], funding_inputs, constants)

    elapsed = time.time() - t0
    print(f"  Pipeline complete: {elapsed:.0f}s")

    output_dir = OUTPUT_BASE / constants.plan_name
    output_dir.mkdir(parents=True, exist_ok=True)
    liability_stacked.to_csv(output_dir / "liability_stacked.csv", index=False)
    funding_df.to_csv(output_dir / "funding.csv", index=False)
    print(f"  Output written to {output_dir}/")

    _emit_truth_table(constants.plan_name, liability_results, funding_df, constants, output_dir)

    row1 = liability_stacked.iloc[0]
    total_aal = row1.get("total_aal_est", row1.get("aal_est", 0))
    print(f"\n  Year 1 summary:")
    print(f"    Total AAL:     {_fmt_dollars(total_aal)}")
    if "payroll_est" in row1:
        print(f"    Payroll:       {_fmt_dollars(row1['payroll_est'])}")
    if "nc_rate_est" in row1:
        print(f"    NC Rate:       {_fmt_pct(row1['nc_rate_est'])}")
    if len(funding_df) > 1:
        fy1 = funding_df.iloc[1]
        print(f"    Funded Ratio:  {_fmt_pct(fy1.get('FR_AVA', 0))}")
        print(f"    ER Cont Rate:  {_fmt_pct(fy1.get('er_cont_rate', 0))}")


# Registry mapping plan name → runner. A plan must be listed here to be
# runnable via `pension-model run`; discover_plans() alone is not enough
# because each plan still has plan-specific pipeline glue.
_PLAN_RUNNERS = {
    "frs": _run_frs,
    "txtrs": _run_txtrs,
}


def cmd_run(args):
    """Dispatch `pension-model run <plan>` to the per-plan runner."""
    from pension_model.plan_config import discover_plans, load_plan_config

    if args.test_only:
        print(f"Running tests...")
        ok = run_tests()
        sys.exit(0 if ok else 1)

    plans = discover_plans()
    if args.plan not in plans:
        available = ", ".join(sorted(plans)) or "(none found)"
        print(f"Unknown plan: {args.plan!r}. Available plans: {available}")
        sys.exit(2)

    if args.plan not in _PLAN_RUNNERS:
        print(f"Plan {args.plan!r} has a config but no runner registered in cli._PLAN_RUNNERS.")
        sys.exit(2)

    config_path = plans[args.plan]
    cal_path = config_path.parent / "calibration.json"
    constants = load_plan_config(
        config_path,
        calibration_path=cal_path if cal_path.exists() else None,
    )

    _PLAN_RUNNERS[args.plan](constants, args)

    if not args.no_test:
        print("\nRunning tests...")
        tests_ok = run_tests()
        sys.exit(0 if tests_ok else 1)


def cmd_list(args):
    """List discovered plans and whether each has a registered runner."""
    from pension_model.plan_config import discover_plans

    plans = discover_plans()
    if not plans:
        print("No plans found under configs/")
        return
    print("Discovered plans:")
    for name, path in sorted(plans.items()):
        status = "runnable" if name in _PLAN_RUNNERS else "config only"
        rel = path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path
        print(f"  {name:20s} {status:12s} {rel}")


def main():
    warnings.filterwarnings("ignore")

    from pension_model.plan_config import discover_plans
    discovered = sorted(discover_plans().keys())

    parser = argparse.ArgumentParser(prog="pension-model", description="Pension model CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    run_p = subparsers.add_parser("run", help="Run a plan's liability + funding pipeline")
    run_p.add_argument("plan", choices=discovered or None,
                       help=f"Plan to run. Discovered: {', '.join(discovered) or '(none)'}")
    run_p.add_argument("--no-test", action="store_true", help="Skip tests after the run")
    run_p.add_argument("--test-only", action="store_true", help="Run tests only, skip the model")

    cal = subparsers.add_parser("calibrate", help="Compute calibration factors")
    cal.add_argument("plan_name", choices=discovered or None,
                     help=f"Plan to calibrate. Discovered: {', '.join(discovered) or '(none)'}")
    cal.add_argument("--write", action="store_true", help="Write calibration to JSON")
    cal.add_argument("--output", type=str, default=None, help="Output path for calibration JSON")

    subparsers.add_parser("list", help="List discovered plans")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "calibrate":
        cmd_calibrate(args)
    elif args.command == "list":
        cmd_list(args)
