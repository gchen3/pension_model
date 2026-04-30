#!/usr/bin/env python3
"""Run one (plan, scenario) and upsert long-format rows into output/all_runs.csv.

The all-runs CSV is the canonical comparison surface across plans and
scenarios. Schema:

    plan, scenario, year, metric, value

Re-running the same (plan, scenario) replaces any prior rows for that
cell so the file stays current.

Usage:
    python scripts/diagnostic/run_cell.py --plan txtrs --scenario baseline
    python scripts/diagnostic/run_cell.py --plan txtrs-av --scenario high_discount

``--scenario baseline`` (the default) means no scenario overrides; any
other name is looked up as ``scenarios/<name>.json``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pension_model.runners import run_truth_table

ALL_RUNS_PATH = PROJECT_ROOT / "output" / "all_runs.csv"

NON_METRIC_COLS = {"plan", "year"}


def truth_table_to_long(plan: str, scenario: str, df: pd.DataFrame) -> pd.DataFrame:
    """Reshape a truth-table DataFrame into the canonical long format."""
    metric_cols = [
        c for c in df.columns
        if c not in NON_METRIC_COLS and pd.api.types.is_numeric_dtype(df[c])
    ]
    long = df.melt(
        id_vars=["year"],
        value_vars=metric_cols,
        var_name="metric",
        value_name="value",
    )
    long.insert(0, "scenario", scenario)
    long.insert(0, "plan", plan)
    return long[["plan", "scenario", "year", "metric", "value"]]


def upsert_rows(new_rows: pd.DataFrame, path: Path) -> None:
    """Replace any rows for the same (plan, scenario) and append the new ones."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_csv(path)
        plan = new_rows["plan"].iloc[0]
        scenario = new_rows["scenario"].iloc[0]
        keep = existing[
            ~((existing["plan"] == plan) & (existing["scenario"] == scenario))
        ]
        combined = pd.concat([keep, new_rows], ignore_index=True)
    else:
        combined = new_rows
    combined.to_csv(path, index=False, float_format="%.17g")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="plan name (e.g. txtrs)")
    parser.add_argument(
        "--scenario",
        default="baseline",
        help="scenario name (default: baseline). Any value other than 'baseline' "
        "must correspond to a scenarios/<name>.json file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ALL_RUNS_PATH,
        help=f"long-format CSV to upsert into (default: {ALL_RUNS_PATH})",
    )
    args = parser.parse_args()

    tt = run_truth_table(args.plan, args.scenario)
    long = truth_table_to_long(args.plan, args.scenario, tt)
    upsert_rows(long, args.output)
    print(
        f"Wrote {len(long)} rows for plan={args.plan} scenario={args.scenario} "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
