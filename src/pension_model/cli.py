#!/usr/bin/env python
"""
CLI entry point for the pension model.

Usage:
    pension-model run <plan>              # run plan model + tests
    pension-model run <plan> --no-test    # run plan model only
    pension-model run <plan> --test-only  # tests only (no model run)
    pension-model run <plan> --truth-table  # also write R-vs-Python truth table
    pension-model calibrate <plan>        # compute calibration factors
    pension-model list                    # list discovered plans

Plans are auto-discovered from ``plans/<plan>/config/plan_config.json``.
"""

import sys
import time
import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT_BASE = Path("output")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_dollars(val):
    """Format a dollar value in billions."""
    return f"${val / 1e9:.1f}B"


def _fmt_pct(val):
    """Format a ratio as percentage."""
    return f"{val * 100:.1f}%"


def _fmt_smoothing(cfg):
    """Describe asset smoothing from config dict."""
    sm = cfg.ava_smoothing
    method = sm.get("method", "unknown")
    if method == "corridor":
        lo = sm.get("corridor_low", 0.8)
        hi = sm.get("corridor_high", 1.2)
        recog = sm.get("gain_loss_recognition", 0.2)
        return f"corridor ({lo:.0%}-{hi:.0%} of MVA), {recog:.0%}/yr gain-loss recognition"
    elif method == "gain_loss":
        period = sm.get("recognition_period", 4)
        return f"{period}-year gain-loss recognition"
    else:
        return method


# ---------------------------------------------------------------------------
# Plan summary — standardized analysis output for any plan
# ---------------------------------------------------------------------------

# Columns in summary.csv (plan-wide, by year).
SUMMARY_COLUMNS = [
    "plan", "year",
    "n_active", "payroll", "benefits",
    "aal", "ual_ava", "ual_mva",
    "er_cont", "ee_cont",
    "mva", "ava", "invest_income",
    "fr_mva", "fr_ava",
]


def _col(df, *names):
    """Return the first matching column's values, or None."""
    for n in names:
        if n in df.columns:
            return df[n].values
    return None


def _col_sum(df, *name_pairs):
    """Sum two columns (legacy + new pattern). Return None if neither found."""
    a = _col(df, *name_pairs[0]) if isinstance(name_pairs[0], tuple) else _col(df, name_pairs[0])
    b = _col(df, *name_pairs[1]) if isinstance(name_pairs[1], tuple) else _col(df, name_pairs[1])
    if a is not None and b is not None:
        return a + b
    return a if a is not None else b


