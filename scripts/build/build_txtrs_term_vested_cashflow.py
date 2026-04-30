#!/usr/bin/env python3
"""Build TXTRS runtime funding/current_term_vested_cashflow.csv.

This is a legacy-reconstruction artifact: the cashflow stream produced
here matches the TXTRS R model's bell-curve construction exactly, so
the Python runtime's truth tables for TXTRS do not move when the runtime
switches from constructing the stream in the year loop to reading it as
input data.

Method: bell curve (normal-distribution-weighted payments over
amo_period_term, peaking at midpoint).
Provenance: TXTRS R model — the `dnorm()`-weighted block in
`src/pension_model/core/pipeline_current.py`. This is a one-off ported
into the TXTRS prep area; new plans use the shared deferred-annuity
method in `prep/common/methods/term_vested_deferred_annuity.md`.

Inputs read:
  plans/txtrs/config/plan_config.json   - economic.dr_current,
                                          funding.amo_period_term
  plans/txtrs/config/calibration.json   - per-class pvfb_term_current

Output written:
  plans/txtrs/data/funding/current_term_vested_cashflow.csv

Self-check: NPV of the produced stream at economic.dr_current equals
pvfb_term_current to floating-point precision (this is the construction
identity).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from pension_model.core.pipeline_current import _npv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_DIR = PROJECT_ROOT / "plans" / "txtrs"
CONFIG_PATH = PLAN_DIR / "config" / "plan_config.json"
CALIBRATION_PATH = PLAN_DIR / "config" / "calibration.json"
OUT_PATH = PLAN_DIR / "data" / "funding" / "current_term_vested_cashflow.csv"


def build_class_stream(
    pvfb_term_current: float,
    cashflow_rate: float,
    amo_period: int,
) -> list[float]:
    """Build the TXTRS bell-curve stream for one class.

    Weights are `dnorm(seq, mean=amo_period/2, sd=amo_period/5)` over
    year offsets 1..amo_period. Weights are normalized so the year-1
    payment equals `pvfb_term_current / NPV(weights)`; the rest of the
    stream is `first_payment * weight_t / weight_1`.
    """
    if pvfb_term_current == 0:
        return [0.0] * amo_period
    mid = amo_period / 2
    spread = amo_period / 5
    seq = np.arange(1, amo_period + 1)
    weights = (1 / (spread * np.sqrt(2 * np.pi))) * np.exp(
        -0.5 * ((seq - mid) / spread) ** 2
    )
    ann_ratio = weights / weights[0]
    first_payment = pvfb_term_current / _npv(cashflow_rate, ann_ratio)
    return list(first_payment * ann_ratio)


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())
    calibration = json.loads(CALIBRATION_PATH.read_text())

    cashflow_rate = config["economic"]["dr_current"]
    amo_period = config["funding"].get("amo_period_term", 50)

    rows: list[dict] = []
    for class_name, class_cal in calibration["classes"].items():
        pvfb = class_cal["pvfb_term_current"]
        stream = build_class_stream(pvfb, cashflow_rate, amo_period)

        npv = _npv(cashflow_rate, stream)
        if pvfb != 0:
            rel_err = abs(npv - pvfb) / abs(pvfb)
            assert rel_err < 1e-12, (
                f"TXTRS {class_name}: NPV {npv} != pvfb_term_current {pvfb} "
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
