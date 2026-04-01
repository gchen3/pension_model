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
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import numpy as np


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
    sep_class_map: Dict[str, str]

    # Tiers (raw list of tier dicts from config — interpreted by evaluator)
    tier_defs: Tuple[dict, ...]

    # Benefit multipliers (raw from config)
    benefit_mult_defs: dict

    # Plan design ratios (raw from config)
    plan_design_defs: dict

    # Per-class ACFR data
    acfr_data: Dict[str, dict]

    # Calibration (per-class nc_cal and pvfb_term_current)
    calibration: Dict[str, dict] = field(default_factory=dict)

    # Cash balance parameters (optional, TRS-style plans)
    cash_balance: Optional[dict] = None

    # Precomputed: class→group mapping for fast lookup
    _class_to_group: Dict[str, str] = field(default_factory=dict)

    # --- Derived properties ---

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
        )

    @property
    def class_data(self) -> dict:
        """Dict of class_name → namespace with ACFR + calibration fields.

        Compatible with ModelConstants.class_data[cn].X access pattern.
        """
        result = {}
        for cn, acfr in self.acfr_data.items():
            cal = self.calibration.get(cn, {})
            result[cn] = SimpleNamespace(
                outflow=acfr["outflow"],
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

        For FRS: {"db": (0.75, 0.25, 0.25), "dc": (0.25, 0.75, 0.75)}
        For TRS: {"db": (1.0, 1.0, 1.0), "cb": (0.0, 0.0, 0.0)}
        """
        group = self.class_group(class_name)
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
        """Whether a class is in the special group (FRS concept)."""
        return self.class_group(class_name) == "special_group"

    def get_sep_class(self, class_name: str) -> str:
        """Get the separation rate class for a given class."""
        return self.sep_class_map.get(class_name, class_name)

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

    @property
    def ben_payment_ratio(self) -> float:
        """Computed from ACFR ben_payment_ratio_components if present."""
        bpr = self.raw.get("ben_payment_ratio_components")
        if bpr is None:
            return 1.0
        pp = bpr["pension_payment"]
        total = pp + bpr["contribution_refunds"] + bpr["disbursement_to_ip"] + bpr["admin_expense"]
        return pp / total

    def get_acfr(self, class_name: str) -> dict:
        """Return ACFR data for a class (with calibration applied)."""
        base = dict(self.acfr_data.get(class_name, {}))
        cal = self.calibration.get(class_name, {})
        base["nc_cal"] = cal.get("nc_cal", 1.0)
        base["pvfb_term_current"] = cal.get("pvfb_term_current", 0.0)
        return base


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
    """TRS-style grandfathering: check conditions as of cutoff_year."""
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

    # Simple NRA-based reduction (FRS style)
    if "nra" in reduction:
        nra_map = reduction["nra"]
        rate = reduction.get("rate_per_year", 0.05)
        if class_name == "special" and "special" in nra_map:
            nra = nra_map["special"]
        else:
            nra = nra_map.get("default", 65)
        return 1.0 - rate * (nra - dist_age)

    # Rule-based reduction (TRS style)
    if "rules" in reduction:
        reduce_tables = getattr(config, "_reduce_tables", None)
        for rule in reduction["rules"]:
            cond = rule.get("condition", {})
            # Check condition
            if not _check_reduce_condition(cond, dist_age, yos, entry_year, tier_name, config):
                continue
            formula = rule.get("formula", "linear")
            if formula == "linear":
                rate = rule.get("rate_per_year", 0.05)
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
        # GFT table indexed by (yos, age)
        row = table[table["yos"] == yos]
        if row.empty:
            row = table[table["yos"] <= yos].tail(1)
        if row.empty:
            return float("nan")
        # Find age column
        age_cols = [c for c in table.columns if c != "yos"]
        age_col = str(int(dist_age)) if str(int(dist_age)) in [str(c) for c in age_cols] else None
        if age_col is None:
            # Closest age
            int_cols = [int(float(c)) for c in age_cols if str(c).replace(".", "").isdigit()]
            if int_cols:
                closest = min(int_cols, key=lambda x: abs(x - dist_age))
                age_col = str(closest)
        if age_col is not None:
            val = row.iloc[0].get(int(age_col), row.iloc[0].get(float(age_col), float("nan")))
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
    """Default Reduced Others factors (TRS) when table not available."""
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
# Plan design ratio lookup
# ---------------------------------------------------------------------------

def get_plan_design_ratios(config: PlanConfig, class_name: str) -> Tuple[float, float, float]:
    """Return (before_2018_db, after_2018_db, new_db) plan design ratios.

    For FRS these differ by class group. For TRS-style plans, typically 1.0/1.0/1.0.
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

def load_plan_config(config_path: Path,
                     calibration_path: Optional[Path] = None) -> PlanConfig:
    """Load a PlanConfig from a JSON file.

    Args:
        config_path: Path to plan_config.json
        calibration_path: Optional path to calibration.json (overrides)
    """
    with open(config_path) as f:
        raw = json.load(f)

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
        sep_class_map=raw.get("sep_class_map", {}),

        tier_defs=tuple(raw.get("tiers", [])),
        benefit_mult_defs=raw.get("benefit_multipliers", {}),
        plan_design_defs=raw.get("plan_design", {}),

        acfr_data=raw.get("acfr_data", {}),
        calibration=calibration,

        _class_to_group=class_to_group,
    )

    return config


def load_frs_config(calibration_path: Optional[Path] = None) -> PlanConfig:
    """Convenience: load the FRS plan config with default paths."""
    base = Path(__file__).parents[2] / "configs" / "frs"
    config_path = base / "plan_config.json"
    if calibration_path is None:
        cal_path = base / "calibration.json"
    else:
        cal_path = calibration_path
    return load_plan_config(config_path, cal_path)


def load_txtrs_config(calibration_path: Optional[Path] = None) -> PlanConfig:
    """Convenience: load the Texas TRS plan config."""
    base = Path(__file__).parents[2] / "configs" / "txtrs"
    config_path = base / "plan_config.json"
    cal_path = calibration_path or (base / "calibration.json")
    return load_plan_config(config_path, cal_path if cal_path.exists() else None)