def build_plan_summary(plan_name, liability, funding, constants):
    """Build a plan-wide summary DataFrame with standardized columns.

    Works for any plan — extracts the same metrics regardless of whether
    funding is a dict-of-DataFrames (FRS) or a single DataFrame (TRS).
    This is the primary analysis output; it persists even after truth
    tables are retired.
    """
    classes = list(constants.classes)

    # Sum headcounts across all classes
    n_active = None
    for cn in classes:
        col = liability[cn]["total_n_active"].values
        n_active = col if n_active is None else n_active + col

    # Get aggregate funding — FRS uses a plan-level key, TRS is a single df
    if isinstance(funding, dict):
        f = funding.get(plan_name, funding.get(classes[0]))
    else:
        f = funding

    year = _col(f, "year", "fy")
    payroll = _col(f, "total_payroll")
    benefits = _col_sum(f, ("ben_payment_legacy",), ("ben_payment_new",))
    if benefits is None:
        benefits = _col(f, "total_ben_payment")
    aal = _col(f, "total_aal")
    ava = _col(f, "total_ava")
    mva = _col(f, "total_mva")
    ual_ava = _col(f, "total_ual_ava")
    ual_mva = _col(f, "total_ual_mva")
    er_cont = _col(f, "total_er_cont")
    ee_cont = _col_sum(f, ("ee_nc_cont_legacy",), ("ee_nc_cont_new",))
    if ee_cont is None:
        ee_cont = _col(f, "total_ee_nc_cont")
    fr_ava = _col(f, "fr_ava")
    fr_mva = _col(f, "fr_mva")
    invest_income = _col_sum(
        f,
        ("exp_inv_earnings_ava_legacy", "exp_inv_income_legacy"),
        ("exp_inv_earnings_ava_new", "exp_inv_income_new"),
    )

    n_rows = len(year) if year is not None else len(f)

    def _safe(arr):
        return arr if arr is not None else np.full(n_rows, np.nan)

    return pd.DataFrame({
        "plan": plan_name,
        "year": pd.array(year, dtype="Int64") if year is not None else range(n_rows),
        "n_active": _safe(n_active),
        "payroll": _safe(payroll),
        "benefits": _safe(benefits),
        "aal": _safe(aal),
        "ual_ava": _safe(ual_ava),
        "ual_mva": _safe(ual_mva),
        "er_cont": _safe(er_cont),
        "ee_cont": _safe(ee_cont),
        "mva": _safe(mva),
        "ava": _safe(ava),
        "invest_income": _safe(invest_income),
        "fr_mva": _safe(fr_mva),
        "fr_ava": _safe(fr_ava),
    })[SUMMARY_COLUMNS]


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

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
    print(f"    COLA (retirees):        {bn.cola_current_retire:.0%}")
    print(f"    Funding policy:         {fn.funding_policy}")
    print(f"    Amortization:           {fn.amo_method}, {fn.amo_period_new}-year period")
    print(f"    Asset smoothing:        {_fmt_smoothing(fn)}")
    print(f"    Projection horizon:     {rn.model_period} years ({rn.start_year}-{rn.start_year + rn.model_period})")
    print(f"    Plan config:            {constants.plan_name}")


def print_summary_table(summary):
    """Print start-year / final-year comparison table to console."""
    y1 = summary.iloc[0]
    y_last = summary.iloc[-1]

    print(f"\n  Summary (all groups combined):")
    print(f"  {'':30s} {str(int(y1['year'])):>16s}  {str(int(y_last['year'])):>16s}")
    print(f"  {'Assets (AVA)':30s} {_fmt_dollars(y1['ava']):>16s}  {_fmt_dollars(y_last['ava']):>16s}")
    print(f"  {'Assets (MVA)':30s} {_fmt_dollars(y1['mva']):>16s}  {_fmt_dollars(y_last['mva']):>16s}")
    print(f"  {'Liabilities (AAL)':30s} {_fmt_dollars(y1['aal']):>16s}  {_fmt_dollars(y_last['aal']):>16s}")
    print(f"  {'Unfunded liability (UAL)':30s} {_fmt_dollars(y1['ual_ava']):>16s}  {_fmt_dollars(y_last['ual_ava']):>16s}")
    print(f"  {'Funded ratio (AVA)':30s} {_fmt_pct(y1['fr_ava']):>16s}  {_fmt_pct(y_last['fr_ava']):>16s}")
    print(f"  {'Funded ratio (MVA)':30s} {_fmt_pct(y1['fr_mva']):>16s}  {_fmt_pct(y_last['fr_mva']):>16s}")
    print(f"  {'Active members':30s} {y1['n_active']:>16,.0f}  {y_last['n_active']:>16,.0f}")
    print(f"  {'Payroll':30s} {_fmt_dollars(y1['payroll']):>16s}  {_fmt_dollars(y_last['payroll']):>16s}")
    print(f"  {'Benefit payments':30s} {_fmt_dollars(y1['benefits']):>16s}  {_fmt_dollars(y_last['benefits']):>16s}")
    print(f"  {'Employer contributions':30s} {_fmt_dollars(y1['er_cont']):>16s}  {_fmt_dollars(y_last['er_cont']):>16s}")
    print(f"  {'Employee contributions':30s} {_fmt_dollars(y1['ee_cont']):>16s}  {_fmt_dollars(y_last['ee_cont']):>16s}")


