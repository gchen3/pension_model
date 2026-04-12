"""
Plan configuration loader: data-driven replacement for model_constants + tier_logic.

Loads plan_config.json and provides:
  - PlanConfig dataclass with all plan parameters
  - Table-driven tier determination (replaces tier_logic.get_tier)
  - Table-driven benefit multiplier lookup (replaces tier_logic.get_ben_mult)
  - Table-driven early retirement reduction (replaces tier_logic.get_reduce_factor)
  - Separation type derivation (replaces tier_logic.get_sep_type)
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retirement status constants — universal across all plans.
# Ordered so status >= EARLY means retirement-eligible.
# ---------------------------------------------------------------------------
NON_VESTED = 0
VESTED = 1
EARLY = 2      # includes "reduced" (never produced, only defensively checked)
NORM = 3


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanConfig:
    """All plan parameters loaded from JSON config.

    This is the single source of truth for a plan run.
    Replaces ModelConstants + tier_logic.py hardcoded rules.
    """
    plan_name: str
    plan_description: str
    raw: dict  # full parsed JSON for anything not yet lifted out

    # Economic
    dr_current: float
    dr_new: float
    dr_old: float
    payroll_growth: float
    pop_growth: float
    inflation: float
    model_return: float

    # Benefit
    db_ee_cont_rate: float
    db_ee_interest_rate: float
    cal_factor: float
    retire_refund_ratio: float
    fas_years_default: int
    benefit_types: Tuple[str, ...]
    cola: dict

    # Funding
    funding_policy: str
    amo_method: str
    amo_period_new: int
    amo_pay_growth: float
    funding_lag: int
    amo_period_term: int
    amo_term_growth: float
    ava_smoothing: dict

    # Ranges
    min_age: int
    max_age: int
    start_year: int
    new_year: int
    min_entry_year: int
    model_period: int
    max_yos: int

    # Classes
    classes: Tuple[str, ...]
    class_groups: Dict[str, List[str]]

    # Tiers (raw list of tier dicts from config — interpreted by evaluator)
    tier_defs: Tuple[dict, ...]

    # Benefit multipliers (raw from config)
    benefit_mult_defs: dict

    # Plan design ratios (raw from config)
    plan_design_defs: dict

    # Per-class ACFR data
    valuation_inputs: Dict[str, dict]

    # Calibration (per-class nc_cal and pvfb_term_current)
    calibration: Dict[str, dict] = field(default_factory=dict)

    # Cash balance parameters (optional, plans with CB benefit type)
    cash_balance: Optional[dict] = None

    # Precomputed: class→group mapping for fast lookup
    _class_to_group: Dict[str, str] = field(default_factory=dict)

    # Precomputed tier lookup tables (built from tier_defs at init)
    _tier_name_to_id: Dict[str, int] = field(default_factory=dict)
    _tier_id_to_name: Tuple[str, ...] = ()
    _tier_id_to_cola_key: Tuple[str, ...] = ()
    _tier_id_to_fas_years: Tuple[int, ...] = ()

    # --- Derived properties ---

    @property
    def scenario_name(self) -> Optional[str]:
        """Name of the active scenario, or None for baseline."""
        return self.raw.get("_scenario_name")

    # --- Modeling behavioral flags ---

    def resolve_data_dir(self) -> Path:
        """Resolve the stage 3 data directory for this plan.

        Reads data.data_dir from config JSON, resolves relative to project root.
        Falls back to plans/{plan_name}/data/ if not specified.
        """
        data_cfg = self.raw.get("data", {})
        data_dir_str = data_cfg.get("data_dir", f"plans/{self.plan_name}/data")
        data_dir = Path(data_dir_str)
        if not data_dir.is_absolute():
            project_root = Path(__file__).parents[2]
            data_dir = project_root / data_dir
        return data_dir

    @property
    def entrant_salary_at_start_year(self) -> bool:
        """Whether entrant profile salaries are expressed at start_year level.

        When True, max_hist_year is raised to start_year so future cohorts
        use the entrant profile salary directly. When False,
        max_hist_year comes from the salary_headcount data.
        """
        return self.raw.get("modeling", {}).get("entrant_salary_at_start_year", False)

    @property
    def use_earliest_retire(self) -> bool:
        """Whether to use earliest eligible age (incl. early) vs earliest normal."""
        return self.raw.get("modeling", {}).get("use_earliest_retire", False)

    @property
    def term_vested_method(self) -> str:
        """Method for projecting term vested benefit payments.
        'growing_annuity' or 'bell_curve'."""
        return self.raw.get("modeling", {}).get("term_vested_method", "growing_annuity")

    @property
    def male_mp_forward_shift(self) -> int:
        """Years to shift male mortality improvement scale forward (0 = no shift)."""
        return self.raw.get("modeling", {}).get("male_mp_forward_shift", 0)

    @property
    def cola_proration_cutoff_year(self) -> Optional[int]:
        """Year boundary for COLA proration (null if not applicable)."""
        return self.cola.get("proration_cutoff_year")

    @property
    def plan_design_cutoff_year(self) -> Optional[int]:
        """Year boundary for plan design ratio split (null if not applicable)."""
        return self.raw.get("plan_design", {}).get("cutoff_year")

    @property
    def salary_growth_col_map(self) -> Dict[str, str]:
        """Map class names to salary growth column names in input data."""
        return self.raw.get("salary_growth_col_map", {})

    @property
    def base_table_map(self) -> Dict[str, str]:
        """Map class names to mortality base table type (regular/safety/general)."""
        return self.raw.get("base_table_map", {})

    def get_base_table_type(self, class_name: str) -> str:
        """Resolve mortality base table type for a class."""
        return self.base_table_map.get(class_name, "general")

    @property
    def max_entry_year(self) -> int:
        return self.start_year + self.model_period

    @property
    def entry_year_range(self) -> range:
        return range(self.min_entry_year, self.max_entry_year + 1)

    @property
    def age_range(self) -> range:
        return range(self.min_age, self.max_age + 1)

    @property
    def yos_range(self) -> range:
        return range(0, self.max_yos + 1)

    @property
    def max_year(self) -> int:
        return self.start_year + self.model_period + self.max_age - self.min_age

    # --- Namespace adapters for ModelConstants compatibility ---
    # These let benefit_tables.py, pipeline.py, funding_model.py use PlanConfig
    # with the same `constants.ranges.X` / `constants.economic.X` access patterns.

    @property
    def ranges(self) -> SimpleNamespace:
        return SimpleNamespace(
            min_age=self.min_age, max_age=self.max_age,
            start_year=self.start_year, new_year=self.new_year,
            min_entry_year=self.min_entry_year, model_period=self.model_period,
            max_yos=self.max_yos,
            max_entry_year=self.max_entry_year,
            entry_year_range=self.entry_year_range,
            age_range=self.age_range,
            yos_range=self.yos_range,
            max_year=self.max_year,
        )

    @property
    def economic(self) -> SimpleNamespace:
        return SimpleNamespace(
            dr_current=self.dr_current, dr_new=self.dr_new, dr_old=self.dr_old,
            payroll_growth=self.payroll_growth, pop_growth=self.pop_growth,
            inflation=self.inflation, model_return=self.model_return,
        )

    @property
    def benefit(self) -> SimpleNamespace:
        c = self.cola
        return SimpleNamespace(
            db_ee_cont_rate=self.db_ee_cont_rate,
            db_ee_interest_rate=self.db_ee_interest_rate,
            cal_factor=self.cal_factor,
            retire_refund_ratio=self.retire_refund_ratio,
            cola_tier_1_active=c.get("tier_1_active", 0.0),
            cola_tier_1_active_constant=c.get("tier_1_active_constant", False),
            cola_tier_2_active=c.get("tier_2_active", 0.0),
            cola_tier_3_active=c.get("tier_3_active", 0.0),
            cola_current_retire=c.get("current_retire", 0.0),
            cola_current_retire_one=c.get("current_retire_one_time", 0.0),
            one_time_cola=c.get("one_time_cola", False),
        )

    @property
    def funding(self) -> SimpleNamespace:
        return SimpleNamespace(
            funding_policy=self.funding_policy,
            amo_method=self.amo_method,
            amo_period_new=self.amo_period_new,
            amo_pay_growth=self.amo_pay_growth,
            funding_lag=self.funding_lag,
            amo_period_term=self.amo_period_term,
            amo_term_growth=self.amo_term_growth,
            ava_smoothing=self.ava_smoothing,
        )

    @property
    def class_data(self) -> dict:
        """Dict of class_name → namespace with ACFR + calibration fields.

        Compatible with ModelConstants.class_data[cn].X access pattern.
        """
        result = {}
        for cn, acfr in self.valuation_inputs.items():
            cal = self.calibration.get(cn, {})
            result[cn] = SimpleNamespace(
                ben_payment=acfr["ben_payment"],
                retiree_pop=acfr["retiree_pop"],
                total_active_member=acfr["total_active_member"],
                er_dc_cont_rate=acfr["er_dc_cont_rate"],
                val_norm_cost=acfr["val_norm_cost"],
                nc_cal=cal.get("nc_cal", 1.0),
                pvfb_term_current=cal.get("pvfb_term_current", 0.0),
            )
        return result

    @property
    def plan_design(self) -> SimpleNamespace:
        """Compatible with ModelConstants.plan_design.get_ratios(is_special)."""
        config = self

        def _get_ratios(is_special: bool) -> tuple:
            # Use "special_group" or "default" group
            group = "special_group" if is_special else "default"
            pd_defs = config.plan_design_defs
            ratios = pd_defs.get(group, pd_defs.get("default", {}))
            before = ratios.get("before_2018", ratios.get("before_new_year", 1.0))
            after = ratios.get("after_2018", ratios.get("after_new_year", before))
            new = ratios.get("new", ratios.get("new_db", 1.0))
            return (before, after, new)

        return SimpleNamespace(get_ratios=_get_ratios)

    def get_design_ratios(self, class_name: str) -> Dict[str, Tuple[float, float, float]]:
        """Return plan design ratios for each benefit type.

        Returns {bt: (before, after, new)} for each bt in benefit_types.
        'before' = pre-new_year legacy, 'after' = post-2018/pre-new_year,
        'new' = post-new_year new hires.

        Example: {"db": (0.75, 0.25, 0.25), "dc": (0.25, 0.75, 0.75)}

        Design-ratio grouping can differ from tier-eligibility grouping.
        If ``design_ratio_group_map`` is present in config, it overrides the
        default class_group lookup for this class.
        """
        override_map = self.raw.get("design_ratio_group_map", {})
        group = override_map.get(class_name, self.class_group(class_name))
        pd_defs = self.plan_design_defs
        ratios = pd_defs.get(group, pd_defs.get("default", {}))

        result = {}
        for bt in self.benefit_types:
            if bt == "db":
                before = ratios.get("before_2018", ratios.get("before_new_year", 1.0))
                after = ratios.get("after_2018", ratios.get("after_new_year", before))
                new = ratios.get("new", ratios.get("new_db", 1.0))
                result["db"] = (before, after, new)
            elif bt == "cb":
                before = ratios.get("before_cb", 0.0)
                after = ratios.get("after_cb", 0.0)
                new = ratios.get("new_cb", 0.0)
                result["cb"] = (before, after, new)
            elif bt == "dc":
                # DC is the complement: whatever isn't DB or CB
                db_before, db_after, db_new = result.get("db", (1.0, 1.0, 1.0))
                cb_before, cb_after, cb_new = result.get("cb", (0.0, 0.0, 0.0))
                result["dc"] = (
                    1.0 - db_before - cb_before,
                    1.0 - db_after - cb_after,
                    1.0 - db_new - cb_new,
                )
        return result

    def class_group(self, class_name: str) -> str:
        """Return the group name for a given class."""
        return self._class_to_group.get(class_name, "default")

    def is_special(self, class_name: str) -> bool:
        """Whether a class is in the special group."""
        return self.class_group(class_name) == "special_group"

    def get_fas_years(self, tier_name: str) -> int:
        """Look up FAS averaging period from tier config.

        Falls back to fas_years_default if tier has no fas_years.
        """
        tier_base = tier_name.split("_")[0]
        if len(tier_name.split("_")) > 1:
            tier_base = tier_name.split("_")[0] + "_" + tier_name.split("_")[1]
        for td in self.tier_defs:
            if td["name"] == tier_base:
                return td.get("fas_years", self.fas_years_default)
        return self.fas_years_default

    def get_class_inputs(self, class_name: str) -> dict:
        """Return ACFR data for a class (with calibration applied)."""
        base = dict(self.valuation_inputs.get(class_name, {}))
        cal = self.calibration.get(class_name, {})
        base["nc_cal"] = cal.get("nc_cal", 1.0)
        base["pvfb_term_current"] = cal.get("pvfb_term_current", 0.0)
        return base

    def validate(self) -> list:
        """Check config for common issues; return list of warning strings.

        Intended for third-plan authors: flags non-obvious defaults,
        missing optional fields, and structural inconsistencies.
        """
        warnings = []

        # ben_payment: required per-class field — initial-year pension
        # payments to current retirees.
        for cn, acfr in self.valuation_inputs.items():
            if "ben_payment" not in acfr:
                warnings.append(
                    f"class '{cn}' is missing 'ben_payment' in valuation_inputs. "
                    f"This is the initial-year pension benefit payments to "
                    f"current retirees (used to seed the retiree liability "
                    f"projection)."
                )

        # Calibration: warn if any class has nc_cal far from 1.0
        for cn, cal in self.calibration.items():
            nc_cal = cal.get("nc_cal", 1.0)
            if nc_cal < 0.8 or nc_cal > 1.2:
                warnings.append(
                    f"class '{cn}' has nc_cal={nc_cal:.3f} (outside 0.8-1.2 range). "
                    f"This may indicate data or assumption issues."
                )

        # Entrant profile: check if file exists or will be derived
        data_dir = self.resolve_data_dir()
        has_explicit_ep = (data_dir / "demographics" / "entrant_profile.csv").exists()
        uses_start_year = self.entrant_salary_at_start_year
        if has_explicit_ep and not uses_start_year:
            warnings.append(
                "entrant_profile.csv exists but entrant_salary_at_start_year "
                "is not set. The profile salaries may not be scaled correctly."
            )

        # Class coverage: every class in classes must have an valuation_inputs entry
        for cn in self.classes:
            if cn not in self.valuation_inputs:
                warnings.append(
                    f"class '{cn}' is listed in 'classes' but has no entry in "
                    f"valuation_inputs. Required fields: ben_payment, retiree_pop, "
                    f"total_active_member, val_norm_cost, val_aal."
                )

        # DC fields: if benefit_types includes "dc", each class needs er_dc_cont_rate
        if "dc" in self.benefit_types:
            for cn in self.classes:
                acfr = self.valuation_inputs.get(cn, {})
                if "er_dc_cont_rate" not in acfr:
                    warnings.append(
                        f"class '{cn}' is missing 'er_dc_cont_rate' in valuation_inputs "
                        f"but benefit_types includes 'dc'."
                    )

        # Grouped headcount: check that group members share total_active_member
        for cn, acfr in self.valuation_inputs.items():
            hcg = acfr.get("headcount_group")
            if hcg and len(hcg) > 1:
                target = acfr["total_active_member"]
                for peer in hcg:
                    peer_acfr = self.valuation_inputs.get(peer, {})
                    peer_target = peer_acfr.get("total_active_member")
                    if peer_target != target:
                        warnings.append(
                            f"headcount_group mismatch: '{cn}' has total_active_member="
                            f"{target} but peer '{peer}' has {peer_target}. "
                            f"Grouped classes must share the same target."
                        )
                        break

        return warnings

    def validate_data_files(self) -> list:
        """Check that required data files exist for this plan.

        Call early (before running the pipeline) to fail fast with a clear
        message listing all missing files, rather than crashing mid-pipeline.
        """
        missing = []
        data_dir = self.resolve_data_dir()

        # Per-class demographic files
        demo_dir = data_dir / "demographics"
        for cn in self.classes:
            for suffix in ("headcount", "salary"):
                # Try class-prefixed, then unprefixed (single-class plans)
                prefixed = demo_dir / f"{cn}_{suffix}.csv"
                unprefixed = demo_dir / f"{suffix}.csv"
                if not prefixed.exists() and not unprefixed.exists():
                    missing.append(str(prefixed))

        # Salary growth: per-class or shared
        has_any_sg = False
        for cn in self.classes:
            if (demo_dir / f"{cn}_salary_growth.csv").exists():
                has_any_sg = True
                break
        if not has_any_sg and not (demo_dir / "salary_growth.csv").exists():
            missing.append(str(demo_dir / "salary_growth.csv"))

        # Retiree distribution
        if not (demo_dir / "retiree_distribution.csv").exists():
            missing.append(str(demo_dir / "retiree_distribution.csv"))

        # Decrement files: per-class or shared
        decr_dir = data_dir / "decrements"
        for cn in self.classes:
            for suffix in ("termination_rates", "retirement_rates"):
                prefixed = decr_dir / f"{cn}_{suffix}.csv"
                unprefixed = decr_dir / f"{suffix}.csv"
                if not prefixed.exists() and not unprefixed.exists():
                    missing.append(str(prefixed))

        # Mortality
        mort_dir = data_dir / "mortality"
        for f in ("base_rates.csv", "improvement_scale.csv"):
            if not (mort_dir / f).exists():
                missing.append(str(mort_dir / f))

        # Funding
        fund_dir = data_dir / "funding"
        for f in ("init_funding.csv", "return_scenarios.csv"):
            if not (fund_dir / f).exists():
                missing.append(str(fund_dir / f))

        return missing


# ---------------------------------------------------------------------------
# Tier evaluator — replaces tier_logic.py
# ---------------------------------------------------------------------------

def _matches_condition(cond: dict, age: int, yos: int,
                       entry_year: int = 0, entry_age: int = 0) -> bool:
    """Check if a single condition dict is satisfied.

    Supports keys: min_age, min_yos, rule_of (age+yos >= N).
    All present keys must be satisfied (AND).
    """
    if "min_age" in cond and age < cond["min_age"]:
        return False
    if "min_yos" in cond and yos < cond["min_yos"]:
        return False
    if "rule_of" in cond and (age + yos) < cond["rule_of"]:
        return False
    return True


def _matches_any(rules: list, age: int, yos: int,
                 entry_year: int = 0, entry_age: int = 0) -> bool:
    """Check if any rule in the list matches (OR of conditions)."""
    for rule in rules:
        if _matches_condition(rule, age, yos, entry_year, entry_age):
            return True
    return False


def _resolve_tier_def(tier_name: str, tier_defs: tuple) -> dict:
    """Find a tier def by name."""
    for td in tier_defs:
        if td["name"] == tier_name:
            return td
    raise ValueError(f"Unknown tier: {tier_name}")


def _get_eligibility(tier_def: dict, group: str, all_tier_defs: tuple) -> dict:
    """Get eligibility rules for a tier+group, following same_as references."""
    # Follow eligibility_same_as chain
    td = tier_def
    seen = set()
    while "eligibility_same_as" in td:
        ref = td["eligibility_same_as"]
        if ref in seen:
            raise ValueError(f"Circular eligibility_same_as: {ref}")
        seen.add(ref)
        td = _resolve_tier_def(ref, all_tier_defs)

    elig = td["eligibility"]
    # Try group-specific first, then "default"
    return elig.get(group, elig.get("default", {}))


def extract_normal_retirement_params(
    config, tier_name: str, class_name: str,
) -> tuple:
    """Extract NRA, min vesting YOS, and YOS-only threshold from tier eligibility.

    Returns (nra, nra_yos, yos_threshold) where:
      - nra: minimum normal retirement age (from age+YOS rule with lowest min_yos)
      - nra_yos: min_yos from that same rule
      - yos_threshold: min_yos from the YOS-only rule (no min_age)

    These replace the hardcoded values in cohort_calculator.py.
    """
    # Strip retirement-status suffix (e.g. "tier_1_vested" -> "tier_1")
    tier_base = tier_name
    for suffix in ("_norm", "_early", "_vested", "_non_vested", "_reduced"):
        if tier_base.endswith(suffix):
            tier_base = tier_base[:-len(suffix)]
            break

    td = _resolve_tier_def(tier_base, config.tier_defs)
    group = config.class_group(class_name)
    elig = _get_eligibility(td, group, config.tier_defs)
    normal_rules = elig.get("normal", [])

    nra = None
    nra_yos = None
    yos_threshold = None

    for rule in normal_rules:
        has_age = "min_age" in rule
        has_yos = "min_yos" in rule
        has_rule_of = "rule_of" in rule

        if has_yos and not has_age and not has_rule_of:
            # YOS-only rule → yos_threshold
            if yos_threshold is None or rule["min_yos"] < yos_threshold:
                yos_threshold = rule["min_yos"]
        elif has_age and has_yos and not has_rule_of:
            # Age+YOS rule → NRA candidate (pick lowest min_yos variant)
            if nra_yos is None or rule["min_yos"] < nra_yos:
                nra = rule["min_age"]
                nra_yos = rule["min_yos"]

    # Fallback: if no age+YOS rule found, use vesting_yos
    if nra_yos is None:
        nra_yos = elig.get("vesting_yos", 5)

    return nra, nra_yos, yos_threshold


def resolve_cola_scalar(
    config, tier_name: str, entry_year: int, yos: int,
) -> float:
    """Scalar COLA lookup — mirrors resolve_cola_vec for the per-yos loop.

    Uses cola_key from tier definition, prorate_cola flag, and
    proration_cutoff_year from config (not hardcoded tier names or years).
    """
    # Strip retirement-status suffix
    tier_base = tier_name
    for suffix in ("_norm", "_early", "_vested", "_non_vested", "_reduced"):
        if tier_base.endswith(suffix):
            tier_base = tier_base[:-len(suffix)]
            break

    td = _resolve_tier_def(tier_base, config.tier_defs)
    cola_key = td["cola_key"]
    raw_cola = config.cola.get(cola_key, 0.0)
    cola_cutoff = config.cola_proration_cutoff_year

    should_prorate = (
        td.get("prorate_cola", False)
        and not config.cola.get(cola_key + "_constant", False)
        and cola_cutoff is not None
        and raw_cola > 0
    )

    if should_prorate and yos > 0:
        yos_b4 = min(max(cola_cutoff - entry_year, 0), yos)
        return raw_cola * yos_b4 / yos
    return raw_cola


def _entry_year_in_tier(entry_year: int, tier_def: dict, new_year: int) -> bool:
    """Check if entry_year falls within this tier's range."""
    # Handle grandfathered assignment separately
    if tier_def.get("assignment") == "grandfathered_rule":
        return False  # must be checked via is_grandfathered

    lo = tier_def.get("entry_year_min")
    if tier_def.get("entry_year_min_param") == "new_year":
        lo = new_year

    hi = tier_def.get("entry_year_max")
    if tier_def.get("entry_year_max_param") == "new_year":
        hi = new_year

    if lo is not None and entry_year < lo:
        return False
    if hi is not None and entry_year >= hi:
        return False
    return True


