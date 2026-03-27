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
