"""
Calibration module.

Computes calibration factors (nc_cal, pvfb_term_current) by comparing
uncalibrated model output against actuarial valuation (AV) targets.

The calibration process:
1. Run the pipeline with neutral calibration (nc_cal=1.0, pvfb_term_current=0)
2. Extract model NC rate and AAL from pipeline output
3. Compute nc_cal = val_norm_cost / model_norm_cost
4. Compute pvfb_term_current = val_aal - model_aal
5. Produce diagnostics comparing model vs AV across all available quantities
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


@dataclass
class CalibrationTargets:
    """Per-class targets from actuarial valuation report."""
    val_norm_cost: float       # NC rate from AV
    val_aal: float             # Total AAL from AV
    # Diagnostic-only targets (not calibrated against, but reported)
    val_payroll: Optional[float] = None
    val_benefit_payments: Optional[float] = None


@dataclass
class CalibrationResult:
    """Computed calibration for a single class."""
    nc_cal: float
    pvfb_term_current: float
    # Diagnostics: what the model produced before calibration
    model_norm_cost: float
    model_aal: float
    model_payroll: float
    model_benefit_payments: float


def calibrate_class(
    class_name: str,
    liability_output: pd.DataFrame,
    targets: CalibrationTargets,
    start_year: int,
) -> CalibrationResult:
    """Compute calibration factors for one class.

    liability_output must come from a pipeline run with nc_cal=1.0 and
    pvfb_term_current=0 (neutral calibration).
    """
    row0 = liability_output[liability_output["year"] == start_year].iloc[0]

    model_nc = row0["nc_rate_db_legacy_est"]
    # With pvfb_term_current=0, aal_term_current_est is 0,
    # so total_aal_est is the raw model AAL
    model_aal = row0["total_aal_est"]
    model_payroll = row0["total_payroll_est"]
    model_ben = row0["tot_ben_refund_legacy_est"]

    nc_cal = targets.val_norm_cost / model_nc if model_nc != 0 else 1.0
    pvfb_term_current = targets.val_aal - model_aal

    return CalibrationResult(
        nc_cal=nc_cal,
        pvfb_term_current=pvfb_term_current,
        model_norm_cost=model_nc,
        model_aal=model_aal,
        model_payroll=model_payroll,
        model_benefit_payments=model_ben,
    )


def run_calibration(
    liability_results: Dict[str, pd.DataFrame],
    targets: Dict[str, CalibrationTargets],
    start_year: int,
) -> Dict[str, CalibrationResult]:
    """Compute calibration factors for all classes.

    liability_results: output from pipeline runs with neutral calibration.
    targets: per-class AV targets.
    """
    results = {}
    for cn, liab in liability_results.items():
        if cn in targets:
            results[cn] = calibrate_class(cn, liab, targets[cn], start_year)
    return results


def load_targets_from_init_funding(
    init_funding: pd.DataFrame,
    val_norm_costs: Dict[str, float],
) -> Dict[str, CalibrationTargets]:
    """Build calibration targets from init_funding_data.csv and known NC rates.

    init_funding: DataFrame with columns 'class', 'total_aal', 'total_payroll', etc.
    val_norm_costs: dict mapping class_name -> AV normal cost rate.

    .. deprecated:: Use ``build_targets_from_config`` instead.
    """
    targets = {}
    for _, row in init_funding.iterrows():
        cn = row["class"].replace(" ", "_")
        if cn not in val_norm_costs:
            continue
        targets[cn] = CalibrationTargets(
            val_norm_cost=val_norm_costs[cn],
            val_aal=row["total_aal"],
            val_payroll=row.get("total_payroll"),
            val_benefit_payments=row.get("total_ben_payment") if "total_ben_payment" in row.index else None,
        )
    return targets


def build_targets_from_config(constants) -> Dict[str, CalibrationTargets]:
    """Build calibration targets from plan config's acfr_data.

    Requires each class entry in acfr_data to have at least ``val_norm_cost``
    and ``val_aal``.  Works for any plan.
    """
    targets = {}
    acfr = constants.acfr_data
    for cn in constants.classes:
        entry = acfr.get(cn, {})
        vnc = entry.get("val_norm_cost")
        val_aal = entry.get("val_aal")
        if vnc is None or val_aal is None:
            continue
        targets[cn] = CalibrationTargets(
            val_norm_cost=vnc,
            val_aal=val_aal,
            val_payroll=entry.get("val_payroll"),
            val_benefit_payments=entry.get("outflow"),
        )
    return targets


def format_diagnostics(
    results: Dict[str, CalibrationResult],
    targets: Dict[str, CalibrationTargets],
    cal_factor: float,
) -> str:
    """Format calibration diagnostics as a human-readable string."""
    lines = []
    lines.append("Calibration Diagnostics")
    lines.append("=" * 70)
    lines.append(f"  Global cal_factor: {cal_factor}")
    lines.append("")

    # NC rate calibration
    lines.append("  Normal cost calibration (nc_cal = AV NC / model NC):")
    lines.append(f"  {'Class':20s} {'Model NC':>10s} {'AV NC':>10s} {'nc_cal':>10s} {'Flag':>6s}")
    lines.append(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*6}")
    for cn in sorted(results.keys()):
        r = results[cn]
        t = targets[cn]
        flag = "!" if r.nc_cal < 0.8 or r.nc_cal > 1.2 else ""
        lines.append(
            f"  {cn:20s} {r.model_norm_cost:10.5f} {t.val_norm_cost:10.5f} "
            f"{r.nc_cal:10.5f} {flag:>6s}"
        )

    lines.append("")

    # AAL calibration
    lines.append("  AAL calibration (pvfb_term_current = AV AAL - model AAL):")
    lines.append(f"  {'Class':20s} {'Model AAL($B)':>14s} {'AV AAL($B)':>14s} {'pvfb_term($B)':>14s} {'Gap%':>8s}")
    lines.append(f"  {'-'*20} {'-'*14} {'-'*14} {'-'*14} {'-'*8}")
    for cn in sorted(results.keys()):
        r = results[cn]
        t = targets[cn]
        gap_pct = (r.pvfb_term_current / t.val_aal * 100) if t.val_aal != 0 else 0
        lines.append(
            f"  {cn:20s} {r.model_aal/1e9:14.2f} {t.val_aal/1e9:14.2f} "
            f"{r.pvfb_term_current/1e9:14.2f} {gap_pct:7.1f}%"
        )

    lines.append("")

    # Out-of-sample: payroll
    has_payroll = any(t.val_payroll is not None for t in targets.values())
    if has_payroll:
        lines.append("  Out-of-sample checks (not calibrated):")
        lines.append(f"  {'Class':20s} {'Model Pay($B)':>14s} {'AV Pay($B)':>14s} {'Ratio':>8s}")
        lines.append(f"  {'-'*20} {'-'*14} {'-'*14} {'-'*8}")
        for cn in sorted(results.keys()):
            r = results[cn]
            t = targets[cn]
            if t.val_payroll is not None and t.val_payroll != 0:
                ratio = r.model_payroll / t.val_payroll
                lines.append(
                    f"  {cn:20s} {r.model_payroll/1e9:14.2f} {t.val_payroll/1e9:14.2f} "
                    f"{ratio:8.4f}"
                )

    return "\n".join(lines)


def format_comparison(
    results: Dict[str, CalibrationResult],
    existing_path: Path,
) -> Optional[str]:
    """Compare computed calibration to an existing calibration.json.

    Returns formatted comparison string, or None if no existing file.
    """
    if not existing_path.exists():
        return None

    import json
    with open(existing_path) as f:
        existing = json.load(f)

    existing_classes = existing.get("classes", {})
    if not existing_classes:
        return None

    lines = []
    lines.append("  Comparison with existing calibration.json:")
    lines.append(f"  {'Class':20s} {'nc_cal(new)':>12s} {'nc_cal(old)':>12s} {'diff':>10s}  "
                 f"{'pvfb(new,$B)':>12s} {'pvfb(old,$B)':>12s} {'diff($M)':>10s}")
    lines.append(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*10}  {'-'*12} {'-'*12} {'-'*10}")

    for cn in sorted(results.keys()):
        r = results[cn]
        old = existing_classes.get(cn, {})
        old_nc = old.get("nc_cal", 1.0)
        old_pvfb = old.get("pvfb_term_current", 0.0)
        nc_diff = r.nc_cal - old_nc
        pvfb_diff = r.pvfb_term_current - old_pvfb
        lines.append(
            f"  {cn:20s} {r.nc_cal:12.7f} {old_nc:12.7f} {nc_diff:10.2e}  "
            f"{r.pvfb_term_current/1e9:12.4f} {old_pvfb/1e9:12.4f} {pvfb_diff/1e6:10.2f}"
        )

    return "\n".join(lines)


def write_calibration_json(
    cal_factor: float,
    results: Dict[str, CalibrationResult],
    output_path: Path,
) -> None:
    """Write computed calibration factors to JSON file."""
    data = {
        "description": "Calibration factors computed by pension-model calibrate",
        "cal_factor": cal_factor,
        "classes": {},
    }
    for cn in sorted(results.keys()):
        r = results[cn]
        data["classes"][cn] = {
            "nc_cal": r.nc_cal,
            "pvfb_term_current": r.pvfb_term_current,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