def _is_grandfathered(entry_year: int, entry_age: int,
                      params: dict) -> bool:
    """Conditional grandfathering: check conditions as of cutoff_year."""
    cutoff = params["cutoff_year"]
    if entry_year > cutoff:
        return False
    yos_at_cutoff = min(cutoff - entry_year, 70)
    age_at_cutoff = entry_age + yos_at_cutoff
    for cond in params["conditions"]:
        if "min_age_at_cutoff" in cond and age_at_cutoff >= cond["min_age_at_cutoff"]:
            return True
        if "rule_of_at_cutoff" in cond and (age_at_cutoff + yos_at_cutoff) >= cond["rule_of_at_cutoff"]:
            return True
        if "min_yos_at_cutoff" in cond and yos_at_cutoff >= cond["min_yos_at_cutoff"]:
            return True
    return False


def get_tier(config: PlanConfig, class_name: str,
             entry_year: int, age: int, yos: int,
             entry_age: int = 0) -> str:
    """Determine tier+status for a member, driven by plan config.

    Returns tier string like "tier_1_norm", "grandfathered_early", etc.
    """
    group = config.class_group(class_name)

    # Find which tier this entry_year belongs to
    matched_tier = None
    for td in config.tier_defs:
        if td.get("assignment") == "grandfathered_rule":
            ea = entry_age if entry_age > 0 else (age - yos)
            if _is_grandfathered(entry_year, ea, td["grandfathered_params"]):
                matched_tier = td
                break
        elif _entry_year_in_tier(entry_year, td, config.new_year):
            # For tiers with not_grandfathered flag, skip if grandfathered
            if td.get("not_grandfathered"):
                gf_tier = next((t for t in config.tier_defs
                                if t.get("assignment") == "grandfathered_rule"), None)
                if gf_tier:
                    ea = entry_age if entry_age > 0 else (age - yos)
                    if _is_grandfathered(entry_year, ea, gf_tier["grandfathered_params"]):
                        continue
            matched_tier = td
            break

    if matched_tier is None:
        # Fallback: use last tier
        matched_tier = config.tier_defs[-1]

    tier_name = matched_tier["name"]
    elig = _get_eligibility(matched_tier, group, config.tier_defs)

    if not elig:
        return f"{tier_name}_non_vested"

    # Check normal retirement
    normal_rules = elig.get("normal", [])
    if _matches_any(normal_rules, age, yos, entry_year, entry_age):
        return f"{tier_name}_norm"

    # Check early retirement
    early_rules = elig.get("early", [])
    if _matches_any(early_rules, age, yos, entry_year, entry_age):
        return f"{tier_name}_early"

    # Vested or non-vested
    vesting_yos = elig.get("vesting_yos", 5)
    if yos >= vesting_yos:
        return f"{tier_name}_vested"

    return f"{tier_name}_non_vested"


