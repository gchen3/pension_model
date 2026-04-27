"""Plan config schema and status constants."""

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

from pension_model.config_compat import (
    build_benefit_namespace,
    build_class_data_namespace,
    build_economic_namespace,
    build_funding_namespace,
    build_plan_design_namespace,
    build_ranges_namespace,
)
from pension_model.config_validation import validate_config, validate_data_files


NON_VESTED = 0
VESTED = 1
EARLY = 2
NORM = 3


@dataclass(frozen=True)
class PlanConfig:
    plan_name: str
    plan_description: str
    raw: dict
    dr_current: float
    dr_new: float
    dr_old: float
    baseline_dr_current: float
    payroll_growth: float
    pop_growth: float
    inflation: float
    model_return: float
    db_ee_cont_rate: float
    db_ee_interest_rate: float
    cal_factor: float
    retire_refund_ratio: float
    fas_years_default: int
    benefit_types: Tuple[str, ...]
    cola: dict
    funding_policy: str
    amo_method: str
    amo_period_new: int
    amo_pay_growth: float
    funding_lag: int
    amo_period_term: int
    amo_term_growth: float
    ava_smoothing: dict
    min_age: int
    max_age: int
    start_year: int
    new_year: int
    min_entry_year: int
    model_period: int
    max_yos: int
    classes: Tuple[str, ...]
    class_groups: Dict[str, List[str]]
    tier_defs: Tuple[dict, ...]
    benefit_mult_defs: dict
    plan_design_defs: dict
    valuation_inputs: Dict[str, dict]
    calibration: Dict[str, dict] = field(default_factory=dict)
    cash_balance: Optional[dict] = None
    reduce_tables: Optional[Dict[str, object]] = None
    _class_to_group: Dict[str, str] = field(default_factory=dict)
    _tier_name_to_id: Dict[str, int] = field(default_factory=dict)
    _tier_id_to_name: Tuple[str, ...] = ()
    _tier_id_to_cola_key: Tuple[str, ...] = ()
    _tier_id_to_fas_years: Tuple[int, ...] = ()

    @property
    def scenario_name(self) -> Optional[str]:
        return self.raw.get("_scenario_name")

    def resolve_data_dir(self) -> Path:
        data_cfg = self.raw.get("data", {})
        data_dir_str = data_cfg.get("data_dir", f"plans/{self.plan_name}/data")
        data_dir = Path(data_dir_str)
        if not data_dir.is_absolute():
            project_root = Path(__file__).parents[2]
            data_dir = project_root / data_dir
        return data_dir

    @property
    def entrant_salary_at_start_year(self) -> bool:
        return self.raw.get("modeling", {}).get("entrant_salary_at_start_year", False)

    @property
    def use_earliest_retire(self) -> bool:
        return self.raw.get("modeling", {}).get("use_earliest_retire", False)

    @property
    def term_vested_method(self) -> str:
        return self.raw.get("modeling", {}).get("term_vested_method", "growing_annuity")

    @property
    def male_mp_forward_shift(self) -> int:
        return self.raw.get("modeling", {}).get("male_mp_forward_shift", 0)

    @property
    def cola_proration_cutoff_year(self) -> Optional[int]:
        return self.cola.get("proration_cutoff_year")

    @property
    def plan_design_cutoff_year(self) -> Optional[int]:
        return self.raw.get("plan_design", {}).get("cutoff_year")

    @property
    def salary_growth_col_map(self) -> Dict[str, str]:
        return self.raw.get("salary_growth_col_map", {})

    @property
    def mortality_base_table(self) -> str:
        return self.raw.get("mortality", {}).get("base_table", "general")

    @property
    def base_table_map(self) -> Dict[str, str]:
        return self.raw.get("base_table_map", {})

    def get_base_table_type(self, class_name: str) -> str:
        return self.base_table_map.get(class_name, "general")

    @property
    def age_groups(self) -> Optional[List[dict]]:
        return self.raw.get("modeling", {}).get("age_groups")

    @property
    def has_drop(self) -> bool:
        return self.raw.get("funding", {}).get("has_drop", False)

    @property
    def drop_reference_class(self) -> Optional[str]:
        return self.raw.get("funding", {}).get("drop_reference_class")

    @property
    def statutory_rates(self) -> Optional[dict]:
        return self.raw.get("funding", {}).get("statutory_rates")

    @property
    def amo_period_current(self) -> Optional[int]:
        return self.raw.get("funding", {}).get("amo_period_current")

    @property
    def return_scen_col(self) -> str:
        return self.raw.get("economic", {}).get("return_scen", "assumption")

    @property
    def design_ratio_group_map(self) -> Dict[str, str]:
        return self.raw.get("design_ratio_group_map", {})

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

    @property
    def ranges(self) -> SimpleNamespace:
        return build_ranges_namespace(self)

    @property
    def economic(self) -> SimpleNamespace:
        return build_economic_namespace(self)

    @property
    def benefit(self) -> SimpleNamespace:
        return build_benefit_namespace(self)

    @property
    def funding(self) -> SimpleNamespace:
        return build_funding_namespace(self)

    @property
    def class_data(self) -> dict:
        return build_class_data_namespace(self)

    @property
    def plan_design(self) -> SimpleNamespace:
        return build_plan_design_namespace(self)

    def get_design_ratios(self, class_name: str) -> Dict[str, Tuple[float, float, float]]:
        group = self.design_ratio_group_map.get(class_name, self.class_group(class_name))
        ratios = self.plan_design_defs.get(group, self.plan_design_defs.get("default", {}))
        result = {}
        for bt in self.benefit_types:
            if bt == "db":
                before = ratios.get("before_2018", ratios.get("before_new_year", 1.0))
                after = ratios.get("after_2018", ratios.get("after_new_year", before))
                new = ratios.get("new", ratios.get("new_db", 1.0))
                result["db"] = (before, after, new)
            elif bt == "cb":
                result["cb"] = (
                    ratios.get("before_cb", 0.0),
                    ratios.get("after_cb", 0.0),
                    ratios.get("new_cb", 0.0),
                )
            elif bt == "dc":
                db_before, db_after, db_new = result.get("db", (1.0, 1.0, 1.0))
                cb_before, cb_after, cb_new = result.get("cb", (0.0, 0.0, 0.0))
                result["dc"] = (
                    1.0 - db_before - cb_before,
                    1.0 - db_after - cb_after,
                    1.0 - db_new - cb_new,
                )
        return result

    def class_group(self, class_name: str) -> str:
        return self._class_to_group.get(class_name, "default")

    def is_special(self, class_name: str) -> bool:
        return self.class_group(class_name) == "special_group"

    def get_fas_years(self, tier_name: str) -> int:
        tier_base = tier_name.split("_")[0]
        if len(tier_name.split("_")) > 1:
            tier_base = tier_name.split("_")[0] + "_" + tier_name.split("_")[1]
        for td in self.tier_defs:
            if td["name"] == tier_base:
                return td.get("fas_years", self.fas_years_default)
        return self.fas_years_default

    def get_class_inputs(self, class_name: str) -> dict:
        base = dict(self.valuation_inputs.get(class_name, {}))
        cal = self.calibration.get(class_name, {})
        base["nc_cal"] = cal.get("nc_cal", 1.0)
        base["pvfb_term_current"] = cal.get("pvfb_term_current", 0.0)
        return base

    def validate(self) -> list:
        return validate_config(self)

    def validate_data_files(self) -> list:
        return validate_data_files(self)
