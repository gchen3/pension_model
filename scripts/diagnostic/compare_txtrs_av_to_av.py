#!/usr/bin/env python3
"""Compare txtrs-av year-0 model output to AV Table 2 published values.

Produces a side-by-side report of PVFB by status, PVFNC, AAL by status,
and total AAL, with relative gaps. Designed to be re-run as the model or
data changes; the AV-published values are pinned to the 2024 valuation.

The output is intended as a diagnostic for understanding where the model
diverges from the published AV before any calibration is applied. Once
calibration is in place, this script's gap percentages will shift toward
zero for the calibrated quantities.

Run after a full pension-model run for txtrs-av:
  pension-model run txtrs-av --no-test
  python scripts/diagnostic/compare_txtrs_av_to_av.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIAB_PATH = PROJECT_ROOT / "output" / "txtrs-av" / "liability_stacked.csv"

# AV Table 2 published values for valuation as of 8/31/2024 (Texas TRS).
# Source: prep/txtrs-av/sources/Texas TRS Valuation 2024.pdf, printed p. 17.
AV_TABLE_2_2024 = {
    "active_members":                 970_872,
    "average_pay_dollars":             59_210,
    "active_total_payroll":     57_484_875_501,   # AV Table 15a active member annualized salary
    "projected_payroll":        61_388_248_000,   # AV Table 2 line 10
    "pvfs":                    517_122_182_135,   # line 3
    "pvfb_retired_in_pay":     133_927_805_157,   # line 5a
    "pvfb_retired_survivors":    2_079_196_524,   # line 5b
    "pvfb_vested_inactive":      7_509_703_539,   # line 5c
    "pvfb_active":             187_884_499_767,   # line 5d
    "pvfb_inactive_nonvested":   1_218_489_735,   # line 5e
    "pvfb_total":              332_619_694_722,   # line 5f
    "pvfnc":                    59_524_634_671,   # line 6
    "aal_total":               273_095_060_051,   # line 7
    "nc_rate_gross":                    0.1210,   # line 4a
}


def _safe(series, key):
    return float(series.get(key, 0) or 0)


def _bucket_year_zero(liab_path: Path) -> dict:
    df = pd.read_csv(liab_path)
    y0 = df[df.year == df.year.min()].iloc[0]

    pvfb_active = _safe(y0, "pvfb_active_db_legacy_est") + _safe(y0, "pvfb_active_db_new_est")
    pvfnc = _safe(y0, "pvfnc_db_legacy_est") + _safe(y0, "pvfnc_db_new_est")
    aal_active = _safe(y0, "aal_active_db_legacy_est") + _safe(y0, "aal_active_db_new_est")
    aal_retire_current = _safe(y0, "aal_retire_current_est")
    aal_retire_proj = _safe(y0, "aal_retire_db_legacy_est") + _safe(y0, "aal_retire_db_new_est")
    aal_term_current = _safe(y0, "aal_term_current_est")
    aal_term_proj = _safe(y0, "aal_term_db_legacy_est") + _safe(y0, "aal_term_db_new_est")
    aal_total = _safe(y0, "total_aal_est")
    payroll = _safe(y0, "total_payroll_est")

    pvfb_retire_total = aal_retire_current + aal_retire_proj
    pvfb_term_total = aal_term_current + aal_term_proj
    pvfb_total = pvfb_active + pvfb_retire_total + pvfb_term_total

    return {
        "year": int(y0.year),
        "active_total_payroll": payroll,
        "pvfb_active": pvfb_active,
        "pvfb_retire_total": pvfb_retire_total,
        "pvfb_term_total": pvfb_term_total,
        "pvfb_total": pvfb_total,
        "pvfnc": pvfnc,
        "aal_active": aal_active,
        "aal_retire_current": aal_retire_current,
        "aal_term_total": pvfb_term_total,  # term AAL == term PVFB (no future accrual)
        "aal_total": aal_total,
    }


def build_comparison(model: dict, av: dict) -> pd.DataFrame:
    rows = [
        ("Active total payroll (cohort-derived)", model["active_total_payroll"], av["active_total_payroll"]),
        ("PVFB - active members",                  model["pvfb_active"],          av["pvfb_active"]),
        ("PVFB - retirees in pay or deferred",     model["pvfb_retire_total"],    av["pvfb_retired_in_pay"]),
        ("PVFB - retiree future survivor",         0,                              av["pvfb_retired_survivors"]),
        ("PVFB - vested inactive",                 model["pvfb_term_total"],      av["pvfb_vested_inactive"]),
        ("PVFB - inactive nonvested",              0,                              av["pvfb_inactive_nonvested"]),
        ("PVFB - total",                            model["pvfb_total"],           av["pvfb_total"]),
        ("PVFNC (employee + employer)",            model["pvfnc"],                 av["pvfnc"]),
        ("AAL - active (PVFB - PVFNC)",            model["aal_active"],            av["pvfb_active"] - av["pvfnc"]),
        ("AAL - current retirees",                 model["aal_retire_current"],    av["pvfb_retired_in_pay"]),
        ("AAL - other (term + survivor + nonvested)", model["aal_term_total"],
                                                   av["pvfb_vested_inactive"] + av["pvfb_retired_survivors"] + av["pvfb_inactive_nonvested"]),
        ("AAL - total",                             model["aal_total"],            av["aal_total"]),
    ]
    out = pd.DataFrame(rows, columns=["quantity", "model", "av"])
    out["gap_dollars"] = out["model"] - out["av"]
    out["gap_pct"] = ((out["model"] - out["av"]) / out["av"]).where(out["av"] != 0, float("nan")) * 100
    return out


def format_table(df: pd.DataFrame) -> str:
    def fmt_b(x):
        return f"${x/1e9:>10,.2f}B" if abs(x) > 1e6 else f"{x:>11,.0f}"

    def fmt_pct(x):
        return "      " if pd.isna(x) else f"{x:+6.2f}%"

    lines = ["=" * 90,
             f"{'Quantity':<44s} {'Model':>14s} {'AV':>14s} {'Gap':>14s}",
             "=" * 90]
    for _, r in df.iterrows():
        lines.append(f"{r.quantity:<44s} {fmt_b(r.model):>14s} {fmt_b(r.av):>14s} {fmt_pct(r.gap_pct):>14s}")
    lines.append("=" * 90)
    return "\n".join(lines)


def main() -> None:
    if not LIAB_PATH.exists():
        raise SystemExit(
            f"Missing {LIAB_PATH}. Run `pension-model run txtrs-av --no-test` first."
        )
    model = _bucket_year_zero(LIAB_PATH)
    print(f"txtrs-av year-{model['year']} liability vs AV Table 2 (2024)")
    print()
    df = build_comparison(model, AV_TABLE_2_2024)
    print(format_table(df))

    out_csv = PROJECT_ROOT / "prep" / "txtrs-av" / "reports" / "av_comparison_year0.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")


if __name__ == "__main__":
    main()
