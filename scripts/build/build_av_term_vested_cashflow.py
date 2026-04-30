#!/usr/bin/env python3
"""Build current_term_vested_cashflow.csv for AV-first plans.

Generic over any AV-first plan; takes the plan name on the command line.
Uses the shared deferred-annuity method documented in
`prep/common/methods/term_vested_deferred_annuity.md` and implemented
in `scripts/build/term_vested_deferred_annuity.py`.

Inputs read:
  plans/{plan}/config/plan_config.json   - economic.dr_current
                                           benefit.cola.current_retire
                                           term_vested.avg_deferral_years
                                           term_vested.avg_payout_years
  plans/{plan}/config/calibration.json   - per-class pvfb_term_current

Output written:
  plans/{plan}/data/funding/current_term_vested_cashflow.csv

Self-check: NPV of the produced stream at economic.dr_current equals
pvfb_term_current to floating-point precision.

Usage:
  python scripts/build/build_av_term_vested_cashflow.py txtrs-av
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from pension_model.core.pipeline_current import _npv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from term_vested_deferred_annuity import deferred_annuity_stream


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main(plan: str) -> None:
    plan_dir = PROJECT_ROOT / "plans" / plan
    config_path = plan_dir / "config" / "plan_config.json"
    calibration_path = plan_dir / "config" / "calibration.json"
    out_path = plan_dir / "data" / "funding" / "current_term_vested_cashflow.csv"

    config = json.loads(config_path.read_text())
    calibration = json.loads(calibration_path.read_text())

    baseline_rate = config["economic"]["dr_current"]
    cola = config["benefit"]["cola"]["current_retire"]
    tv = config["term_vested"]
    deferral_years = int(tv["avg_deferral_years"])
    payout_years = int(tv["avg_payout_years"])

    rows: list[dict] = []
    for class_name, class_cal in calibration["classes"].items():
        pvfb = class_cal["pvfb_term_current"]
        stream = deferred_annuity_stream(
            pvfb_term_current=pvfb,
            baseline_rate=baseline_rate,
            cola=cola,
            deferral_years=deferral_years,
            payout_years=payout_years,
        )

        npv = _npv(baseline_rate, stream)
        if pvfb != 0:
            rel_err = abs(npv - pvfb) / abs(pvfb)
            assert rel_err < 1e-12, (
                f"{plan} {class_name}: NPV {npv} != pvfb_term_current {pvfb} "
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, float_format="%.17g")
    print(
        f"Wrote {out_path} ({len(df)} rows, "
        f"{df['class_name'].nunique()} classes, "
        f"D={deferral_years}, L={payout_years}, cola={cola})"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="plan name, e.g. txtrs-av")
    args = parser.parse_args()
    main(args.plan)