def get_tier_vectorized(config: PlanConfig, class_name: str,
                        entry_year: np.ndarray, age: np.ndarray,
                        yos: np.ndarray,
                        entry_age: np.ndarray = None) -> np.ndarray:
    """Vectorized tier determination."""
    n = len(entry_year)
    result = np.empty(n, dtype=object)
    ea = entry_age if entry_age is not None else (age - yos)
    for i in range(n):
        result[i] = get_tier(config, class_name,
                             int(entry_year[i]), int(age[i]), int(yos[i]),
                             int(ea[i]))
    return result


# ---------------------------------------------------------------------------
# Benefit multiplier — replaces tier_logic.get_ben_mult
# ---------------------------------------------------------------------------

def get_ben_mult(config: PlanConfig, class_name: str, tier: str,
                 dist_age: int, yos: int, dist_year: int = 0) -> float:
    """Look up benefit multiplier from config tables.

    Returns the multiplier or NaN if the member is not eligible.
    """
    bm_defs = config.benefit_mult_defs
    class_rules = bm_defs.get(class_name)
    if class_rules is None:
        return float("nan")

    # Determine which tier's rules to use
    tier_base = tier.split("_")[0] + "_" + tier.split("_")[1] if "_" in tier else tier
    # e.g. "tier_1_norm" → "tier_1", "grandfathered_early" → "grandfathered"

    # Check all_tiers first
    if "all_tiers" in class_rules:
        rules = class_rules["all_tiers"]
    else:
        rules = class_rules.get(tier_base)
        # Follow same_as references
        if rules is None:
            for key in class_rules:
                if key.endswith("_same_as") and key.replace("_same_as", "") == tier_base:
                    ref_tier = class_rules[key]
                    rules = class_rules.get(ref_tier)
                    break
        if rules is None:
            return float("nan")

    # Flat multiplier
    if "flat" in rules:
        # Check for year-dependent override (e.g. FRS special pre-1974)
        if "flat_before_year" in rules and dist_year <= rules["flat_before_year"]["year"]:
            return rules["flat_before_year"]["mult"]
        return rules["flat"]

    # Graded multiplier: evaluate rules in order, first match wins
    if "graded" in rules:
        for entry in rules["graded"]:
            or_conditions = entry["or"]
            for cond in or_conditions:
                if _matches_condition(cond, dist_age, yos):
                    return entry["mult"]

        # Early retirement fallback
        if "early" in tier and "early_fallback" in rules:
            return rules["early_fallback"]

        return float("nan")

    return float("nan")


