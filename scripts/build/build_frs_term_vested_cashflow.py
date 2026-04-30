#!/usr/bin/env python3
"""Build FRS runtime funding/current_term_vested_cashflow.csv.

This is a legacy-reconstruction artifact: the cashflow stream produced
here matches the FRS R model's growing-annuity construction exactly, so
the Python runtime's truth tables for FRS do not move when the runtime
switches from constructing the stream in the year loop to reading it as
input data.

Method: growing annuity (level percent of payroll).
Provenance: FRS R model — `_get_pmt` + `_recur_grow3` in
`src/pension_model/core/pipeline_current.py`. This is a one-off
ported into the FRS prep area; new plans use the shared deferred-annuity
method in `prep/common/methods/term_vested_deferred_annuity.md`.

Inputs read:
  plans/frs/config/plan_config.json   - economic.dr_current,
                                        economic.payroll_growth,
                                        funding.amo_period_term
  plans/frs/config/calibration.json   - per-class pvfb_term_current

Output written:
  plans/frs/data/funding/current_term_vested_cashflow.csv

Self-check: NPV of the produced stream at economic.dr_current equals
pvfb_term_current to floating-point precision (this is the construction
identity).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pension_model.core.pipeline_current import _get_pmt, _npv, _recur_grow3


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_DIR = PROJECT_ROOT / "plans" / "frs"
CONFIG_PATH = PLAN_DIR / "config" / "plan_config.json"
CALIBRATION_PATH = PLAN_DIR / "config" / "calibration.json"
OUT_PATH = PLAN_DIR / "data" / "funding" / "current_term_vested_cashflow.csv"


def build_class_stream(
    pvfb_term_current: float,
    cashflow_rate: float,
    payroll_growth: float,
    amo_period: int,
) -> list[float]:
    """Build the FRS growing-annuity stream for one class.

    Returns payments at year_offset 1..amo_period. The payment at
    year_offset 1 is the level-percent-of-payroll first payment that
    amortizes pvfb_term_current over amo_period at cashflow_rate; later
    payments grow at payroll_growth.
    """
    if pvfb_term_current == 0:
        return [0.0] * amo_period
    first_payment = _get_pmt(
        cashflow_rate, payroll_growth, amo_period, pvfb_term_current, t=1
    )
    return list(_recur_grow3(first_payment, payroll_growth, amo_period))


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())
    calibration = json.loads(CALIBRATION_PATH.read_text())

    cashflow_rate = config["economic"]["dr_current"]
    payroll_growth = config["economic"]["payroll_growth"]
    amo_period = config["funding"]["amo_period_term"]

    rows: list[dict] = []
    for class_name, class_cal in calibration["classes"].items():
        pvfb = class_cal["pvfb_term_current"]
        stream = build_class_stream(pvfb, cashflow_rate, payroll_growth, amo_period)

        npv = _npv(cashflow_rate, stream)
        if pvfb != 0:
            rel_err = abs(npv - pvfb) / abs(pvfb)
            assert rel_err < 1e-12, (
                f"FRS {class_name}: NPV {npv} != pvfb_term_current {pvfb} "
                f"(rel err {rel_err:.2e})"
            )

        for year_offset, payment in enumerate(stream, start=1):
            rows.append(
                {
                    "class_name": class_name,
                    "year_offset": year_offset,
                    "payment": payment,
                }
            )

    df = pd.DataFrame(rows, columns=["class_name", "year_offset", "payment"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, float_format="%.17g")
    print(f"Wrote {OUT_PATH} ({len(df)} rows, {df['class_name'].nunique()} classes)")


if __name__ == "__main__":
    main()
