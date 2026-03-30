"""
Model constants and parameters.

All R model constants consolidated into a single dataclass.
These are plan-specific inputs from the actuarial valuation report (ACFR)
and model assumptions. For generalization, a different plan would provide
different values through the same interface.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class EconomicAssumptions:
    """Economic and actuarial assumptions."""
    dr_current: float = 0.067        # Discount rate for current members
    dr_new: float = 0.067            # Discount rate for new-tier members
    dr_old: float = 0.068            # Previous year's discount rate
    payroll_growth: float = 0.0325   # Payroll growth assumption
    pop_growth: float = 0.0          # Active population growth
    inflation: float = 0.024         # Inflation assumption
    model_return: float = 0.067      # Investment return assumption


@dataclass(frozen=True)
class BenefitAssumptions:
    """Benefit-related assumptions."""
    db_ee_cont_rate: float = 0.03    # Employee contribution rate (3%)
    db_ee_interest_rate: float = 0.0 # Interest credited on EE contributions
    cal_factor: float = 0.9          # Global calibration factor for benefits
    retire_refund_ratio: float = 1.0 # Fraction of vested who choose annuity (vs refund)
    cola_tier_1_active: float = 0.03 # Tier 1 COLA for active/projected retirees
    cola_tier_1_active_constant: bool = False  # If True, COLA not prorated by pre-2011 YOS
    cola_tier_2_active: float = 0.0  # Tier 2 COLA
    cola_tier_3_active: float = 0.0  # Tier 3 COLA
    cola_current_retire: float = 0.03  # COLA for current retirees
    cola_current_retire_one: float = 0.0  # One-time COLA for current retirees
    one_time_cola: bool = False      # Whether one-time COLA applies


@dataclass(frozen=True)
class FundingAssumptions:
    """Funding policy assumptions."""
    funding_policy: str = "statutory"  # "statutory" or "ADC"
    amo_method: str = "level %"        # "level %" or "level $"
    amo_period_new: int = 20           # Years to amortize new UAAL
    amo_pay_growth: float = 0.0325     # Payroll growth for amortization
    funding_lag: int = 1               # Lag before contribution rate takes effect
    amo_period_term: int = 50          # Amortization period for remaining liability
    amo_term_growth: float = 0.03      # Growth rate for term amortization payments


@dataclass(frozen=True)
class ModelRange:
    """Age, year, and service ranges for the model."""
    min_age: int = 18
    max_age: int = 120
    start_year: int = 2022
    new_year: int = 2024              # Year when tier 3 begins
    min_entry_year: int = 1970        # Earliest entry year to model
    model_period: int = 30            # Projection horizon in years

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
    def max_yos(self) -> int:
        return 70  # R: yos_range_ <- 0:70

    @property
    def yos_range(self) -> range:
        return range(0, self.max_yos + 1)

    @property
    def max_year(self) -> int:
        return self.start_year + self.model_period + self.max_age - self.min_age


@dataclass(frozen=True)
class ClassACFRData:
    """ACFR financial data for a single membership class."""
    outflow: float                     # Benefit payments + other disbursements
    retiree_pop: float                 # Number of current annuitants
    total_active_member: float         # Total active members (DB + DC)
    pvfb_term_current: float           # Remaining accrued liability adjustment
    er_dc_cont_rate: float             # Employer DC contribution rate
    val_norm_cost: float               # Normal cost from valuation report


@dataclass(frozen=True)
class PlanDesignRatios:
    """DB vs DC plan design ratios."""
    # Fraction of members choosing DB plan, by entry period
    special_before_2018: float = 0.95
    non_special_before_2018: float = 0.75
    special_after_2018: float = 0.85
    non_special_after_2018: float = 0.25
    special_new: float = 0.75
    non_special_new: float = 0.25

    def get_ratios(self, is_special: bool) -> tuple:
        """Return (before_2018, after_2018, new) DB ratios."""
        if is_special:
            return (self.special_before_2018, self.special_after_2018, self.special_new)
        return (self.non_special_before_2018, self.non_special_after_2018, self.non_special_new)


@dataclass(frozen=True)
class ModelConstants:
    """All model constants consolidated. One instance per model run."""
    economic: EconomicAssumptions = field(default_factory=EconomicAssumptions)
    benefit: BenefitAssumptions = field(default_factory=BenefitAssumptions)
    funding: FundingAssumptions = field(default_factory=FundingAssumptions)
    ranges: ModelRange = field(default_factory=ModelRange)
    plan_design: PlanDesignRatios = field(default_factory=PlanDesignRatios)
    class_data: Dict[str, ClassACFRData] = field(default_factory=dict)

    @property
    def ben_payment_ratio(self) -> float:
        """Ratio of pension payments to total cash outflows (computed from ACFR)."""
        # These are system-wide ACFR line items
        pension_payment = 11_944_986_866
        contribution_refunds = 28_343_757
        disbursement_to_ip = 768_106_850
        admin_expense = 22_494_571
        return pension_payment / (pension_payment + contribution_refunds +
                                  disbursement_to_ip + admin_expense)


def frs_constants() -> ModelConstants:
    """Create ModelConstants with Florida FRS baseline values."""
    class_data = {
        "regular": ClassACFRData(
            outflow=8_967_096_000, retiree_pop=393_308,
            total_active_member=537_128, pvfb_term_current=6_591_924_964,
            er_dc_cont_rate=0.066, val_norm_cost=0.0896,
        ),
        "special": ClassACFRData(
            outflow=2_423_470_000, retiree_pop=41_696,
            total_active_member=72_925, pvfb_term_current=3_237_763_994,
            er_dc_cont_rate=0.1654, val_norm_cost=0.2013,
        ),
        "admin": ClassACFRData(
            outflow=8_090_000, retiree_pop=160,
            total_active_member=104, pvfb_term_current=-2_095_291,
            er_dc_cont_rate=0.0843, val_norm_cost=0.1457,
        ),
        "eco": ClassACFRData(
            outflow=9_442_000, retiree_pop=227,
            total_active_member=2_075, pvfb_term_current=27_604_397,
            er_dc_cont_rate=0.0994, val_norm_cost=0.1254,
        ),
        "eso": ClassACFRData(
            outflow=53_526_000, retiree_pop=1_446,
            total_active_member=2_075, pvfb_term_current=30_965_398,
            er_dc_cont_rate=0.1195, val_norm_cost=0.1463,
        ),
        "judges": ClassACFRData(
            outflow=105_844_000, retiree_pop=989,
            total_active_member=2_075, pvfb_term_current=101_107_976,
            er_dc_cont_rate=0.1405, val_norm_cost=0.1777,
        ),
        "senior_management": ClassACFRData(
            outflow=338_664_000, retiree_pop=5_828,
            total_active_member=7_610, pvfb_term_current=635_471_640,
            er_dc_cont_rate=0.0798, val_norm_cost=0.1086,
        ),
    }

    return ModelConstants(class_data=class_data)
