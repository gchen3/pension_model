"""
Salary growth functions for pension modeling.
"""

from typing import Optional
import numpy as np


def cumulative_salary_growth(
    growth_rates: np.ndarray,
    max_yos: int = 70
) -> np.ndarray:
    """
    Calculate cumulative salary growth factors.

    Args:
        growth_rates: Array of annual growth rates by YOS
        max_yos: Maximum years of service to calculate

    Returns:
        Array of cumulative growth factors
    """
    cum_growth = np.cumprod(1 + growth_rates[:max_yos])
    return cum_growth


def salary_with_growth(
    entry_salary: float,
    yos: int,
    cumulative_growth: float
) -> float:
    """
    Calculate salary after applying cumulative growth.

    Args:
        entry_salary: Starting salary
        yos: Years of service
        cumulative_growth: Cumulative growth factor

    Returns:
        Salary after growth
    """
    return entry_salary * cumulative_growth


def projected_salary(
    current_salary: float,
    growth_rate: float,
    years: int
) -> np.ndarray:
    """
    Project salary forward with growth.

    Args:
        current_salary: Current salary
        growth_rate: Annual growth rate
        years: Number of years to project

    Returns:
        Array of projected salaries
    """
    salaries = np.zeros(years)
    salaries[0] = current_salary

    for i in range(1, years):
        salaries[i] = salaries[i-1] * (1 + growth_rate)

    return salaries