def _write_outputs(summary, liability_stacked, output_dir):
    """Write summary.csv and liability_stacked.csv."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "summary.csv", index=False)
    liability_stacked.to_csv(output_dir / "liability_stacked.csv", index=False)

    rel = output_dir.relative_to(Path.cwd()) if output_dir.is_relative_to(Path.cwd()) else output_dir
    print(f"\n  Files:")
    print(f"    {rel}/summary.csv            - plan-wide summary by year")
    print(f"    {rel}/liability_stacked.csv  - liability detail by class and year")


# ---------------------------------------------------------------------------
# Truth table (optional, for R-vs-Python comparison)
# ---------------------------------------------------------------------------

def _emit_truth_table(plan_name, liability, funding, constants, output_dir):
    """Build the Python truth table, write CSV + Excel sheet.

    Called only when --truth-table is passed. Failures are logged but
    do not abort the run — the truth table is a diagnostic aid.
    """
    try:
        from pension_model.truth_table import (
            build_python_truth_table,
            upsert_sheet_to_excel,
        )

        df = build_python_truth_table(plan_name, liability, funding, constants)

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "truth_table.csv"
        df.to_csv(csv_path, index=False)

        xlsx_path = OUTPUT_BASE / "truth_tables.xlsx"
        upsert_sheet_to_excel(df, xlsx_path, f"{plan_name}_Py")

        rel_csv = csv_path.relative_to(Path.cwd()) if csv_path.is_relative_to(Path.cwd()) else csv_path
        rel_xlsx = xlsx_path.relative_to(Path.cwd()) if xlsx_path.is_relative_to(Path.cwd()) else xlsx_path
        print(f"    {rel_csv}")
        print(f"    {rel_xlsx} (sheet '{plan_name}_Py')")
    except Exception as e:  # noqa: BLE001 — diagnostic aid must not crash the run
        print(f"\n  WARNING: truth table could not be written: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Pipeline executor
# ---------------------------------------------------------------------------

def _execute_pipeline(constants):
    """Run liability + funding pipeline for any plan.

    Returns (liability_dict, funding_obj, liability_stacked).
    The funding object shape varies by plan (dict for FRS, DataFrame for TRS)
    but build_plan_summary() normalizes them into a common format.
    """
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.core.funding_model import (
        load_funding_inputs, compute_funding, compute_funding_trs,
    )

    print("  Building benefit tables, workforce, and liabilities (this may take a while)...")
    liability = run_plan_pipeline(constants, progress=True)

    liability_frames = []
    for cn in constants.classes:
        df = liability[cn].copy()
        df["plan_name"] = constants.plan_name
        df["class_name"] = cn
        liability_frames.append(df)
    liability_stacked = pd.concat(liability_frames, ignore_index=True)

    print("  Computing funding...")
    funding_dir = constants.resolve_data_dir() / "funding"
    funding_inputs = load_funding_inputs(funding_dir)

    funding_model = constants.funding_model
    if funding_model == "trs":
        funding = compute_funding_trs(
            liability[list(constants.classes)[0]], funding_inputs, constants)
    else:
        funding = compute_funding(liability, funding_inputs, constants)

    return liability, funding, liability_stacked


# ---------------------------------------------------------------------------
# Unified plan runner
# ---------------------------------------------------------------------------

def _run_plan(constants, args):
    """Run any plan's pipeline and emit standardized output."""
    plan_name = constants.plan_name
    scenario = constants.scenario_name

    header = f"{plan_name.upper()} Pension Model Pipeline"
    if scenario:
        header += f"  [scenario: {scenario}]"
    print("=" * 60)
    print(header)
    print("=" * 60)

    t0 = time.time()
    liability, funding, liability_stacked = _execute_pipeline(constants)
    elapsed = time.time() - t0
    print(f"  Pipeline complete: {elapsed:.0f}s")

    # Parameters
    print_parameters(constants)

    # Summary
    if scenario:
        output_dir = OUTPUT_BASE / plan_name / scenario
    else:
        output_dir = OUTPUT_BASE / plan_name
    summary = build_plan_summary(plan_name, liability, funding, constants)
    print_summary_table(summary)
    _write_outputs(summary, liability_stacked, output_dir)

    # Truth table (optional)
    if args.truth_table:
        _emit_truth_table(plan_name, liability, funding, constants, output_dir)


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def cmd_calibrate(args):
    """Run calibration: compute nc_cal and pvfb_term_current from AV targets."""
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.plan_config import discover_plans, load_plan_config
    from pension_model.core.calibration import (
        build_targets_from_config, run_calibration, format_diagnostics,
        format_comparison, write_calibration_json,
    )

    plan_name = args.plan_name

    plans = discover_plans()
    if plan_name not in plans:
        print(f"  Config not found for plan {plan_name!r}. Discovered: {sorted(plans)}")
        sys.exit(1)
    config_path = plans[plan_name]

    print("=" * 60)
    print(f"{plan_name.upper()} Calibration")
    print("=" * 60)

    t0 = time.time()

    # Load config without calibration -> neutral (nc_cal=1.0, pvfb_term_current=0)
    constants = load_plan_config(config_path, calibration_path=Path("__no_calibration__"))
    cal_factor = constants.benefit.cal_factor

    # Build calibration targets from config's acfr_data
    targets = build_targets_from_config(constants)
    if not targets:
        print(f"  No calibration targets found in acfr_data for {plan_name!r}.")
        print(f"  Each class needs val_norm_cost and val_aal in acfr_data.")
        sys.exit(1)

    # Run pipeline with neutral calibration
    print("  Running uncalibrated pipeline...")
    liability = run_plan_pipeline(constants, progress=True)

    # Compute calibration
    results = run_calibration(liability, targets, constants.ranges.start_year)

    elapsed = time.time() - t0
    print(f"  Calibration complete: {elapsed:.0f}s\n")

    # Print diagnostics
    print(format_diagnostics(results, targets, cal_factor))

    # Compare to existing calibration.json (e.g. R-derived values)
    existing_cal_path = config_path.parent / "calibration.json"
    comparison = format_comparison(results, existing_cal_path)
    if comparison:
        print()
        print(comparison)

    # Write calibration JSON if requested
    if args.write:
        output_path = Path(args.output) if args.output else existing_cal_path
        write_calibration_json(cal_factor, results, output_path)
        print(f"\n  Calibration written to {output_path}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_tests():
    """Run all baseline validation and unit tests via pytest."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pension_model/", "-v", "--tb=short"],
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_run(args):
    """Dispatch `pension-model run <plan>` to the unified runner."""
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

    config_path = plans[args.plan]
    cal_path = config_path.parent / "calibration.json"
    scenario_path = Path(args.scenario) if args.scenario else None
    constants = load_plan_config(
        config_path,
        calibration_path=cal_path if cal_path.exists() else None,
        scenario_path=scenario_path,
    )

    _run_plan(constants, args)

    if not args.no_test:
        print("\nRunning tests...")
        tests_ok = run_tests()
        sys.exit(0 if tests_ok else 1)


def cmd_list(args):
    """List discovered plans and whether each has a registered runner."""
    from pension_model.plan_config import discover_plans

    plans = discover_plans()
    if not plans:
        print("No plans found under plans/")
        return
    print("Discovered plans:")
    for name, path in sorted(plans.items()):
        rel = path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path
        print(f"  {name:20s} {rel}")


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
    run_p.add_argument("--truth-table", action="store_true",
                       help="Write R-vs-Python truth table to CSV and Excel")
    run_p.add_argument("--scenario", type=str, default=None,
                       help="Path to scenario JSON file (overrides baseline assumptions)")

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
