"""
Actuarial calculations module for pension modeling.

This module implements core actuarial calculations following Winklevoss methodology:
- Present Value of Future Benefits (PVFB)
- Present Value of Future Salary (PVFS)
- Normal Cost (NC)
- Accrued Actuarial Liability (AAL) using Entry Age Normal (EAN) method

Key formulas:
- Survival probability: n_p_x = product of p_x from age x to x+n-1
- Discount factor: v^n = 1/(1+i)^n
- PVFB = sum of (benefit * survival_prob * discount_factor)
- NC = PVFB increase from one year of service
- AAL = PVFB * (YOS / total service)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd
import numpy as np
from pathlib import Path


@dataclass
class ActuarialAssumptions:
    """Actuarial assumptions for calculations."""
    discount_rate: float  # i = 0.067 for 6.7%
    salary_growth: float  # Salary growth rate
    cola_rate: float  # Cost of living adjustment
    benefit_multiplier: float  # e.g., 0.016 for 1.6%
    retirement_age: int  # Normal retirement age
    max_age: int = 120  # Maximum age for calculations


class SurvivalCalculator:
    """
    Calculate survival probabilities from mortality tables.

    Uses the standard actuarial notation:
    - q_x = probability of death within one year
    - p_x = 1 - q_x = probability of surviving one year
    - n_p_x = probability of surviving n years from age x
    """

    def __init__(self, mort_table: pd.DataFrame):
        """
        Initialize with a mortality table.

        Args:
            mort_table: DataFrame with mortality rates
                       Must have columns: entry_age, dist_age, mort_final
        """
        self.mort_table = mort_table
        self._cache = {}  # Cache for survival probabilities

    def get_qx(self, entry_age: int, age: int) -> float:
        """
        Get mortality rate q_x for a given age.

        Args:
            entry_age: Age at plan entry
            age: Current age

        Returns:
            Mortality rate (probability of death within one year)
        """
        matches = self.mort_table[
            (self.mort_table['entry_age'] == entry_age) &
            (self.mort_table['dist_age'] == age)
        ]

        if len(matches) > 0:
            return matches['mort_final'].iloc[0]

        # Default mortality rates by age (RP-2014 approximate)
        if age < 50:
            return 0.001
        elif age < 60:
            return 0.003
        elif age < 70:
            return 0.01
        elif age < 80:
            return 0.03
        elif age < 90:
            return 0.10
        else:
            return 0.25

    def get_px(self, entry_age: int, age: int) -> float:
        """
        Get one-year survival probability p_x.

        Args:
            entry_age: Age at plan entry
            age: Current age

        Returns:
            Probability of surviving one year
        """
        return 1 - self.get_qx(entry_age, age)

    def get_npx(self, entry_age: int, from_age: int, n: int) -> float:
        """
        Calculate n-year survival probability from age x.

        Formula: n_p_x = p_x * p_(x+1) * ... * p_(x+n-1)

        Args:
            entry_age: Age at plan entry
            from_age: Starting age
            n: Number of years

        Returns:
            Probability of surviving n years
        """
        cache_key = (entry_age, from_age, n)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if n <= 0:
            return 1.0

        if n == 1:
            return self.get_px(entry_age, from_age)

        # Recursive calculation
        survival = 1.0
        for age in range(from_age, from_age + n):
            survival *= self.get_px(entry_age, age)

        self._cache[cache_key] = survival
        return survival

    def get_ex(self, entry_age: int, from_age: int, max_age: int = 120) -> float:
        """
        Calculate curtate life expectancy from age x.

        Formula: e_x = sum of (k_p_x for k = 1 to infinity)

        Args:
            entry_age: Age at plan entry
            from_age: Starting age
            max_age: Maximum age for calculation

        Returns:
            Curtate life expectancy in years
        """
        expectancy = 0.0
        for k in range(1, max_age - from_age + 1):
            expectancy += self.get_npx(entry_age, from_age, k)
        return expectancy


class ActuarialCalculator:
    """
    Calculate actuarial present values for pension benefits.

    Implements the Entry Age Normal (EAN) cost method:
    - PVFB = Present Value of Future Benefits
    - PVFS = Present Value of Future Salary
    - NC = Normal Cost (PVFB increase per year of service)
    - AAL = Accrued Actuarial Liability
    """

    def __init__(
        self,
        assumptions: ActuarialAssumptions,
        mort_table: pd.DataFrame
    ):
        """
        Initialize the actuarial calculator.

        Args:
            assumptions: Actuarial assumptions
            mort_table: Mortality rate table
        """
        self.assumptions = assumptions
        self.survival = SurvivalCalculator(mort_table)

        # Pre-calculate discount factors
        self.v = 1 / (1 + assumptions.discount_rate)

    def discount_factor(self, n: int) -> float:
        """
        Calculate n-year discount factor v^n.

        Formula: v^n = 1/(1+i)^n

        Args:
            n: Number of years

        Returns:
            Discount factor
        """
        return self.v ** n

    def calculate_pvfb(
        self,
        entry_age: int,
        current_age: int,
        current_salary: float,
        current_yos: int = None
    ) -> float:
        """
        Calculate Present Value of Future Benefits for an individual.

        PVFB = sum over all future years of:
        - Survival probability to retirement
        - Benefit amount at retirement
        - COLA adjustments
        - Discount factor

        Args:
            entry_age: Age at plan entry
            current_age: Current age
            current_salary: Current annual salary
            current_yos: Current years of service (calculated if None)

        Returns:
            Present value of future benefits
        """
        if current_yos is None:
            current_yos = current_age - entry_age

        retirement_age = self.assumptions.retirement_age
        years_to_retirement = max(0, retirement_age - current_age)

        # Survival probability to retirement
        surv_to_retirement = self.survival.get_npx(
            entry_age, current_age, years_to_retirement
        )

        # Final salary at retirement (with salary growth)
        final_salary = current_salary * (
            (1 + self.assumptions.salary_growth) ** years_to_retirement
        )

        # Final years of service at retirement
        final_yos = current_yos + years_to_retirement

        # Annual benefit at retirement
        benefit = final_salary * final_yos * self.assumptions.benefit_multiplier

        # PVFB at retirement (annuity factor for life)
        # Simplified: use life expectancy at retirement
        life_expectancy = self.survival.get_ex(
            entry_age, retirement_age, self.assumptions.max_age
        )

        # Annuity factor (simplified - actual would use annuity certain + life)
        annuity_factor = self._calculate_annuity_factor(
            entry_age, retirement_age
        )

        # PVFB = Benefit * Annuity Factor * Survival * Discount
        pvfb = (benefit * annuity_factor *
                surv_to_retirement * self.discount_factor(years_to_retirement))

        return pvfb

    def _calculate_annuity_factor(
        self,
        entry_age: int,
        from_age: int
    ) -> float:
        """
        Calculate life annuity factor a_x.

        Formula: a_x = sum of (k_p_x * v^k) for k = 0 to infinity

        Args:
            entry_age: Age at plan entry
            from_age: Starting age (typically retirement age)

        Returns:
            Annuity factor
        """
        annuity = 0.0
        cola = self.assumptions.cola_rate

        for k in range(self.assumptions.max_age - from_age):
            # Survival probability for k years
            surv_k = self.survival.get_npx(entry_age, from_age, k)

            # Discount factor for k years
            discount_k = self.discount_factor(k)

            # COLA adjustment
            cola_factor = (1 + cola) ** k

            # Add to annuity
            annuity += surv_k * discount_k * cola_factor

        return annuity

    def calculate_pvfs(
        self,
        entry_age: int,
        current_age: int,
        current_salary: float
    ) -> float:
        """
        Calculate Present Value of Future Salary.

        PVFS = sum over all future working years of:
        - Survival probability
        - Salary with growth
        - Discount factor

        Args:
            entry_age: Age at plan entry
            current_age: Current age
            current_salary: Current annual salary

        Returns:
            Present value of future salary
        """
        retirement_age = self.assumptions.retirement_age
        years_to_retirement = max(0, retirement_age - current_age)

        pvfs = 0.0

        for k in range(years_to_retirement):
            # Survival probability for k years
            surv_k = self.survival.get_npx(entry_age, current_age, k + 1)

            # Salary in year k (with growth)
            salary_k = current_salary * (
                (1 + self.assumptions.salary_growth) ** k
            )

            # Discount factor
            discount_k = self.discount_factor(k)

            pvfs += surv_k * salary_k * discount_k

        return pvfs

    def calculate_normal_cost(
        self,
        entry_age: int,
        current_age: int,
        current_salary: float,
        current_yos: int = None
    ) -> float:
        """
        Calculate Normal Cost using EAN method.

        NC = (PVFB at current age) / (PVFS at entry age)
        This represents the level percentage of salary needed to fund benefits.

        Args:
            entry_age: Age at plan entry
            current_age: Current age
            current_salary: Current annual salary
            current_yos: Current years of service

        Returns:
            Normal cost amount
        """
        if current_yos is None:
            current_yos = current_age - entry_age

        # PVFB at current age
        pvfb_current = self.calculate_pvfb(
            entry_age, current_age, current_salary, current_yos
        )

        # PVFB at entry age (for EAN calculation)
        entry_salary = current_salary / (
            (1 + self.assumptions.salary_growth) ** current_yos
        )
        pvfb_entry = self.calculate_pvfb(
            entry_age, entry_age, entry_salary, 0
        )

        # PVFS at entry age
        pvfs_entry = self.calculate_pvfs(
            entry_age, entry_age, entry_salary
        )

        # Normal cost rate (level percentage of salary)
        if pvfs_entry > 0:
            nc_rate = pvfb_entry / pvfs_entry
        else:
            nc_rate = 0

        # Normal cost amount
        nc = current_salary * nc_rate

        return nc

    def calculate_aal(
        self,
        entry_age: int,
        current_age: int,
        current_salary: float,
        current_yos: int = None
    ) -> float:
        """
        Calculate Accrued Actuarial Liability using EAN method.

        AAL = PVFB * (accrued service / total expected service)

        For EAN method:
        AAL = PVFB - (PVFS * NC_rate)

        Args:
            entry_age: Age at plan entry
            current_age: Current age
            current_salary: Current annual salary
            current_yos: Current years of service

        Returns:
            Accrued actuarial liability
        """
        if current_yos is None:
            current_yos = current_age - entry_age

        # PVFB at current age
        pvfb = self.calculate_pvfb(
            entry_age, current_age, current_salary, current_yos
        )

        # PVFS at current age
        pvfs = self.calculate_pvfs(
            entry_age, current_age, current_salary
        )

        # Entry age PVFB for NC rate calculation
        entry_salary = current_salary / (
            (1 + self.assumptions.salary_growth) ** current_yos
        )
        pvfb_entry = self.calculate_pvfb(entry_age, entry_age, entry_salary, 0)
        pvfs_entry = self.calculate_pvfs(entry_age, entry_age, entry_salary)

        # NC rate
        if pvfs_entry > 0:
            nc_rate = pvfb_entry / pvfs_entry
        else:
            nc_rate = 0

        # AAL = PVFB - (PVFS * NC_rate)
        aal = pvfb - (pvfs * nc_rate)

        return max(0, aal)

    def calculate_cohort_pvfb(
        self,
        cohort: pd.DataFrame,
        salary_col: str = 'salary',
        entry_age_col: str = 'entry_age',
        age_col: str = 'age',
        count_col: str = 'n_active'
    ) -> float:
        """
        Calculate total PVFB for a cohort of members.

        Args:
            cohort: DataFrame with member data
            salary_col: Column name for salary
            entry_age_col: Column name for entry age
            age_col: Column name for current age
            count_col: Column name for member count

        Returns:
            Total PVFB for the cohort
        """
        total_pvfb = 0.0

        for _, row in cohort.iterrows():
            entry_age = int(row[entry_age_col])
            age = int(row[age_col])
            salary = row.get(salary_col, 50000)  # Default salary
            count = row[count_col]

            pvfb = self.calculate_pvfb(entry_age, age, salary)
            total_pvfb += pvfb * count

        return total_pvfb

    def calculate_cohort_normal_cost(
        self,
        cohort: pd.DataFrame,
        salary_col: str = 'salary',
        entry_age_col: str = 'entry_age',
        age_col: str = 'age',
        count_col: str = 'n_active'
    ) -> Tuple[float, float]:
        """
        Calculate total Normal Cost for a cohort.

        Args:
            cohort: DataFrame with member data
            salary_col: Column name for salary
            entry_age_col: Column name for entry age
            age_col: Column name for current age
            count_col: Column name for member count

        Returns:
            Tuple of (total NC, total payroll)
        """
        total_nc = 0.0
        total_payroll = 0.0

        for _, row in cohort.iterrows():
            entry_age = int(row[entry_age_col])
            age = int(row[age_col])
            salary = row.get(salary_col, 50000)
            count = row[count_col]

            nc = self.calculate_normal_cost(entry_age, age, salary)
            total_nc += nc * count
            total_payroll += salary * count

        return total_nc, total_payroll

    def calculate_cohort_aal(
        self,
        cohort: pd.DataFrame,
        salary_col: str = 'salary',
        entry_age_col: str = 'entry_age',
        age_col: str = 'age',
        count_col: str = 'n_active'
    ) -> float:
        """
        Calculate total AAL for a cohort.

        Args:
            cohort: DataFrame with member data
            salary_col: Column name for salary
            entry_age_col: Column name for entry age
            age_col: Column name for current age
            count_col: Column name for member count

        Returns:
            Total AAL for the cohort
        """
        total_aal = 0.0

        for _, row in cohort.iterrows():
            entry_age = int(row[entry_age_col])
            age = int(row[age_col])
            salary = row.get(salary_col, 50000)
            count = row[count_col]

            aal = self.calculate_aal(entry_age, age, salary)
            total_aal += aal * count

        return total_aal


def create_calculator_for_class(
    class_name: str,
    mort_table: pd.DataFrame,
    discount_rate: float = 0.067,
    salary_growth: float = 0.0325,
    cola_rate: float = 0.03,
    benefit_multiplier: float = 0.016,
    retirement_age: int = 62
) -> ActuarialCalculator:
    """
    Create an actuarial calculator configured for a membership class.

    Args:
        class_name: Name of membership class
        mort_table: Mortality rate table
        discount_rate: Annual discount rate
        salary_growth: Annual salary growth rate
        cola_rate: Cost of living adjustment rate
        benefit_multiplier: Benefit multiplier (e.g., 0.016 for 1.6%)
        retirement_age: Normal retirement age

    Returns:
        Configured ActuarialCalculator
    """
    # Adjust parameters by class
    class_multipliers = {
        'regular': 0.016,
        'special': 0.020,
        'admin': 0.016,
        'eco': 0.016,
        'eso': 0.016,
        'judges': 0.033,
        'senior_management': 0.016
    }

    class_retirement_ages = {
        'regular': 62,
        'special': 55,
        'admin': 62,
        'eco': 62,
        'eso': 62,
        'judges': 62,
        'senior_management': 62
    }

    # Use class-specific values if available
    benefit_multiplier = class_multipliers.get(class_name, benefit_multiplier)
    retirement_age = class_retirement_ages.get(class_name, retirement_age)

    assumptions = ActuarialAssumptions(
        discount_rate=discount_rate,
        salary_growth=salary_growth,
        cola_rate=cola_rate,
        benefit_multiplier=benefit_multiplier,
        retirement_age=retirement_age
    )

    return ActuarialCalculator(assumptions, mort_table)
