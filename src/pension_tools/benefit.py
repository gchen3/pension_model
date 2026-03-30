"""
Benefit calculation functions for pension modeling.
"""

from typing import Optional
import numpy as np


def calculate_normal_cost(
    salary: float,
    yos: int,
    entry_age: int,
    accrual_rate: float = 0.02
) -> float:
    """
    Calculate normal cost using entry age normal formula.

    Args:
        salary: Current salary
        yos: Years of service
        entry_age: Age when member entered plan
        accrual_rate: Accrual rate (e.g., 0.02)

    Returns:
        Normal cost
    """
    return salary * yos * accrual_rate


def calculate_accrued_liability(
    salary: float,
    yos: int,
    entry_age: int,
    accrual_rate: float = 0.02
) -> float:
    """
    Calculate accrued liability.

    Args:
        salary: Current salary
        yos: Years of service
        entry_age: Age when member entered plan
        accrual_rate: Accrual rate (e.g., 0.02)

    Returns:
        Accrued liability
    """
    nc = calculate_normal_cost(salary, yos, entry_age, accrual_rate)
    return nc * (yos - entry_age)


def calculate_pvfb(
    salary: float,
    yos: int,
    entry_age: int,
    age: int,
    discount_rate: float,
    survival_to_age: float,
    benefit_factor: float = 1.0
) -> float:
    """
    Calculate present value of future benefits.

    Args:
        salary: Projected salary at retirement
        yos: Years of service at retirement
        entry_age: Age when member entered plan
        age: Current age at retirement
        discount_rate: Discount rate
        survival_to_age: Probability of survival to retirement age
        benefit_factor: Benefit multiplier (e.g., 1.0 for full benefit)

    Returns:
        Present value of future benefits
    """
    annual_benefit = salary * benefit_factor

    # Discount to present value
    years_to_retirement = age - entry_age
    pv = annual_benefit / ((1 + discount_rate) ** years_to_retirement)

    # Apply survival probability
    pvfb = pv * survival_to_age

    return pvfb


def calculate_pvfs(
    salary: float,
    yos: int,
    entry_age: int,
    age: int,
    discount_rate: float,
    survival_to_age: float,
    benefit_factor: float = 1.0
) -> float:
    """
    Calculate present value of future service.

    Args:
        salary: Projected salary at each age
        yos: Years of service at each age
        entry_age: Age when member entered plan
        age: Current age
        discount_rate: Discount rate
        survival_to_age: Probability of survival to each age
        benefit_factor: Benefit multiplier

    Returns:
        Present value of future service
    """
    years_to_retirement = age - entry_age

    # Calculate salary at each future age
    future_salary = salary * (1 + discount_rate) ** years_to_retirement

    # Calculate benefit at each future age
    future_benefit = future_salary * benefit_factor

    # Discount each year's benefit
    discount_factors = (1 + discount_rate) ** -np.arange(years_to_retirement + 1)
    pv_benefits = future_benefit / discount_factors

    # Apply survival probability
    pvfs = pv_benefits * survival_to_age

    # Sum over all future ages
    return np.sum(pvfs)


def calculate_pvfb_al(
    salary: float,
    yos: int,
    entry_age: int,
    age: int,
    discount_rate: float,
    survival_to_age: float,
    benefit_factor: float = 1.0
) -> float:
    """
    Calculate present value of future benefits (accrued liability).

    Args:
        salary: Projected salary at retirement
        yos: Years of service at retirement
        entry_age: Age when member entered plan
        age: Current age at retirement
        discount_rate: Discount rate
        survival_to_age: Probability of survival to retirement age
        benefit_factor: Benefit multiplier

    Returns:
        Present value of accrued liability
    """
    years_to_retirement = age - entry_age

    # Calculate salary at retirement
    retirement_salary = salary * (1 + discount_rate) ** years_to_retirement

    # Calculate benefit at retirement
    retirement_benefit = retirement_salary * benefit_factor

    # Discount to present value
    pv = retirement_benefit / ((1 + discount_rate) ** years_to_retirement)

    # Apply survival probability
    pvfb_al = pv * survival_to_age

    return pvfb_al


def calculate_deferred_annuity_pv(
    final_salary: float,
    yos: int,
    current_age: int,
    retirement_age: int,
    benefit_multiplier: float,
    discount_rate: float,
    mortality_table: dict = None,
    cola_rate: float = 0.0
) -> float:
    """
    Calculate present value of deferred annuity (monthly pension starting at retirement age).

    This is the value of waiting until retirement age to collect a monthly pension,
    discounted back to current age.

    Args:
        final_salary: Final average salary at termination
        yos: Years of service at termination
        current_age: Current age of terminated member
        retirement_age: Age when annuity payments begin
        benefit_multiplier: Annual benefit multiplier (e.g., 0.016 for 1.6%)
        discount_rate: Discount rate for present value
        mortality_table: Optional mortality table for survival probability
        cola_rate: Cost-of-living adjustment rate

    Returns:
        Present value of deferred annuity
    """
    # Calculate annual benefit at retirement
    annual_benefit = final_salary * yos * benefit_multiplier

    # If no benefit (insufficient YOS), return 0
    if annual_benefit <= 0:
        return 0.0

    # Years until retirement
    years_to_retirement = retirement_age - current_age

    if years_to_retirement <= 0:
        # Already at/past retirement age - immediate annuity
        years_to_retirement = 0

    # Calculate annuity factor (simplified - assumes 20 years of payments)
    # In full implementation, would use proper annuity calculation with mortality
    payment_years = 20  # Simplified assumption

    # Annuity factor with COLA
    if cola_rate > 0:
        # Annuity with COLA: sum of (1+cola)^n / (1+dr)^n
        annuity_factor = sum(
            (1 + cola_rate) ** n / (1 + discount_rate) ** n
            for n in range(1, payment_years + 1)
        )
    else:
        # Simple annuity factor
        annuity_factor = (1 - (1 + discount_rate) ** -payment_years) / discount_rate

    # PV of annuity at retirement age
    pv_at_retirement = annual_benefit * annuity_factor

    # Discount back to current age
    pv_current = pv_at_retirement / ((1 + discount_rate) ** years_to_retirement)

    # Apply survival probability if mortality table provided
    if mortality_table is not None:
        survival_prob = 1.0
        for age in range(current_age, retirement_age):
            qx = mortality_table.get(age, 0.0)
            survival_prob *= (1 - qx)
        pv_current *= survival_prob

    return pv_current