# ---------------------------------------------------------------------------
# Early retirement reduction — replaces tier_logic.get_reduce_factor
# ---------------------------------------------------------------------------

def get_reduce_factor(config: PlanConfig, class_name: str, tier: str,
                      dist_age: int, yos: int = 0,
                      entry_year: int = 0) -> float:
    """Look up early retirement reduction factor from config.

    Normal retirement: 1.0.  Early retirement: formula or table lookup.
    """
    if "norm" in tier:
        return 1.0
    if "early" not in tier and "reduced" not in tier:
        return float("nan")

    # Find the tier definition — extract tier name (before _early/_norm/_vested)
    # E.g., "intermediate_early" → "intermediate", "grandfathered_early" → "grandfathered"
    tier_name = tier.rsplit("_", 1)[0] if "_" in tier else tier
    tier_def = None
    for td in config.tier_defs:
        if td["name"] == tier_name:
            tier_def = td
            break

    if tier_def is None:
        return float("nan")

    # Follow same_as for reduction too
    rd = tier_def
    seen = set()
    while "early_retire_reduction_same_as" in rd:
        ref = rd["early_retire_reduction_same_as"]
        if ref in seen:
            break
        seen.add(ref)
        rd = _resolve_tier_def(ref, config.tier_defs)

    reduction = rd.get("early_retire_reduction", {})

    # Simple NRA-based reduction (rate_per_year × years before NRA)
    if "nra" in reduction:
        nra_map = reduction["nra"]
        rate = reduction["rate_per_year"]
        nra = nra_map.get(class_name, nra_map.get("default", 65))
        return 1.0 - rate * (nra - dist_age)

    # Rule-based reduction (condition → formula lookup)
    if "rules" in reduction:
        reduce_tables = getattr(config, "_reduce_tables", None)
        for rule in reduction["rules"]:
            cond = rule.get("condition", {})
            # Check condition
            if not _check_reduce_condition(cond, dist_age, yos, entry_year, tier_name, config):
                continue
            formula = rule.get("formula", "linear")
            if formula == "linear":
                rate = rule["rate_per_year"]
                nra = rule.get("nra", 65)
                return max(0.0, 1.0 - rate * (nra - dist_age))
            elif formula == "table":
                table_key = rule.get("table_key", "")
                if reduce_tables and table_key in reduce_tables:
                    return _lookup_reduce_table(reduce_tables[table_key], table_key, dist_age, yos)
                # Fallback: use Reduced Others table values
                return _default_reduce_factor(dist_age)
        return float("nan")

    return float("nan")


