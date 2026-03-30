"""
Plan Configuration Module

This module defines the PlanConfig dataclass and related configuration classes
for pension plan modeling. It consolidates all plan parameters in one place.

Key Design Principles:
- Immutable configuration using dataclasses
- Support for multiple tiers and membership classes
- FRS-specific default values
- Compatible with both legacy and new hire provisions
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

# Import types from types.py
from .types import MembershipClass, Tier, FundingPolicy, AmortizationMethod


@dataclass
class TierConfig:
    """Configuration for a single tier."""
    tier_name: str
    entry_year_start: int
    entry_year_end: Optional[int]

    # Benefit parameters
    benefit_multiplier: float  # e.g., 0.016 for 1.6%
    benefit_multiplier_grades: Optional[Dict[int, float]] = None  # YOS -> multiplier

    # Retirement eligibility
    normal_retirement_age: int = 62
    normal_retirement_yos: int = 6
    early_retirement_age: int = 55
    early_retirement_yos: int = 5
    early_retirement_reduction: float = 0.05  # 5% per year

    # COLA
    cola_rate: float = 0.03  # 3%
    cola_type: str = "fixed"  # "fixed" or "variable"

    # Vesting
    vesting_yos: int = 6

    # Employee contributions
    ee_contribution_rate: float = 0.03  # 3% of salary


@dataclass
class MembershipClassConfig:
    """Configuration for a membership class."""
    class_name: str
    tiers: Dict[str, TierConfig]

    # Class-specific parameters
    special_risk: bool = False
    judges: bool = False

    # Salary growth assumption
    salary_growth_rate: float = 0.045  # 4.5%

    # Population growth
    pop_growth_rate: float = 0.01  # 1%


@dataclass
class PlanConfig:
    """
    Master configuration for a pension plan.

    This dataclass contains all parameters needed to run the pension model,
    including actuarial assumptions, benefit formulas, and funding policies.
    """
    # Plan identification
    plan_name: str = "FRS"
    start_year: int = 2023
    model_period: int = 30

    # Discount rates
    dr_current: float = 0.067  # 6.7% for current members
    dr_new: float = 0.067  # 6.7% for new hires
    model_return: float = 0.067  # Expected return for funding

    # COLA rates
    cola_tier_1_active: float = 0.03  # 3% for Tier 1 actives
    cola_tier_1_retiree: float = 0.03  # 3% for Tier 1 retirees
    cola_current_retire: float = 0.03  # Current retiree COLA
    cola_new_retire: float = 0.02  # New retiree COLA (variable)

    # Salary growth
    salary_growth_rate: float = 0.045  # 4.5% aggregate
    payroll_growth: float = 0.035  # 3.5% payroll growth

    # Population growth rates by class
    pop_growth_rates: Dict[str, float] = field(default_factory=lambda: {
        'regular': 0.01,
        'special': 0.015,
        'admin': 0.005,
        'eco': 0.02,
        'eso': 0.02,
        'judges': 0.005,
        'senior_management': 0.005
    })

    # Plan design ratios (DB vs DC allocation)
    db_legacy_before_2018_ratio: float = 0.70  # 70% DB before 2018
    db_legacy_after_2018_ratio: float = 0.55  # 55% DB 2018-2022
    db_new_ratio: float = 0.50  # 50% DB for new hires
    new_hire_year: int = 2023  # Year when new hire provisions start

    # Funding policy
    funding_policy: FundingPolicy = FundingPolicy.STATUTORY
    amortization_method: AmortizationMethod = AmortizationMethod.LEVEL_PERCENT
    amortization_period_new: int = 20  # Years for new layers
    amortization_period_current: int = 25  # Years for current layers
    funding_lag: int = 1  # Years lag for contribution determination

    # Amortization payroll growth assumption
    amo_pay_growth: float = 0.035  # 3.5%

    # Age limits
    max_age: int = 110
    min_entry_age: int = 20
    max_entry_age: int = 70

    # Membership class configurations
    class_configs: Dict[str, MembershipClassConfig] = field(default_factory=dict)

    # Tier configurations (shared across classes)
    tier_configs: Dict[str, TierConfig] = field(default_factory=lambda: {
        'tier_1': TierConfig(
            tier_name='tier_1',
            entry_year_start=1900,
            entry_year_end=2010,
            benefit_multiplier=0.016,
            normal_retirement_age=62,
            normal_retirement_yos=6,
            early_retirement_age=55,
            early_retirement_yos=5,
            cola_rate=0.03,
            cola_type='fixed',
            vesting_yos=6,
            ee_contribution_rate=0.03
        ),
        'tier_2': TierConfig(
            tier_name='tier_2',
            entry_year_start=2011,
            entry_year_end=2022,
            benefit_multiplier=0.0165,
            benefit_multiplier_grades={6: 0.016, 7: 0.0162, 8: 0.0164, 9: 0.0166, 10: 0.0168},
            normal_retirement_age=60,
            normal_retirement_yos=8,
            early_retirement_age=55,
            early_retirement_yos=5,
            cola_rate=0.02,
            cola_type='variable',
            vesting_yos=8,
            ee_contribution_rate=0.03
        ),
        'tier_3': TierConfig(
            tier_name='tier_3',
            entry_year_start=2023,
            entry_year_end=None,
            benefit_multiplier=0.0165,
            normal_retirement_age=60,
            normal_retirement_yos=8,
            early_retirement_age=55,
            early_retirement_yos=5,
            cola_rate=0.02,
            cola_type='variable',
            vesting_yos=8,
            ee_contribution_rate=0.03
        )
    })

    # Initial values (for funding projection)
    initial_aal_legacy: float = 0.0
    initial_aal_new: float = 0.0
    initial_payroll: float = 0.0
    initial_nc_rate_db_legacy: float = 0.05  # 5% NC rate
    initial_nc_rate_db_new: float = 0.06  # 6% NC rate
    initial_ben_payment: float = 0.0
    initial_refund: float = 0.0

    # Asset values
    initial_ava_legacy: float = 0.0
    initial_ava_new: float = 0.0
    initial_mva_legacy: float = 0.0
    initial_mva_new: float = 0.0

    def get_tier(self, entry_year: int) -> str:
        """
        Determine tier based on entry year.

        Args:
            entry_year: Year of plan entry

        Returns:
            Tier identifier string
        """
        if entry_year <= 2010:
            return 'tier_1'
        elif entry_year <= 2022:
            return 'tier_2'
        else:
            return 'tier_3'

    def get_tier_config(self, tier_name: str) -> Optional[TierConfig]:
        """Get tier configuration by name."""
        return self.tier_configs.get(tier_name)

    def get_benefit_multiplier(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        yos: int,
        age: Optional[int] = None
    ) -> float:
        """
        Get benefit multiplier for a given class, tier, and YOS.

        Args:
            membership_class: Membership class
            tier: Tier identifier
            yos: Years of service
            age: Age (optional, for age-based rules)

        Returns:
            Benefit multiplier (e.g., 0.016 for 1.6%)
        """
        tier_config = self.tier_configs.get(tier.value)
        if tier_config is None:
            return 0.016  # Default

        # Check for graded multiplier
        if tier_config.benefit_multiplier_grades and yos in tier_config.benefit_multiplier_grades:
            return tier_config.benefit_multiplier_grades[yos]

        # Special handling for membership classes
        if membership_class == MembershipClass.SPECIAL:
            return 0.02  # 2.0% for Special Risk
        elif membership_class == MembershipClass.JUDGES:
            return 0.033  # 3.3% for Judges
        elif membership_class == MembershipClass.SENIOR_MANAGEMENT:
            return 0.02  # 2.0% for Senior Management

        return tier_config.benefit_multiplier

    def get_normal_retirement_age(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> tuple:
        """
        Get normal retirement age and YOS requirements.

        Returns:
            Tuple of (age, yos)
        """
        tier_config = self.tier_configs.get(tier.value)
        if tier_config is None:
            return (62, 6)  # Default

        # Special handling for membership classes
        if membership_class == MembershipClass.SPECIAL:
            return (55, 6)  # Special Risk: Age 55 or 6 YOS
        elif membership_class == MembershipClass.JUDGES:
            return (60, 10)  # Judges: Age 60 or 10 YOS

        return (tier_config.normal_retirement_age, tier_config.normal_retirement_yos)

    def get_early_retirement_age(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> tuple:
        """
        Get early retirement age and YOS requirements.

        Returns:
            Tuple of (age, yos)
        """
        tier_config = self.tier_configs.get(tier.value)
        if tier_config is None:
            return (55, 5)  # Default

        return (tier_config.early_retirement_age, tier_config.early_retirement_yos)

    def get_cola_rate(
        self,
        tier: Tier,
        is_retired: bool = False
    ) -> float:
        """
        Get COLA rate for a tier.

        Args:
            tier: Tier identifier
            is_retired: Whether member is retired

        Returns:
            COLA rate (e.g., 0.03 for 3%)
        """
        tier_config = self.tier_configs.get(tier.value)
        if tier_config is None:
            return 0.03  # Default

        return tier_config.cola_rate

    def get_vesting_yos(self, tier: Tier) -> int:
        """Get vesting years of service requirement."""
        tier_config = self.tier_configs.get(tier.value)
        if tier_config is None:
            return 6  # Default
        return tier_config.vesting_yos

    def get_pop_growth_rate(self, membership_class: MembershipClass) -> float:
        """Get population growth rate for a membership class."""
        return self.pop_growth_rates.get(membership_class.value, 0.01)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization."""
        return {
            'plan_name': self.plan_name,
            'start_year': self.start_year,
            'model_period': self.model_period,
            'dr_current': self.dr_current,
            'dr_new': self.dr_new,
            'model_return': self.model_return,
            'cola_tier_1_active': self.cola_tier_1_active,
            'cola_tier_1_retiree': self.cola_tier_1_retiree,
            'cola_current_retire': self.cola_current_retire,
            'cola_new_retire': self.cola_new_retire,
            'salary_growth_rate': self.salary_growth_rate,
            'payroll_growth': self.payroll_growth,
            'pop_growth_rates': self.pop_growth_rates,
            'db_legacy_before_2018_ratio': self.db_legacy_before_2018_ratio,
            'db_legacy_after_2018_ratio': self.db_legacy_after_2018_ratio,
            'db_new_ratio': self.db_new_ratio,
            'new_hire_year': self.new_hire_year,
            'funding_policy': self.funding_policy.value,
            'amortization_method': self.amortization_method.value,
            'amortization_period_new': self.amortization_period_new,
            'amortization_period_current': self.amortization_period_current,
            'funding_lag': self.funding_lag,
            'amo_pay_growth': self.amo_pay_growth,
            'max_age': self.max_age,
            'min_entry_age': self.min_entry_age,
            'max_entry_age': self.max_entry_age,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlanConfig':
        """Create config from dictionary."""
        # Handle enum conversions
        if 'funding_policy' in data and isinstance(data['funding_policy'], str):
            data['funding_policy'] = FundingPolicy(data['funding_policy'])
        if 'amortization_method' in data and isinstance(data['amortization_method'], str):
            data['amortization_method'] = AmortizationMethod(data['amortization_method'])

        return cls(**data)


def create_frs_config() -> PlanConfig:
    """
    Create a PlanConfig with FRS-specific default values.

    Returns:
        PlanConfig configured for Florida Retirement System
    """
    return PlanConfig(
        plan_name="FRS",
        start_year=2023,
        model_period=30,
        dr_current=0.067,
        dr_new=0.067,
        model_return=0.067,
        cola_tier_1_active=0.03,
        cola_tier_1_retiree=0.03,
        cola_current_retire=0.03,
        cola_new_retire=0.02,
        salary_growth_rate=0.045,
        payroll_growth=0.035,
        pop_growth_rates={
            'regular': 0.01,
            'special': 0.015,
            'admin': 0.005,
            'eco': 0.02,
            'eso': 0.02,
            'judges': 0.005,
            'senior_management': 0.005
        },
        db_legacy_before_2018_ratio=0.70,
        db_legacy_after_2018_ratio=0.55,
        db_new_ratio=0.50,
        new_hire_year=2023,
        funding_policy=FundingPolicy.STATUTORY,
        amortization_method=AmortizationMethod.LEVEL_PERCENT,
        amortization_period_new=20,
        amortization_period_current=25,
        funding_lag=1,
        amo_pay_growth=0.035,
        max_age=110,
        min_entry_age=20,
        max_entry_age=70
    )
