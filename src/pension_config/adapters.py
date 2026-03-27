"""
Plan Adapter Framework

This module defines the interface for plan-specific adapters that allow
the general pension model to work with different pension plans.

Each plan adapter implements the PlanAdapter protocol and provides
plan-specific business rules, benefit formulas, and data transformations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable, Any, Dict, List, Optional

from .plan import MembershipClass, Tier


class FundingPolicy(str, Enum):
    """Funding policy types"""
    ADC = "adc"  # Aggregate Deductible Contribution
    EAN = "ean"  # Entry Age Normal
    PUC = "puc"  # Projected Unit Credit


class AmortizationMethod(str, Enum):
    """Amortization methods"""
    LEVEL_DOLLAR = "level_dollar"
    LEVEL_PERCENT = "level_percent"


@runtime_checkable
class PlanAdapter(Protocol):
    """
    Protocol defining the interface for plan-specific adapters.

    Each plan must implement these methods to provide plan-specific
    business rules, benefit formulas, and data transformations.
    """

    @property
    def plan_name(self) -> str:
        """Return the plan name (e.g., 'FRS', 'CalPERS')"""
        ...

    @property
    def membership_classes(self) -> List[MembershipClass]:
        """Return list of membership classes for this plan"""
        ...

    @property
    def tiers(self) -> List[Tier]:
        """Return list of tiers for this plan"""
        ...

    def get_benefit_multiplier(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        years_of_service: float,
        age: Optional[float] = None
    ) -> float:
        """
        Get the benefit multiplier for a given class, tier, and YOS.

        Args:
            membership_class: The membership class
            tier: The tier (tier_1, tier_2, tier_3)
            years_of_service: Years of service
            age: Age (if needed for tier determination)

        Returns:
            Benefit multiplier (e.g., 0.0165 for 1.65% per YOS)
        """
        ...

    def get_normal_retirement_age(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> tuple[float, float]:
        """
        Get normal retirement age (age and YOS) for a class and tier.

        Returns:
            Tuple of (age, years_of_service)
        """
        ...

    def get_early_retirement_age(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> tuple[float, float]:
        """
        Get early retirement age (age and YOS) for a class and tier.

        Returns:
            Tuple of (age, years_of_service)
        """
        ...

    def get_early_retirement_factor(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        current_age: float,
        current_yos: float,
        normal_ret_age: float,
        normal_ret_yos: float
    ) -> float:
        """
        Calculate early retirement reduction factor.

        Args:
            membership_class: The membership class
            tier: The tier
            current_age: Current age
            current_yos: Current years of service
            normal_ret_age: Normal retirement age
            normal_ret_yos: Normal retirement years of service

        Returns:
            Reduction factor (e.g., 0.95 for 5% reduction)
        """
        ...

    def get_cola_rate(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        is_retired: bool,
        year: int
    ) -> float:
        """
        Get COLA rate for a given class, tier, and year.

        Args:
            membership_class: The membership class
            tier: The tier
            is_retired: Whether the member is retired
            year: The projection year

        Returns:
            COLA rate (e.g., 0.03 for 3%)
        """
        ...

    def get_salary_growth_rate(
        self,
        membership_class: MembershipClass,
        years_of_service: float
    ) -> float:
        """
        Get salary growth rate for a given class and YOS.

        Args:
            membership_class: The membership class
            years_of_service: Years of service

        Returns:
            Salary growth rate (e.g., 0.045 for 4.5%)
        """
        ...

    def get_withdrawal_rate(
        self,
        membership_class: MembershipClass,
        age: float,
        years_of_service: float,
        gender: Optional[str] = None
    ) -> float:
        """
        Get withdrawal/termination rate for a given class, age, and YOS.

        Args:
            membership_class: The membership class
            age: Current age
            years_of_service: Years of service
            gender: Gender (if needed)

        Returns:
            Withdrawal rate (e.g., 0.05 for 5%)
        """
        ...

    def get_mortality_rate(
        self,
        membership_class: MembershipClass,
        age: float,
        gender: str,
        is_retired: bool = False
    ) -> float:
        """
        Get mortality rate (qx) for a given class, age, and gender.

        Args:
            membership_class: The membership class
            age: Current age
            gender: Gender ('M' or 'F')
            is_retired: Whether the member is retired (may use different table)

        Returns:
            Mortality rate (qx)
        """
        ...

    def determine_tier(
        self,
        membership_class: MembershipClass,
        entry_year: int,
        distribution_year: Optional[int] = None
    ) -> Tier:
        """
        Determine which tier a member belongs to based on entry year.

        Args:
            membership_class: The membership class
            entry_year: Year of entry into the plan
            distribution_year: Year of distribution (if applicable)

        Returns:
            The tier (tier_1, tier_2, or tier_3)
        """
        ...

    def get_db_dc_ratio(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        entry_year: int
    ) -> tuple[float, float]:
        """
        Get the DB/DC split ratio for a given class, tier, and entry year.

        Returns:
            Tuple of (db_ratio, dc_ratio) - both should sum to 1.0
        """
        ...

    def get_retirement_benefit_formula(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> str:
        """
        Get a description of the retirement benefit formula.

        Returns:
            String describing the formula (e.g., "1.65% x YOS x Final Average Salary")
        """
        ...

    def validate_data_requirements(
        self,
        data: Dict[str, Any]
    ) -> List[str]:
        """
        Validate that all required data for this plan is present.

        Args:
            data: Dictionary of loaded data tables

        Returns:
            List of validation errors (empty if all valid)
        """
        ...


class BasePlanAdapter(ABC):
    """
    Base class for plan adapters with common functionality.

    Subclasses should override the abstract methods to provide
    plan-specific implementations.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the adapter with plan-specific configuration.

        Args:
            config: Dictionary containing plan configuration
        """
        self.config = config

    @property
    @abstractmethod
    def plan_name(self) -> str:
        """Return the plan name"""
        pass

    @property
    @abstractmethod
    def membership_classes(self) -> List[MembershipClass]:
        """Return list of membership classes"""
        pass

    @property
    @abstractmethod
    def tiers(self) -> List[Tier]:
        """Return list of tiers"""
        pass

    # Default implementations for some methods
    def get_early_retirement_factor(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        current_age: float,
        current_yos: float,
        normal_ret_age: float,
        normal_ret_yos: float
    ) -> float:
        """
        Default early retirement factor calculation (5% per year early).

        Subclasses can override for different formulas.
        """
        # Calculate months early from age and YOS
        months_early_age = max(0, (normal_ret_age - current_age) * 12)
        months_early_yos = max(0, (normal_ret_yos - current_yos) * 12)

        # Use the greater of the two
        months_early = max(months_early_age, months_early_yos)

        # 5% reduction per year early (0.4167% per month)
        reduction = min(0.50, months_early * 0.004167)

        return 1.0 - reduction

    def validate_data_requirements(
        self,
        data: Dict[str, Any]
    ) -> List[str]:
        """
        Default data validation - checks for common required tables.

        Subclasses can override for plan-specific requirements.
        """
        errors = []

        required_tables = [
            'salary_growth',
            'mortality',
            'withdrawal_rates',
            'retirement_eligibility',
            'benefit_rules'
        ]

        for table in required_tables:
            if table not in data:
                errors.append(f"Missing required table: {table}")

        return errors


@dataclass
class PlanRegistry:
    """
    Registry for available plan adapters.

    This allows the model to dynamically load plan adapters
    by plan name.
    """

    _adapters: Dict[str, PlanAdapter] = {}

    @classmethod
    def register(cls, adapter: PlanAdapter) -> None:
        """Register a plan adapter"""
        cls._adapters[adapter.plan_name] = adapter

    @classmethod
    def get(cls, plan_name: str) -> Optional[PlanAdapter]:
        """Get a plan adapter by name"""
        return cls._adapters.get(plan_name)

    @classmethod
    def list_plans(cls) -> List[str]:
        """List all registered plan names"""
        return list(cls._adapters.keys())