def _check_reduce_condition(cond: dict, dist_age: int, yos: int,
                            entry_year: int, tier_name: str,
                            config: PlanConfig) -> bool:
    """Check if a reduction rule condition is met."""
    if not cond:
        return True  # empty condition = always matches
    if "min_yos" in cond and yos < cond["min_yos"]:
        return False
    if "min_age" in cond and dist_age < cond["min_age"]:
        return False
    if "rule_of" in cond and (dist_age + yos) < cond["rule_of"]:
        return False
    if cond.get("grandfathered") and "grandfathered" not in tier_name:
        return False
    if "or" in cond:
        return any(_check_reduce_condition(sub, dist_age, yos, entry_year, tier_name, config)
                   for sub in cond["or"])
    return True


def _lookup_reduce_table(table, table_key: str, dist_age: int, yos: int) -> float:
    """Look up reduction factor from a DataFrame table."""
    if "gft" in table_key.lower():
        # GFT table indexed by (yos, age) — columns are integer ages
        row = table[table["yos"] == yos]
        if row.empty:
            row = table[table["yos"] <= yos].tail(1)
        if row.empty:
            return float("nan")
        age_cols = [c for c in table.columns if c != "yos"]
        age_col = int(dist_age) if int(dist_age) in age_cols else None
        if age_col is None:
            int_cols = [c for c in age_cols if isinstance(c, (int, float))]
            if int_cols:
                age_col = min(int_cols, key=lambda x: abs(x - dist_age))
        if age_col is not None:
            val = row.iloc[0][age_col]
            if val is not None and not (isinstance(val, float) and val != val):
                return float(val)
        return float("nan")
    else:
        # Others table indexed by age
        row = table[table["age"] == dist_age]
        if row.empty:
            return float("nan")
        col = [c for c in table.columns if c != "age"][0]
        return float(row.iloc[0][col])


def _default_reduce_factor(dist_age: int) -> float:
    """Default early retirement reduction factors when table not available."""
    factors = {55: 0.43, 56: 0.46, 57: 0.50, 58: 0.55, 59: 0.59,
               60: 0.64, 61: 0.70, 62: 0.76, 63: 0.84, 64: 0.91, 65: 1.00}
    return factors.get(dist_age, 1.0 if dist_age >= 65 else float("nan"))


# ---------------------------------------------------------------------------
# Separation type — replaces tier_logic.get_sep_type
# ---------------------------------------------------------------------------

def get_sep_type(tier: str) -> str:
    """Determine separation type from tier string.

    Returns: "retire", "vested", or "non_vested"
    """
    if any(x in tier for x in ("early", "norm", "reduced")):
        return "retire"
    if "non_vested" in tier:
        return "non_vested"
    if "vested" in tier:
        return "vested"
    return "non_vested"


# ---------------------------------------------------------------------------
# Vectorized resolvers
# ---------------------------------------------------------------------------
#
# These operate on numpy arrays and produce bit-identical output to the scalar
# `get_tier`, `_get_cola`-equivalent, `get_ben_mult`, and `get_reduce_factor`
# functions above. They are designed to be called once per builder on the full
# set of rows, replacing per-row `.apply(lambda: get_tier(...))` and Python-loop
# `get_tier_vectorized` patterns.
#
# Semantics must match the scalar versions exactly — the scalar functions are
# the source of truth, and the unit tests in tests/test_pension_model/
# test_vectorized_resolvers.py enumerate a grid of inputs and assert equality.


def _entry_year_in_tier_vec(entry_year: np.ndarray, tier_def: dict,
                            new_year: int) -> np.ndarray:
    """Vectorized version of _entry_year_in_tier."""
    if tier_def.get("assignment") == "grandfathered_rule":
        return np.zeros(len(entry_year), dtype=bool)

    lo = tier_def.get("entry_year_min")
    if tier_def.get("entry_year_min_param") == "new_year":
        lo = new_year

    hi = tier_def.get("entry_year_max")
    if tier_def.get("entry_year_max_param") == "new_year":
        hi = new_year

    mask = np.ones(len(entry_year), dtype=bool)
    if lo is not None:
        mask &= entry_year >= lo
    if hi is not None:
        mask &= entry_year < hi
    return mask


def _is_grandfathered_vec(entry_year: np.ndarray, entry_age: np.ndarray,
                          params: dict) -> np.ndarray:
    """Vectorized version of _is_grandfathered."""
    cutoff = params["cutoff_year"]
    n = len(entry_year)

    in_range = entry_year <= cutoff
    yos_at_cutoff = np.minimum(cutoff - entry_year, 70)
    age_at_cutoff = entry_age + yos_at_cutoff

    result = np.zeros(n, dtype=bool)
    for cond in params["conditions"]:
        # Scalar _is_grandfathered returns True on the FIRST matching condition.
        # Vectorized: OR the per-condition masks. A row is grandfathered if ANY
        # condition matches. Equivalent because scalar short-circuits on True.
        if "min_age_at_cutoff" in cond:
            result |= in_range & (age_at_cutoff >= cond["min_age_at_cutoff"])
        if "rule_of_at_cutoff" in cond:
            result |= in_range & ((age_at_cutoff + yos_at_cutoff)
                                  >= cond["rule_of_at_cutoff"])
        if "min_yos_at_cutoff" in cond:
            result |= in_range & (yos_at_cutoff >= cond["min_yos_at_cutoff"])
    return result