def calculate_refund_pv(
    employee_contributions: float,
    interest_rate: float,
    years_of_contributions: int,
    credit_interest_rate: float = None
) -> float:
    """
    Calculate present value of refund (lump sum of employee contributions with interest).

    This is the value of taking an immediate refund of contributions.

    Args:
        employee_contributions: Total employee contributions made
        interest_rate: Interest rate credited on contributions
        years_of_contributions: Number of years contributions were made
        credit_interest_rate: Optional separate interest credit rate (defaults to interest_rate)

    Returns:
        Present value of refund (lump sum)
    """
    if credit_interest_rate is None:
        credit_interest_rate = interest_rate

    # Calculate accumulated value with credited interest
    # Assumes contributions made evenly over the period
    if years_of_contributions <= 0:
        return employee_contributions

    # Simplified: average contribution period is half the years
    avg_years = years_of_contributions / 2
    accumulated_value = employee_contributions * ((1 + credit_interest_rate) ** avg_years)

    return accumulated_value


def optimize_benefit_decision(
    final_salary: float,
    yos: int,
    current_age: int,
    entry_age: int,
    employee_contributions: float,
    normal_retirement_age: int,
    benefit_multiplier: float,
    discount_rate: float,
    contribution_interest_rate: float = 0.03,
    mortality_table: dict = None,
    cola_rate: float = 0.0,
    min_vesting_yos: int = 5
) -> tuple:
    """
    Optimize benefit decision: compare PV of deferred annuity vs refund.

    Determines whether a terminated vested member should:
    - Take a deferred annuity (monthly pension starting at retirement age)
    - Take a refund (lump sum of employee contributions)

    Args:
        final_salary: Final average salary at termination
        yos: Years of service at termination
        current_age: Current age of terminated member
        entry_age: Age when member entered plan
        employee_contributions: Total employee contributions made
        normal_retirement_age: Normal retirement age for the plan
        benefit_multiplier: Annual benefit multiplier (e.g., 0.016 for 1.6%)
        discount_rate: Discount rate for present value calculations
        contribution_interest_rate: Interest rate credited on contributions
        mortality_table: Optional mortality table for survival probability
        cola_rate: Cost-of-living adjustment rate
        min_vesting_yos: Minimum YOS for vesting

    Returns:
        Tuple of (decision, annuity_pv, refund_pv)
        decision: 'annuity' if deferred annuity is better, 'refund' if refund is better
    """
    # Check vesting requirement
    if yos < min_vesting_yos:
        # Not vested - must take refund
        refund_pv = calculate_refund_pv(
            employee_contributions,
            contribution_interest_rate,
            yos
        )
        return ('refund', 0.0, refund_pv)

    # Calculate PV of deferred annuity
    annuity_pv = calculate_deferred_annuity_pv(
        final_salary=final_salary,
        yos=yos,
        current_age=current_age,
        retirement_age=normal_retirement_age,
        benefit_multiplier=benefit_multiplier,
        discount_rate=discount_rate,
        mortality_table=mortality_table,
        cola_rate=cola_rate
    )

    # Calculate PV of refund
    refund_pv = calculate_refund_pv(
        employee_contributions=employee_contributions,
        interest_rate=contribution_interest_rate,
        years_of_contributions=yos
    )

    # Optimal decision: choose higher PV
    if annuity_pv >= refund_pv:
        return ('annuity', annuity_pv, refund_pv)
    else:
        return ('refund', annuity_pv, refund_pv)


def get_benefit_decision_probabilities(
    final_salary: float,
    yos: int,
    current_age: int,
    entry_age: int,
    employee_contributions: float,
    normal_retirement_age: int,
    benefit_multiplier: float,
    discount_rate: float,
    contribution_interest_rate: float = 0.03,
    mortality_table: dict = None,
    cola_rate: float = 0.0,
    min_vesting_yos: int = 5
) -> tuple:
    """
    Get probabilities for retire vs refund decision based on PV comparison.

    Returns probabilities that can be used in workforce projection.

    Args:
        (Same as optimize_benefit_decision)

    Returns:
        Tuple of (retire_prob, refund_prob)
    """
    decision, annuity_pv, refund_pv = optimize_benefit_decision(
        final_salary=final_salary,
        yos=yos,
        current_age=current_age,
        entry_age=entry_age,
        employee_contributions=employee_contributions,
        normal_retirement_age=normal_retirement_age,
        benefit_multiplier=benefit_multiplier,
        discount_rate=discount_rate,
        contribution_interest_rate=contribution_interest_rate,
        mortality_table=mortality_table,
        cola_rate=cola_rate,
        min_vesting_yos=min_vesting_yos
    )

    if decision == 'annuity':
        return (1.0, 0.0)
    else:
        return (0.0, 1.0)
