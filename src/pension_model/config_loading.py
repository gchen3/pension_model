"""Plan config loading and discovery helpers.

Keeps file I/O, scenario merging, and plan auto-discovery separate from the
core ``PlanConfig`` schema and rule-resolution logic in ``plan_config.py``.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

from pension_model.config_schema import PlanConfig


log = logging.getLogger(__name__)


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge overrides into base dict (returns a new dict)."""
    result = dict(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _build_class_to_group(raw: dict) -> Dict[str, str]:
    """Build class-to-group lookup from ``class_groups`` config."""
    class_to_group: Dict[str, str] = {}
    for group_name, members in raw.get("class_groups", {}).items():
        for class_name in members:
            class_to_group[class_name] = group_name
    return class_to_group


def _load_calibration_data(
    calibration_path: Optional[Path],
    *,
    skip_class_calibration: bool,
) -> tuple[dict, Optional[float]]:
    """Load calibration payload from JSON when available.

    Returns:
        Tuple of ``(per_class_calibration, global_cal_factor_override)``.
    """
    if calibration_path is None or not calibration_path.exists():
        return {}, None

    with open(calibration_path) as f:
        cal_raw = json.load(f)

    calibration = {} if skip_class_calibration else cal_raw.get("classes", {})
    return calibration, cal_raw.get("cal_factor")


def _build_tier_metadata(
    tier_defs_raw: list[dict],
    *,
    fas_default: int,
) -> tuple[dict[str, int], tuple[str, ...], tuple[str, ...], tuple[int, ...]]:
    """Build tier lookup tables cached on ``PlanConfig``."""
    tier_name_to_id = {td["name"]: i for i, td in enumerate(tier_defs_raw)}
    tier_id_to_name = tuple(td["name"] for td in tier_defs_raw)
    tier_id_to_cola_key = tuple(td["cola_key"] for td in tier_defs_raw)
    tier_id_to_fas_years = tuple(td.get("fas_years", fas_default) for td in tier_defs_raw)
    return (
        tier_name_to_id,
        tier_id_to_name,
        tier_id_to_cola_key,
        tier_id_to_fas_years,
    )


def load_plan_config(
    config_path: Path,
    calibration_path: Optional[Path] = None,
    scenario_path: Optional[Path] = None,
    skip_class_calibration: bool = False,
) -> PlanConfig:
    """Load a PlanConfig from a JSON file."""
    with open(config_path) as f:
        raw = json.load(f)

    baseline_dr_current = raw["economic"]["dr_current"]

    scenario_name = None
    if scenario_path is not None:
        with open(scenario_path) as f:
            scenario = json.load(f)
        scenario_name = scenario.get("name", scenario_path.stem)
        raw = _deep_merge(raw, scenario.get("overrides", {}))

    if scenario_name:
        raw["_scenario_name"] = scenario_name

    eco = raw["economic"]
    ben = raw["benefit"]
    fun = raw["funding"]
    rng = raw["ranges"]

    tier_defs_raw = raw.get("tiers", [])
    class_to_group = _build_class_to_group(raw)
    calibration, cal_factor_override = _load_calibration_data(
        calibration_path,
        skip_class_calibration=skip_class_calibration,
    )
    if cal_factor_override is not None:
        ben = dict(ben)
        ben["cal_factor"] = cal_factor_override

    (
        tier_name_to_id,
        tier_id_to_name,
        tier_id_to_cola_key,
        tier_id_to_fas_years,
    ) = _build_tier_metadata(
        tier_defs_raw,
        fas_default=ben.get("fas_years_default", 5),
    )

    config = PlanConfig(
        plan_name=raw["plan_name"],
        plan_description=raw.get("plan_description", ""),
        raw=raw,
        dr_current=eco["dr_current"],
        dr_new=eco["dr_new"],
        dr_old=eco.get("dr_old", eco["dr_current"]),
        baseline_dr_current=baseline_dr_current,
        payroll_growth=eco["payroll_growth"],
        pop_growth=eco.get("pop_growth", 0.0),
        inflation=eco["inflation"],
        model_return=eco.get("model_return", eco["dr_current"]),
        db_ee_cont_rate=ben["db_ee_cont_rate"],
        db_ee_interest_rate=ben.get("db_ee_interest_rate", 0.0),
        cal_factor=ben.get("cal_factor", 1.0),
        retire_refund_ratio=ben.get("retire_refund_ratio", 1.0),
        fas_years_default=ben.get("fas_years_default", 5),
        benefit_types=tuple(ben.get("benefit_types", ["db"])),
        cola=ben.get("cola", {}),
        cash_balance=ben.get("cash_balance"),
        funding_policy=fun["policy"],
        amo_method=fun["amo_method"],
        amo_period_new=fun["amo_period_new"],
        amo_pay_growth=fun.get("amo_pay_growth", eco["payroll_growth"]),
        funding_lag=fun.get("funding_lag", 1),
        amo_period_term=fun.get("amo_period_term", 50),
        amo_term_growth=fun.get("amo_term_growth", 0.03),
        ava_smoothing=fun.get("ava_smoothing", {}),
        min_age=rng["min_age"],
        max_age=rng["max_age"],
        start_year=rng["start_year"],
        new_year=rng.get("new_year", rng["start_year"]),
        min_entry_year=rng.get("min_entry_year", 1970),
        model_period=rng["model_period"],
        max_yos=rng.get("max_yos", 70),
        classes=tuple(raw["classes"]),
        class_groups=raw.get("class_groups", {}),
        tier_defs=tuple(raw.get("tiers", [])),
        benefit_mult_defs=raw.get("benefit_multipliers", {}),
        plan_design_defs=raw.get("plan_design", {}),
        valuation_inputs=raw.get("valuation_inputs", {}),
        calibration=calibration,
        _class_to_group=class_to_group,
        _tier_name_to_id=tier_name_to_id,
        _tier_id_to_name=tier_id_to_name,
        _tier_id_to_cola_key=tier_id_to_cola_key,
        _tier_id_to_fas_years=tier_id_to_fas_years,
    )

    for warning in config.validate():
        log.info("[%s config] %s", config.plan_name, warning)

    return config


def discover_plans(plans_dir: Optional[Path] = None) -> dict[str, Path]:
    """Return {plan_name: plan_config.json path} for discovered plans."""
    if plans_dir is None:
        plans_dir = Path(__file__).parents[2] / "plans"
    plans: dict[str, Path] = {}
    if not plans_dir.is_dir():
        return plans
    for entry in sorted(plans_dir.iterdir()):
        if not entry.is_dir():
            continue
        cfg = entry / "config" / "plan_config.json"
        if cfg.exists():
            plans[entry.name] = cfg
    return plans


def load_plan_config_by_name(
    plan_name: str,
    calibration_path: Optional[Path] = None,
) -> PlanConfig:
    """Load a plan config by plan directory name."""
    plans = discover_plans()
    if plan_name not in plans:
        raise ValueError(f"Unknown plan {plan_name!r}. Available: {sorted(plans)}")
    config_path = plans[plan_name]
    if calibration_path is None:
        cal_path = config_path.parent / "calibration.json"
        cal_path = cal_path if cal_path.exists() else None
    else:
        cal_path = calibration_path
    return load_plan_config(config_path, cal_path)


def load_frs_config(calibration_path: Optional[Path] = None) -> PlanConfig:
    """Convenience: load the FRS plan config (debug/tests only)."""
    return load_plan_config_by_name("frs", calibration_path)


def load_txtrs_config(calibration_path: Optional[Path] = None) -> PlanConfig:
    """Convenience: load the TRS plan config (debug/tests only)."""
    return load_plan_config_by_name("txtrs", calibration_path)