def _matches_condition_vec(cond: dict, age: np.ndarray,
                           yos: np.ndarray) -> np.ndarray:
    """Vectorized version of _matches_condition (min_age / min_yos / rule_of)."""
    n = len(age)
    mask = np.ones(n, dtype=bool)
    if "min_age" in cond:
        mask &= age >= cond["min_age"]
    if "min_yos" in cond:
        mask &= yos >= cond["min_yos"]
    if "rule_of" in cond:
        mask &= (age + yos) >= cond["rule_of"]
    return mask


def _matches_any_vec(rules: list, age: np.ndarray,
                     yos: np.ndarray) -> np.ndarray:
    """Vectorized version of _matches_any (OR over AND rules)."""
    if not rules:
        return np.zeros(len(age), dtype=bool)
    result = np.zeros(len(age), dtype=bool)
    for rule in rules:
        result |= _matches_condition_vec(rule, age, yos)
    return result


_STATUS_SUFFIX = {NON_VESTED: "_non_vested", VESTED: "_vested",
                  EARLY: "_early", NORM: "_norm"}


def resolve_tiers_vec(config: PlanConfig,
                      class_name: np.ndarray,
                      entry_year: np.ndarray,
                      age: np.ndarray,
                      yos: np.ndarray,
                      entry_age: Optional[np.ndarray] = None,
                      ) -> Tuple[np.ndarray, np.ndarray]:
    """Vectorized tier resolution — returns integer tier_id and ret_status.

    Args:
        class_name: object array of class name strings
        entry_year, age, yos: int arrays
        entry_age: optional int array; rows where entry_age <= 0 fall back to
            age - yos (matching scalar default behavior)

    Returns:
        (tier_id, ret_status) where:
          tier_id: int32 array — index into config.tier_defs
          ret_status: int8 array — NON_VESTED/VESTED/EARLY/NORM
    """
    entry_year = np.asarray(entry_year, dtype=np.int64)
    age = np.asarray(age, dtype=np.int64)
    yos = np.asarray(yos, dtype=np.int64)
    n = len(entry_year)

    if entry_age is None:
        ea_arr = age - yos
    else:
        ea_arr = np.asarray(entry_age, dtype=np.int64)
        ea_arr = np.where(ea_arr > 0, ea_arr, age - yos)

    # Map class_name -> group via config._class_to_group
    group_map = config._class_to_group
    group = np.array([group_map.get(cn, "default") for cn in class_name],
                     dtype=object)

    # Locate a grandfathered tier def (if any) and compute its mask once
    gf_tier_def = None
    for td in config.tier_defs:
        if td.get("assignment") == "grandfathered_rule":
            gf_tier_def = td
            break
    if gf_tier_def is not None:
        gf_mask_global = _is_grandfathered_vec(
            entry_year, ea_arr, gf_tier_def["grandfathered_params"])
    else:
        gf_mask_global = np.zeros(n, dtype=bool)

    # Assign tier_def index to each row — first match wins
    tier_id = np.full(n, -1, dtype=np.int32)
    for i, td in enumerate(config.tier_defs):
        unassigned = tier_id == -1
        if not unassigned.any():
            break
        if td.get("assignment") == "grandfathered_rule":
            mask = gf_mask_global & unassigned
        else:
            mask = _entry_year_in_tier_vec(entry_year, td, config.new_year)
            mask &= unassigned
            if td.get("not_grandfathered"):
                mask &= ~gf_mask_global
        tier_id[mask] = i

    # Fallback: anything still unassigned gets the last tier def
    tier_id[tier_id == -1] = len(config.tier_defs) - 1

    # Resolve retirement status per (tier_def, group) combination
    ret_status = np.full(n, NON_VESTED, dtype=np.int8)
    unique_groups = set(group.tolist())
    for ti, td in enumerate(config.tier_defs):
        for grp in unique_groups:
            combo_mask = (tier_id == ti) & (group == grp)
            if not combo_mask.any():
                continue

            elig = _get_eligibility(td, grp, config.tier_defs)

            if not elig:
                # NON_VESTED is already the default
                continue

            sub_age = age[combo_mask]
            sub_yos = yos[combo_mask]

            normal_rules = elig.get("normal", [])
            early_rules = elig.get("early", [])
            vesting_yos = elig.get("vesting_yos", 5)

            norm_m = _matches_any_vec(normal_rules, sub_age, sub_yos)
            early_m = _matches_any_vec(early_rules, sub_age, sub_yos) & ~norm_m
            vested_m = (sub_yos >= vesting_yos) & ~norm_m & ~early_m

            sub_status = np.full(combo_mask.sum(), NON_VESTED, dtype=np.int8)
            sub_status[norm_m] = NORM
            sub_status[early_m] = EARLY
            sub_status[vested_m] = VESTED

            ret_status[combo_mask] = sub_status

    return tier_id, ret_status


def resolve_tiers_vec_str(config: PlanConfig,
                          class_name: np.ndarray,
                          entry_year: np.ndarray,
                          age: np.ndarray,
                          yos: np.ndarray,
                          entry_age: Optional[np.ndarray] = None,
                          ) -> np.ndarray:
    """Backward-compatible wrapper: returns tier strings like 'tier_1_norm'.

    Temporary — will be removed once all consumers migrate to integer encoding.
    """
    tier_id, ret_status = resolve_tiers_vec(
        config, class_name, entry_year, age, yos, entry_age)
    id_to_name = config._tier_id_to_name
    result = np.empty(len(tier_id), dtype=object)
    for i in range(len(tier_id)):
        result[i] = id_to_name[tier_id[i]] + _STATUS_SUFFIX[ret_status[i]]
    return result


def resolve_cola_vec(config: PlanConfig,
                     tier_id: np.ndarray,
                     entry_year: np.ndarray,
                     yos: np.ndarray) -> np.ndarray:
    """Vectorized COLA lookup — bit-identical to the _get_cola closure.

    Uses integer tier_id to match tier_defs directly (no string operations).
    """
    tier_id = np.asarray(tier_id, dtype=np.int32)
    entry_year = np.asarray(entry_year, dtype=np.int64)
    yos = np.asarray(yos, dtype=np.int64)
    n = len(tier_id)
    cola_cutoff = config.cola_proration_cutoff_year

    result = np.zeros(n, dtype=np.float64)

    for i, td in enumerate(config.tier_defs):
        mask = tier_id == i
        if not mask.any():
            continue

        cola_key = td["cola_key"]
        raw_cola = config.cola.get(cola_key, 0.0)

        should_prorate = (
            td.get("prorate_cola", False)
            and not config.cola.get(cola_key + "_constant", False)
            and cola_cutoff is not None
            and raw_cola > 0
        )

        if should_prorate:
            sub_ey = entry_year[mask]
            sub_yos = yos[mask]
            yos_b4 = np.minimum(np.maximum(cola_cutoff - sub_ey, 0), sub_yos)
            with np.errstate(divide="ignore", invalid="ignore"):
                safe_yos = np.where(sub_yos > 0, sub_yos, 1)
                prorated = raw_cola * yos_b4 / safe_yos
            vals = np.where(sub_yos > 0, prorated, raw_cola)
            result[mask] = vals
        else:
            result[mask] = raw_cola

    return result


