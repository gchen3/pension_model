"""
Benefit Calculation Module

Calculates pension benefits, normal costs, accrued liabilities,
present value of future benefits (PVFB), and present value of future salaries (PVFS).

Key Design Principles:
- Stream year-by-year to avoid keeping all years in memory
- Use long format for core data (one row = one entity)
- Pure functions for calculation logic
- Use plan adapter for plan-specific business rules
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from pension_config.plan import MembershipClass, Tier
from pension_config.adapters import PlanAdapter
from pension_data.schemas import (
    BenefitValuation,
    MortalityRate,
    SalaryGrowthRate,
    RetirementEligibility,
)

from pension_tools.financial import (
    present_value,
    present_value_series,
    discount_factor
)
from pension_tools.salary import (
    cumulative_salary_growth,
    projected_salary
)
# Note: complement_of_survival not yet implemented in mortality.py
# Using inline calculation for now
# Note: Some retirement functions not yet implemented
# from pension_tools.retirement import (
#     is_normal_retirement_eligible,
#     is_early_retirement_eligible,
#     early_retirement_factor
# )
# Note: pension_tools.benefit functions not imported to avoid circular dependencies
# Calculations done inline in BenefitCalculator class
# from pension_tools.benefit import (
#     normal_cost,
#     accrued_liability,
#     pvfb,
#     pvfs
# )


@dataclass
class BenefitCalculation:
    """Result of a benefit calculation for a single member."""
    entry_age: int
    entry_year: int
    age: int
    yos: int
    salary: float
    benefit: float
    normal_cost: float
    accrued_liability: float
    pvfb: float
    pvfs: float
    annuity_factor: float
    tier: Tier


class BenefitCalculator:
    """
    Calculates pension benefits and related actuarial values.

    This module handles:
    - Benefit calculations (normal, early, vested)
    - Normal cost and accrued liability
    - Present value of future benefits (PVFB)
    - Present value of future salaries (PVFS)
    - Annuity factors

    Uses PlanAdapter for plan-specific business rules.
    """

    def __init__(self, adapter: PlanAdapter):
        self.adapter = adapter
        self.start_year = adapter.config.get('start_year', 2023)
        self.model_period = adapter.config.get('model_period', 30)
        self.max_age = adapter.config.get('max_age', 110)

    def calculate_benefit(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        salary: float,
        yos: int,
        age: int
    ) -> float:
        """
        Calculate annual pension benefit.

        Args:
            membership_class: Membership class
            tier: Tier identifier
            salary: Final average salary
            yos: Years of service
            age: Age at retirement

        Returns:
            Annual benefit amount
        """
        # Get benefit multiplier from adapter
        multiplier = self.adapter.get_benefit_multiplier(
            membership_class, tier, yos, age
        )

        base_benefit = multiplier * yos * salary

        # Apply early retirement reduction if applicable
        if tier.value.startswith('tier_1_early') or tier.value.startswith('tier_2_early') or tier.value.startswith('tier_3_early'):
            # Get normal retirement age from adapter
            normal_ret_age, normal_ret_yos = self.adapter.get_normal_retirement_age(
                membership_class, tier
            )

            # Calculate early retirement factor
            reduction = early_retirement_factor(age, yos, normal_ret_age, normal_ret_yos)
            base_benefit *= (1 - reduction)

        return base_benefit

    def calculate_annuity_factor(
        self,
        age: int,
        year: int,
        dist_age: int,
        dr: float,
        mort_table: pd.DataFrame,
        cola_rate: float
    ) -> float:
        """
        Calculate annuity factor for benefit payments.

        Args:
            age: Current age
            year: Current year
            dist_age: Age at distribution (retirement)
            dr: Discount rate
            mort_table: Mortality rate table
            cola_rate: COLA rate for retirees

        Returns:
            Annuity factor
        """
        # Number of years from dist_age to max_age
        years_to_max = self.max_age - dist_age

        if years_to_max <= 0:
            return 0.0

        # Create array of ages from dist_age to max_age
        ages = np.arange(dist_age, self.max_age + 1)
        years = np.arange(len(ages))

        # Get mortality rates for each age
        # Mortality tables use 'dist_age' and 'dist_year' columns
        age_col = 'dist_age' if 'dist_age' in mort_table.columns else 'age'
        year_col = 'dist_year' if 'dist_year' in mort_table.columns else 'year'

        mort_rates = []
        for i, a in enumerate(ages):
            # Find mortality rate for this age and year
            dist_year = year + i
            match = mort_table[
                (mort_table[age_col] == a) &
                (mort_table[year_col] == dist_year)
            ]
            if len(match) > 0:
                mort_rates.append(match['mort_final'].iloc[0])
            else:
                mort_rates.append(0.0)

        mort_rates = np.array(mort_rates)

        # Calculate survival probability for each year
        # Survive to age t = product of (1 - qx) for all previous ages
        surv_prob = np.cumprod(1 - mort_rates)

        # Calculate discount factors with COLA
        # Payment at year t is discounted by (1 + dr)^t and grows by (1 + cola)^t
        discount_factors = np.array([
            (1 / ((1 + dr) ** t)) * ((1 + cola_rate) ** t)
            for t in years
        ])

        # Annuity factor = sum of survival * discount
        annuity = np.sum(surv_prob * discount_factors)

        return annuity

    def calculate_pvfb(
        self,
        benefit: float,
        entry_age: int,
        entry_year: int,
        current_age: int,
        current_year: int,
        dr: float,
        mort_table: pd.DataFrame,
        cola_rate: float
    ) -> float:
        """
        Calculate Present Value of Future Benefits (PVFB).

        Args:
            benefit: Annual benefit amount
            entry_age: Age at entry
            entry_year: Year of entry
            current_age: Current age
            current_year: Current year
            dr: Discount rate
            mort_table: Mortality rate table
            cola_rate: COLA rate

        Returns:
            Present value of future benefits
        """
        # Years from current age to retirement age
        # For simplicity, assume retirement at max_age
        years_to_retirement = self.max_age - current_age

        if years_to_retirement <= 0:
            return 0.0

        # Calculate annuity factor at retirement
        annuity = self.calculate_annuity_factor(
            current_age, current_year, self.max_age, dr, mort_table, cola_rate
        )

        # Calculate survival probability from current age to retirement
        yos = current_age - entry_age
        years = np.arange(years_to_retirement)

        # Get mortality rates
        mort_rates = []
        for i, t in enumerate(years):
            age = current_age + t
            year = current_year + t
            match = mort_table[
                (mort_table['entry_age'] == entry_age) &
                (mort_table['age'] == age) &
                (mort_table['year'] == year) &
                (mort_table['yos'] == yos + t)
            ]
            if len(match) > 0:
                mort_rates.append(match['mort_final'].iloc[0])
            else:
                mort_rates.append(0.0)

        mort_rates = np.array(mort_rates)

        # Survival to retirement = product of (1 - qx) for all previous ages
        surv_to_retirement = np.prod(1 - mort_rates)

        # Discount to present
        discount = 1 / ((1 + dr) ** years_to_retirement)

        # PVFB = Benefit * Annuity * Survival * Discount
        return benefit * annuity * surv_to_retirement * discount

    def calculate_pvfs(
        self,
        salary: float,
        entry_age: int,
        current_age: int,
        current_year: int,
        salary_growth_table: pd.DataFrame,
        dr: float
    ) -> float:
        """
        Calculate Present Value of Future Salaries (PVFS).

        Args:
            salary: Current salary
            entry_age: Age at entry
            current_age: Current age
            current_year: Current year
            salary_growth_table: Salary growth rate table
            dr: Discount rate

        Returns:
            Present value of future salaries
        """
        # Years to retirement
        years_to_retirement = self.max_age - current_age

        if years_to_retirement <= 0:
            return 0.0

        # Get salary growth rates
        growth_rates = []
        for t in range(years_to_retirement):
            age = current_age + t
            yos = age - entry_age
            match = salary_growth_table[
                (salary_growth_table['yos'] == yos)
            ]
            if len(match) > 0:
                growth_rates.append(match['salary_increase'].iloc[0])
            else:
                growth_rates.append(0.0)

        growth_rates = np.array(growth_rates)

        # Calculate cumulative growth
        cum_growth = np.cumprod(1 + growth_rates)

        # Projected salaries
        projected_salaries = salary * cum_growth

        # Discount factors
        discount_factors = np.array([
            1 / ((1 + dr) ** t) for t in range(years_to_retirement)
        ])

        # PVFS = sum of (projected salary * discount)
        return np.sum(projected_salaries * discount_factors)

    def calculate_normal_cost(
        self,
        benefit: float,
        pvfb: float,
        pvfs: float
    ) -> float:
        """
        Calculate Normal Cost (NC).

        Args:
            benefit: Annual benefit
            pvfb: Present value of future benefits
            pvfs: Present value of future salaries

        Returns:
            Normal cost rate
        """
        if pvfs == 0:
            return 0.0

        # NC = PVFB / PVFS * Salary
        # Or as a rate: NC_rate = PVFB / PVFS
        return pvfb / pvfs

    def calculate_accrued_liability(
        self,
        benefit: float,
        entry_age: int,
        entry_year: int,
        current_age: int,
        current_year: int,
        dr: float,
        mort_table: pd.DataFrame,
        cola_rate: float
    ) -> float:
        """
        Calculate Accrued Liability (AL).

        Args:
            benefit: Annual benefit
            entry_age: Age at entry
            entry_year: Year of plan entry
            current_age: Current age
            current_year: Current year
            dr: Discount rate
            mort_table: Mortality rate table
            cola_rate: COLA rate

        Returns:
            Accrued liability
        """
        # Calculate PVFB at current age
        pvfb_current = self.calculate_pvfb(
            benefit, entry_age, entry_year, current_age, current_year,
            dr, mort_table, cola_rate
        )

        # Calculate PVFB at entry age
        pvfb_entry = self.calculate_pvfb(
            benefit, entry_age, entry_year, entry_age, entry_year,
            dr, mort_table, cola_rate
        )

        # AL = PVFB_current - PVFB_entry * (1 - accrued_fraction)
        # For simplicity, use proportional accrual
        yos = current_age - entry_age
        total_yos = self.max_age - entry_age
        accrued_fraction = yos / total_yos if total_yos > 0 else 0

        return pvfb_current * accrued_fraction

    def calculate_benefit_for_member(
        self,
        membership_class: MembershipClass,
        entry_age: int,
        entry_year: int,
        age: int,
        salary: float,
        dr: float,
        mort_table: pd.DataFrame,
        salary_growth_table: pd.DataFrame,
        cola_rate_active: float,
        cola_rate_retire: float
    ) -> BenefitCalculation:
        """
        Calculate all benefit values for a single member.

        Args:
            membership_class: Membership class
            entry_age: Age at entry
            entry_year: Year of entry
            age: Current age
            salary: Current salary
            dr: Discount rate
            mort_table: Mortality rate table
            salary_growth_table: Salary growth rate table
            cola_rate_active: COLA rate for active members
            cola_rate_retire: COLA rate for retirees

        Returns:
            BenefitCalculation with all values
        """
        yos = age - entry_age
        current_year = entry_year + yos

        # Determine tier using adapter
        tier = self.adapter.determine_tier(membership_class, entry_year)

        # Calculate benefit
        benefit = self.calculate_benefit(
            membership_class, tier, salary, yos, age
        )

        # Calculate annuity factor
        annuity = self.calculate_annuity_factor(
            age, current_year, age, dr, mort_table, cola_rate_retire
        )

        # Calculate PVFB
        pvfb_val = self.calculate_pvfb(
            benefit, entry_age, entry_year, age, current_year,
            dr, mort_table, cola_rate_retire
        )

        # Calculate PVFS
        pvfs_val = self.calculate_pvfs(
            salary, entry_age, age, current_year, salary_growth_table, dr
        )

        # Calculate normal cost
        nc = self.calculate_normal_cost(benefit, pvfb_val, pvfs_val)

        # Calculate accrued liability
        al = self.calculate_accrued_liability(
            benefit, entry_age, age, current_year, dr, mort_table, cola_rate_retire
        )

        return BenefitCalculation(
            entry_age=entry_age,
            entry_year=entry_year,
            age=age,
            yos=yos,
            salary=salary,
            benefit=benefit,
            normal_cost=nc,
            accrued_liability=al,
            pvfb=pvfb_val,
            pvfs=pvfs_val,
            annuity_factor=annuity,
            tier=tier
        )

    def calculate_benefit_table(
        self,
        config: Dict[str, any],
        class_name: MembershipClass,
        salary_headcount: pd.DataFrame,
        mort_table: pd.DataFrame,
        salary_growth_table: pd.DataFrame,
        dr_current: float,
        dr_new: float,
        cola_rate_active: float,
        cola_rate_retire: float
    ) -> pd.DataFrame:
        """
        Calculate benefit table for all members in a class.

        Args:
            config: Plan configuration
            class_name: Membership class
            salary_headcount: Salary/headcount data
            mort_table: Mortality rate table
            salary_growth_table: Salary growth rate table
            dr_current: Current discount rate
            dr_new: New discount rate
            cola_rate_active: COLA rate for active members
            cola_rate_retire: COLA rate for retirees

        Returns:
            DataFrame with benefit calculations for all members
        """
        results = []

        for _, row in salary_headcount.iterrows():
            entry_age = row['entry_age']
            entry_year = row['entry_year']
            age = row['age']
            salary = row['entry_salary'] * row.get('cumprod_salary_increase', 1.0)

            # Use appropriate discount rate based on entry year
            dr = dr_new if entry_year >= config.get('new_hire_year', 2018) else dr_current

            calc = self.calculate_benefit_for_member(
                class_name, entry_age, entry_year, age, salary, dr,
                mort_table, salary_growth_table, cola_rate_active, cola_rate_retire
            )

            results.append({
                'entry_age': calc.entry_age,
                'entry_year': calc.entry_year,
                'age': calc.age,
                'yos': calc.yos,
                'salary': calc.salary,
                'benefit': calc.benefit,
                'normal_cost': calc.normal_cost,
                'accrued_liability': calc.accrued_liability,
                'pvfb': calc.pvfb,
                'pvfs': calc.pvfs,
                'annuity_factor': calc.annuity_factor,
                'tier': calc.tier.value
            })

        return pd.DataFrame(results)


def calculate_benefit_table(
    config: 'PlanConfig',
    class_name: MembershipClass,
    salary_headcount: pd.DataFrame,
    mort_table: pd.DataFrame,
    salary_growth_table: pd.DataFrame,
    dr_current: float,
    dr_new: float,
    cola_rate_active: float,
    cola_rate_retire: float
) -> pd.DataFrame:
    """
    Convenience function to calculate benefit table.

    Args:
        config: Plan configuration
        class_name: Membership class
        salary_headcount: Salary/headcount data
        mort_table: Mortality rate table
        salary_growth_table: Salary growth rate table
        dr_current: Current discount rate
        dr_new: New discount rate
        cola_rate_active: COLA rate for active members
        cola_rate_retire: COLA rate for retirees

    Returns:
        DataFrame with benefit calculations
    """
    from pension_config.adapters import PlanAdapter
    from pension_config.frs_adapter import FRSAdapter

    # Create adapter based on config
    adapter = FRSAdapter(config)

    calculator = BenefitCalculator(adapter)
    return calculator.calculate_benefit_table(
        {'new_hire_year': config.new_hire_year},
        class_name,
        salary_headcount,
        mort_table,
        salary_growth_table,
        dr_current,
        dr_new,
        cola_rate_active,
        cola_rate_retire
    )
