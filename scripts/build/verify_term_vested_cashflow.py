#!/usr/bin/env python3
"""Verify per-plan current_term_vested_cashflow.csv files.

For FRS and TXTRS, the CSV must reproduce the stream the current
runtime constructs in `compute_current_term_vested_liability`
bit-identically. That is the precondition for the runtime PR (which
will replace the in-pipeline construction with a CSV read) leaving
truth tables unchanged.

For TXTRS-AV, there is no R legacy to match; the verification is the
NPV identity (NPV at baseline rate equals pvfb_term_current).

Exits non-zero on failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from pension_model.core.pipeline_current import (
    _get_pmt,
    _npv,
    _recur_grow3,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def runtime_growing_annuity_stream(
    pvfb: float, rate: float, growth: float, amo_period: int
) -> np.ndarray:
    """Mirror the runtime growing_annuity branch."""
    if pvfb == 0:
        return np.zeros(amo_period)
    first = _get_pmt(rate, growth, amo_period, pvfb, t=1)
    return _recur_grow3(first, growth, amo_period)


def runtime_bell_curve_stream(
    pvfb: float, rate: float, amo_period: int
) -> np.ndarray:
    """Mirror the runtime bell_curve branch."""
    if pvfb == 0:
        return np.zeros(amo_period)
    mid = amo_period / 2
    spread = amo_period / 5
    seq = np.arange(1, amo_period + 1)
    weights = (1 / (spread * np.sqrt(2 * np.pi))) * np.exp(
        -0.5 * ((seq - mid) / spread) ** 2
    )
    ratio = weights / weights[0]
    first = pvfb / _npv(rate, ratio)
    return first * ratio


def load_csv(plan: str) -> pd.DataFrame:
    path = PROJECT_ROOT / "plans" / plan / "data" / "funding" / "current_term_vested_cashflow.csv"
    return pd.read_csv(path, float_precision="round_trip")


def load_config(plan: str) -> tuple[dict, dict]:
    plan_dir = PROJECT_ROOT / "plans" / plan / "config"
    config = json.loads((plan_dir / "plan_config.json").read_text())
    calibration = json.loads((plan_dir / "calibration.json").read_text())
    return config, calibration


def verify_legacy(plan: str, runtime_fn, **kwargs) -> bool:
    """Compare CSV against runtime construction for a legacy plan."""
    config, calibration = load_config(plan)
    rate = config["economic"]["dr_current"]
    amo_period = config["funding"].get("amo_period_term", 50)
    df = load_csv(plan)

    ok = True
    for class_name, class_cal in calibration["classes"].items():
        pvfb = class_cal["pvfb_term_current"]
        runtime_stream = runtime_fn(pvfb, rate, amo_period=amo_period, **kwargs)
        csv_stream = (
            df[df["class_name"] == class_name]
            .sort_values("year_offset")["payment"]
            .to_numpy()
        )
        if not np.array_equal(runtime_stream, csv_stream):
            max_abs = float(np.max(np.abs(runtime_stream - csv_stream)))
            print(
                f"  FAIL {plan} {class_name}: max abs diff {max_abs:.6e}",
                file=sys.stderr,
            )
            ok = False
        else:
            print(f"  OK   {plan} {class_name}: {len(csv_stream)} payments match exactly")
    return ok


def verify_npv_identity(plan: str) -> bool:
    """Confirm NPV(stream, baseline_rate) == pvfb_term_current."""
    config, calibration = load_config(plan)
    rate = config["economic"]["dr_current"]
    df = load_csv(plan)
    ok = True
    for class_name, class_cal in calibration["classes"].items():
        pvfb = class_cal["pvfb_term_current"]
        stream = (
            df[df["class_name"] == class_name]
            .sort_values("year_offset")["payment"]
            .to_numpy()
        )
        npv = _npv(rate, stream)
        if pvfb == 0:
            if npv != 0:
                print(f"  FAIL {plan} {class_name}: pvfb=0 but NPV={npv}", file=sys.stderr)
                ok = False
            continue
        rel_err = abs(npv - pvfb) / abs(pvfb)
        if rel_err >= 1e-12:
            print(
                f"  FAIL {plan} {class_name}: NPV {npv:.6e} vs pvfb {pvfb:.6e} "
                f"(rel err {rel_err:.2e})",
                file=sys.stderr,
            )
            ok = False
        else:
            print(f"  OK   {plan} {class_name}: NPV identity holds (rel err {rel_err:.2e})")
    return ok


def main() -> int:
    overall_ok = True

    print("FRS (growing annuity, must match R legacy bit-identical):")
    overall_ok &= verify_legacy(
        "frs",
        lambda pvfb, rate, amo_period: runtime_growing_annuity_stream(
            pvfb, rate, _frs_growth(), amo_period
        ),
    )
    print()
    print("TXTRS (bell curve, must match R legacy bit-identical):")
    overall_ok &= verify_legacy(
        "txtrs",
        lambda pvfb, rate, amo_period: runtime_bell_curve_stream(pvfb, rate, amo_period),
    )
    print()
    print("TXTRS-AV (deferred annuity, NPV identity only):")
    overall_ok &= verify_npv_identity("txtrs-av")

    return 0 if overall_ok else 1


def _frs_growth() -> float:
    config, _ = load_config("frs")
    return config["economic"]["payroll_growth"]


if __name__ == "__main__":
    sys.exit(main())
