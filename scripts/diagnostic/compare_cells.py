#!/usr/bin/env python3
"""Pairwise comparison between two (plan, scenario) cells in all_runs.csv.

Reads ``output/all_runs.csv`` (produced by ``run_cell.py``), filters to
the two requested cells, joins on ``(year, metric)``, and emits a
long-format diff CSV. Also prints a per-metric summary to stdout so the
user gets something useful without opening the file.

Usage:
    python scripts/diagnostic/compare_cells.py --a txtrs/baseline --b txtrs-av/baseline
    python scripts/diagnostic/compare_cells.py --a txtrs-av/baseline --b txtrs-av/high_discount

The cell identifier syntax is ``plan/scenario``. ``baseline`` is the
canonical scenario name for "no scenario overrides applied".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ALL_RUNS_PATH = PROJECT_ROOT / "output" / "all_runs.csv"
COMPARE_DIR = PROJECT_ROOT / "output"


def _parse_cell(cell: str) -> tuple[str, str]:
    if "/" not in cell:
        raise ValueError(
            f"Cell identifier must be 'plan/scenario'; got {cell!r}"
        )
    plan, scenario = cell.split("/", 1)
    if not plan or not scenario:
        raise ValueError(
            f"Cell identifier must be 'plan/scenario' with both parts non-empty; got {cell!r}"
        )
    return plan, scenario


def _filter_cell(df: pd.DataFrame, plan: str, scenario: str) -> pd.DataFrame:
    cell = df[(df["plan"] == plan) & (df["scenario"] == scenario)]
    if cell.empty:
        available = sorted({(p, s) for p, s in zip(df["plan"], df["scenario"])})
        raise SystemExit(
            f"No rows for plan={plan} scenario={scenario} in {ALL_RUNS_PATH}. "
            f"Run `make run plan={plan} scenario={scenario}` first.\n"
            f"Available cells: {available}"
        )
    return cell[["year", "metric", "value"]].copy()


def build_comparison(
    all_runs: pd.DataFrame,
    a_plan: str,
    a_scenario: str,
    b_plan: str,
    b_scenario: str,
) -> pd.DataFrame:
    a = _filter_cell(all_runs, a_plan, a_scenario).rename(columns={"value": "value_a"})
    b = _filter_cell(all_runs, b_plan, b_scenario).rename(columns={"value": "value_b"})
    merged = a.merge(b, on=["year", "metric"], how="outer")
    merged["abs_diff"] = merged["value_b"] - merged["value_a"]
    denom = merged["value_a"].where(np.abs(merged["value_a"]) > 1e-12, np.nan)
    merged["pct_diff"] = merged["abs_diff"] / np.abs(denom) * 100.0
    merged.insert(0, "plan_a", a_plan)
    merged.insert(1, "scenario_a", a_scenario)
    merged.insert(2, "plan_b", b_plan)
    merged.insert(3, "scenario_b", b_scenario)
    return merged.sort_values(["metric", "year"]).reset_index(drop=True)


def print_summary(comparison: pd.DataFrame, a_label: str, b_label: str) -> None:
    print(f"\n{a_label}  vs  {b_label}")
    print(f"  rows: {len(comparison)}")
    print()
    summary_rows = []
    for metric, grp in comparison.groupby("metric", sort=False):
        max_abs = grp["abs_diff"].abs().max()
        max_pct = grp["pct_diff"].abs().max()
        y0 = grp[grp["year"] == grp["year"].min()].iloc[0] if len(grp) else None
        ylast = grp[grp["year"] == grp["year"].max()].iloc[0] if len(grp) else None
        summary_rows.append({
            "metric": metric,
            "y0_a": float(y0["value_a"]) if y0 is not None else np.nan,
            "y0_b": float(y0["value_b"]) if y0 is not None else np.nan,
            "y0_pct": float(y0["pct_diff"]) if y0 is not None else np.nan,
            "ylast_pct": float(ylast["pct_diff"]) if ylast is not None else np.nan,
            "max_abs_pct": float(max_pct) if pd.notna(max_pct) else np.nan,
        })
    summary = pd.DataFrame(summary_rows)
    with pd.option_context(
        "display.max_rows", None,
        "display.max_columns", None,
        "display.width", 140,
        "display.float_format", lambda v: f"{v:,.4g}" if abs(v) >= 1 else f"{v:.4g}",
    ):
        print(summary.to_string(index=False))
    print()


def output_path(a_plan: str, a_scenario: str, b_plan: str, b_scenario: str) -> Path:
    name = f"compare_{a_plan}_{a_scenario}__vs__{b_plan}_{b_scenario}.csv"
    return COMPARE_DIR / name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", required=True, help="cell A as plan/scenario (e.g. txtrs/baseline)")
    parser.add_argument("--b", required=True, help="cell B as plan/scenario")
    parser.add_argument(
        "--input",
        type=Path,
        default=ALL_RUNS_PATH,
        help=f"long-format CSV to read (default: {ALL_RUNS_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output CSV path (default: output/compare_<a>__vs__<b>.csv)",
    )
    args = parser.parse_args()

    a_plan, a_scenario = _parse_cell(args.a)
    b_plan, b_scenario = _parse_cell(args.b)

    if not args.input.exists():
        raise SystemExit(
            f"{args.input} not found. Run `make run-all` (or `make run plan=<p> scenario=<s>`) first."
        )

    all_runs = pd.read_csv(args.input)
    comparison = build_comparison(all_runs, a_plan, a_scenario, b_plan, b_scenario)

    out_path = args.output or output_path(a_plan, a_scenario, b_plan, b_scenario)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(out_path, index=False, float_format="%.17g")

    print_summary(comparison, args.a, args.b)
    print(f"Full long-format diff: {out_path}")


if __name__ == "__main__":
    main()