def _resolve_ben_mult_rules(class_rules: dict, tier_base: str) -> Optional[dict]:
    """Scalar-equivalent rules lookup for a given (class, tier_base)."""
    if "all_tiers" in class_rules:
        return class_rules["all_tiers"]
    rules = class_rules.get(tier_base)
    if rules is None:
        for key in class_rules:
            if key.endswith("_same_as") and key.replace("_same_as", "") == tier_base:
                ref_tier = class_rules[key]
                rules = class_rules.get(ref_tier)
                break
    return rules



def resolve_ben_mult_vec(config: PlanConfig,
                         class_name: np.ndarray,
                         tier_id: np.ndarray,
                         ret_status: np.ndarray,
                         dist_age: np.ndarray,
                         yos: np.ndarray,
                         dist_year: np.ndarray) -> np.ndarray:
    """Vectorized benefit multiplier — bit-identical to scalar get_ben_mult.

    Uses integer tier_id for rule lookup (replaces _tier_base_vec string splitting)
    and ret_status for early-retirement fallback (replaces str.contains).
    """
    tier_id = np.asarray(tier_id, dtype=np.int32)
    ret_status = np.asarray(ret_status, dtype=np.int8)
    dist_age = np.asarray(dist_age, dtype=np.int64)
    yos = np.asarray(yos, dtype=np.int64)
    dist_year = np.asarray(dist_year, dtype=np.int64)
    n = len(tier_id)

    result = np.full(n, np.nan, dtype=np.float64)
    bm_defs = config.benefit_mult_defs
    id_to_name = config._tier_id_to_name

    # Group rows by (class_name, tier_id) — small set (few dozen combos)
    import pandas as pd
    keys = pd.Series(list(zip(
        class_name.tolist() if hasattr(class_name, 'tolist') else list(class_name),
        tier_id.tolist(),
    )))
    for (cn, tid), idx in keys.groupby(keys).groups.items():
        idx_arr = np.asarray(idx, dtype=np.int64)
        class_rules = bm_defs.get(cn)
        if class_rules is None:
            continue

        tier_name = id_to_name[tid]
        rules = _resolve_ben_mult_rules(class_rules, tier_name)
        if rules is None:
            continue

        sub_age = dist_age[idx_arr]
        sub_yos = yos[idx_arr]
        sub_year = dist_year[idx_arr]

        if "flat" in rules:
            vals = np.full(len(idx_arr), rules["flat"], dtype=np.float64)
            if "flat_before_year" in rules:
                before = rules["flat_before_year"]
                override_mask = sub_year <= before["year"]
                vals = np.where(override_mask, before["mult"], vals)
            result[idx_arr] = vals
            continue

        if "graded" in rules:
            sub_vals = np.full(len(idx_arr), np.nan, dtype=np.float64)
            assigned = np.zeros(len(idx_arr), dtype=bool)
            for entry in rules["graded"]:
                or_conditions = entry["or"]
                entry_mask = np.zeros(len(idx_arr), dtype=bool)
                for cond in or_conditions:
                    entry_mask |= _matches_condition_vec(cond, sub_age, sub_yos)
                new_assign = entry_mask & ~assigned
                if new_assign.any():
                    sub_vals[new_assign] = entry["mult"]
                    assigned |= new_assign
            # Early-retire fallback for unmatched rows
            if "early_fallback" in rules:
                sub_ret_status = ret_status[idx_arr]
                fallback_mask = ~assigned & (sub_ret_status == EARLY)
                sub_vals[fallback_mask] = rules["early_fallback"]
            result[idx_arr] = sub_vals
            continue

    return result


def resolve_reduce_factor_vec(config: PlanConfig,
                              class_name: np.ndarray,
                              tier_id: np.ndarray,
                              ret_status: np.ndarray,
                              dist_age: np.ndarray,
                              yos: np.ndarray,
                              entry_year: np.ndarray) -> np.ndarray:
    """Vectorized early retirement reduction — bit-identical to get_reduce_factor.

    Uses integer ret_status for norm/early dispatch (replaces str.contains)
    and tier_id for tier_def lookup (replaces string rsplit).
    """
    tier_id = np.asarray(tier_id, dtype=np.int32)
    ret_status = np.asarray(ret_status, dtype=np.int8)
    dist_age = np.asarray(dist_age, dtype=np.int64)
    yos = np.asarray(yos, dtype=np.int64)
    entry_year = np.asarray(entry_year, dtype=np.int64)
    n = len(tier_id)

    result = np.full(n, np.nan, dtype=np.float64)

    # Normal retirement → 1.0
    result[ret_status == NORM] = 1.0

    # Early retirement needs reduction factor
    needs_reduction = ret_status == EARLY
    if not needs_reduction.any():
        return result

    # Resolve per (class_name, tier_id) group
    import pandas as pd
    reduce_tables = getattr(config, "_reduce_tables", None)
    id_to_name = config._tier_id_to_name
    keys = pd.Series(list(zip(class_name.tolist(), tier_id.tolist())))
    keys = keys[needs_reduction]
    for (cn, tid), idx in keys.groupby(keys).groups.items():
        idx_arr = np.asarray(idx, dtype=np.int64)

        tname = id_to_name[tid]

        # Find tier def + follow early_retire_reduction_same_as chain
        tier_def = config.tier_defs[tid]
        if tier_def is None:
            continue

        rd = tier_def
        seen = set()
        while "early_retire_reduction_same_as" in rd:
            ref = rd["early_retire_reduction_same_as"]
            if ref in seen:
                break
            seen.add(ref)
            rd = _resolve_tier_def(ref, config.tier_defs)

        reduction = rd.get("early_retire_reduction", {})
        sub_age = dist_age[idx_arr]
        sub_yos = yos[idx_arr]
        sub_ey = entry_year[idx_arr]

        # NRA-based reduction (rate_per_year × years before NRA)
        if "nra" in reduction:
            nra_map = reduction["nra"]
            rate = reduction["rate_per_year"]
            nra = nra_map.get(cn, nra_map.get("default", 65))
            vals = 1.0 - rate * (nra - sub_age)
            result[idx_arr] = vals
            continue

        # Rule-based reduction (condition → formula lookup)
        if "rules" in reduction:
            sub_vals = np.full(len(idx_arr), np.nan, dtype=np.float64)
            assigned = np.zeros(len(idx_arr), dtype=bool)
            for rule in reduction["rules"]:
                cond = rule.get("condition", {})
                cmask = _reduce_condition_vec(cond, sub_age, sub_yos, sub_ey,
                                              tname)
                cmask &= ~assigned
                if not cmask.any():
                    continue
                formula = rule.get("formula", "linear")
                if formula == "linear":
                    rate = rule["rate_per_year"]
                    nra = rule.get("nra", 65)
                    vals = np.maximum(0.0, 1.0 - rate * (nra - sub_age[cmask]))
                    sub_vals[cmask] = vals
                    assigned |= cmask
                elif formula == "table":
                    table_key = rule.get("table_key", "")
                    # Per-row table lookup (fallback to scalar loop — rare path)
                    local_idx = np.where(cmask)[0]
                    for li in local_idx:
                        if reduce_tables and table_key in reduce_tables:
                            sub_vals[li] = _lookup_reduce_table(
                                reduce_tables[table_key], table_key,
                                int(sub_age[li]), int(sub_yos[li]))
                        else:
                            sub_vals[li] = _default_reduce_factor(int(sub_age[li]))
                    assigned |= cmask
            result[idx_arr] = sub_vals

    return result


def _reduce_condition_vec(cond: dict, dist_age: np.ndarray, yos: np.ndarray,
                          entry_year: np.ndarray,
                          tier_name: str) -> np.ndarray:
    """Vectorized version of _check_reduce_condition."""
    n = len(dist_age)
    if not cond:
        return np.ones(n, dtype=bool)
    mask = np.ones(n, dtype=bool)
    if "min_yos" in cond:
        mask &= yos >= cond["min_yos"]
    if "min_age" in cond:
        mask &= dist_age >= cond["min_age"]
    if "rule_of" in cond:
        mask &= (dist_age + yos) >= cond["rule_of"]
    if cond.get("grandfathered") and "grandfathered" not in tier_name:
        mask &= False
    if "or" in cond:
        or_mask = np.zeros(n, dtype=bool)
        for sub in cond["or"]:
            or_mask |= _reduce_condition_vec(sub, dist_age, yos, entry_year,
                                             tier_name)
        mask &= or_mask
    return mask


# ---------------------------------------------------------------------------
# Plan design ratio lookup
# ---------------------------------------------------------------------------

def get_plan_design_ratios(config: PlanConfig, class_name: str) -> Tuple[float, float, float]:
    """Return (before_2018_db, after_2018_db, new_db) plan design ratios.

    Ratios may differ by class group; single-class plans typically use 1.0/1.0/1.0.
    """
    group = config.class_group(class_name)
    pd_defs = config.plan_design_defs

    # Try group-specific, then "default"
    ratios = pd_defs.get(group, pd_defs.get("default", {}))

    before = ratios.get("before_2018", ratios.get("before_new_year", 1.0))
    after = ratios.get("after_2018", ratios.get("after_new_year", before))
    new = ratios.get("new", ratios.get("new_db", 1.0))

    return (before, after, new)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge overrides into base dict (returns a new dict)."""
    result = dict(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_plan_config(config_path: Path,
                     calibration_path: Optional[Path] = None,
                     scenario_path: Optional[Path] = None) -> PlanConfig:
    """Load a PlanConfig from a JSON file.

    Args:
        config_path: Path to plan_config.json
        calibration_path: Optional path to calibration.json (overrides)
        scenario_path: Optional path to a scenario JSON file. The
            ``overrides`` dict is deep-merged into the plan config before
            constructing PlanConfig. Calibration factors are not affected.
    """
    with open(config_path) as f:
        raw = json.load(f)

    # Apply scenario overrides (before calibration, so calibration wins)
    scenario_name = None
    if scenario_path is not None:
        with open(scenario_path) as f:
            scenario = json.load(f)
        scenario_name = scenario.get("name", scenario_path.stem)
        raw = _deep_merge(raw, scenario.get("overrides", {}))

    # Stash scenario name in raw for downstream access
    if scenario_name:
        raw["_scenario_name"] = scenario_name

    eco = raw["economic"]
    ben = raw["benefit"]
    fun = raw["funding"]
    rng = raw["ranges"]

    # Build class→group mapping
    class_to_group = {}
    for group_name, members in raw.get("class_groups", {}).items():
        for cn in members:
            class_to_group[cn] = group_name

    # Load calibration
    calibration = {}
    if calibration_path is not None and calibration_path.exists():
        with open(calibration_path) as f:
            cal_raw = json.load(f)
        calibration = cal_raw.get("classes", {})
        # Override cal_factor from calibration file if present
        if "cal_factor" in cal_raw:
            ben = dict(ben)
            ben["cal_factor"] = cal_raw["cal_factor"]

    # Build tier lookup tables from tier_defs
    tier_defs_raw = raw.get("tiers", [])
    tier_name_to_id = {td["name"]: i for i, td in enumerate(tier_defs_raw)}
    tier_id_to_name = tuple(td["name"] for td in tier_defs_raw)
    tier_id_to_cola_key = tuple(
        td["cola_key"] for td in tier_defs_raw
    )
    fas_default = ben.get("fas_years_default", 5)
    tier_id_to_fas_years = tuple(
        td.get("fas_years", fas_default) for td in tier_defs_raw
    )

    config = PlanConfig(
        plan_name=raw["plan_name"],
        plan_description=raw.get("plan_description", ""),
        raw=raw,

        dr_current=eco["dr_current"],
        dr_new=eco["dr_new"],
        dr_old=eco.get("dr_old", eco["dr_current"]),
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

    for w in config.validate():
        log.info("[%s config] %s", config.plan_name, w)

    return config


def discover_plans(plans_dir: Optional[Path] = None) -> dict[str, Path]:
    """Return a mapping of {plan_name: plan_config.json path} for every plan
    directory under ``plans/`` that contains a ``config/plan_config.json``.

    The plan name is taken from the directory name (not from the JSON's own
    ``plan_name`` field) so the CLI can validate user input without parsing
    every config file. Callers that need the parsed config should call
    ``load_plan_config`` on the returned path.
    """
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
    """Load a plan config by plan name (debug/tests/scripts).

    Looks the plan up via ``discover_plans()`` — the same auto-discovery
    mechanism the CLI uses — so there is no per-plan convenience loader
    to maintain. A new plan works with no Python changes.

    Args:
        plan_name: The plan directory name under ``plans/`` (e.g. "frs",
            "txtrs"). Must match the directory name, not the
            ``plan_name`` field inside the config file.
        calibration_path: Optional explicit path to a ``calibration.json``.
            If not given, uses ``plans/<plan_name>/config/calibration.json``
            if it exists, otherwise ``None``.

    Raises:
        ValueError: if ``plan_name`` is not among the discovered plans.
    """
    plans = discover_plans()
    if plan_name not in plans:
        raise ValueError(
            f"Unknown plan {plan_name!r}. Available: {sorted(plans)}"
        )
    config_path = plans[plan_name]
    if calibration_path is None:
        cal_path = config_path.parent / "calibration.json"
        cal_path = cal_path if cal_path.exists() else None
    else:
        cal_path = calibration_path
    return load_plan_config(config_path, cal_path)


def load_frs_config(calibration_path: Optional[Path] = None) -> PlanConfig:
    """Convenience: load the FRS plan config (debug/tests only).

    Thin wrapper around :func:`load_plan_config_by_name`. Kept for
    backward compatibility with existing test files.
    """
    return load_plan_config_by_name("frs", calibration_path)


def load_txtrs_config(calibration_path: Optional[Path] = None) -> PlanConfig:
    """Convenience: load the TRS plan config (debug/tests only).

    Thin wrapper around :func:`load_plan_config_by_name`. Kept for
    backward compatibility with existing test files.
    """
    return load_plan_config_by_name("txtrs", calibration_path)
