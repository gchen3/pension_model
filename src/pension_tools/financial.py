"""
Financial functions for pension modeling.

This module contains pure functions for financial calculations
including present value, net present value, future value,
discount factors, and amortization calculations.
"""

from typing import Optional
import numpy as np


def present_value(
    rate: float,
    growth_rate: float = 0.0,
    nper: int = 1,
    payment: float = 1.0,
    timing: int = 1
) -> float:
    """
    Calculate present value of a series of payments.

    Args:
        rate: Discount rate (as decimal, e.g., 0.067 for 6.7%)
        growth_rate: Growth rate of payments (as decimal)
        nper: Number of periods
        payment: Payment amount
        timing: Payment timing (0=beginning, 1=end, 0.5=mid-period)

    Returns:
        Present value

    Formula:
        PV = PMT * (1 - (1+g)^-n) / (r-g) * (1+r)^-t

    Where r = (1+rate)/(1+growth_rate)
    """
    r = (1 + rate) / (1 + growth_rate)

    if r == 0:
        return payment * nper

    discount_factor = (1 + r) ** (-timing)

    if nper == 0:
        return payment / discount_factor

    pv_factor = (1 - (1 + r) ** -nper) / r
    return payment * pv_factor


def present_value_series(
    rate: float,
    payments: np.ndarray,
    growth_rate: float = 0.0,
    timing: int = 1
) -> np.ndarray:
    """
    Calculate present value of a series of payments.

    Args:
        rate: Discount rate (as decimal)
        growth_rate: Growth rate of payments (as decimal)
        payments: Array of payment amounts
        timing: Payment timing (0=beginning, 1=end)

    Returns:
        Array of present values
    """
    r = (1 + rate) / (1 + growth_rate)
    nper = len(payments)
    periods = np.arange(1, nper + 1)

    if r == 0:
        return payments

    discount_factor = (1 + r) ** (periods - timing)
    pv_factors = (1 - (1 + r) ** -periods) / r

    return payments * pv_factors


def net_present_value(
    rate: float,
    growth_rate: float = 0.0,
    nper: int = 1,
    payment: float = 1.0,
    timing: int = 1
) -> float:
    """
    Calculate net present value (NPV) of a series of payments.

    Args:
        rate: Discount rate (as decimal)
        growth_rate: Growth rate of payments (as decimal)
        nper: Number of periods
        payment: Payment amount
        timing: Payment timing (0=beginning, 1=end)

    Returns:
        Net present value
    """
    pv = present_value(rate, growth_rate, nper, payment, timing)
    return pv - payment


def future_value(
    rate: float,
    nper: int = 1,
    payment: float = 1.0,
    timing: int = 1
) -> float:
    """
    Calculate future value of a series of payments.

    Args:
        rate: Interest rate (as decimal)
        nper: Number of periods
        payment: Payment amount
        timing: Payment timing (0=beginning, 1=end)

    Returns:
        Future value

    Formula:
        FV = PMT * ((1+r)^n-1) / r
    """
    if rate == 0:
        return payment * nper

    discount_factor = (1 + rate) ** (nper - timing)

    if nper == 0:
        return payment

    fv_factor = ((1 + rate) ** (nper - timing) - 1) / rate
    return payment * fv_factor


def cumulative_future_value(
    rate: float,
    cashflows: np.ndarray,
    first_value: float = 0.0
) -> np.ndarray:
    """
    Calculate cumulative future value of a series of cashflows.

    Args:
        rate: Interest rate (as decimal)
        cashflows: Array of cashflows
        first_value: Initial value

    Returns:
        Array of cumulative future values
    """
    cumvalues = np.zeros(len(cashflows))
    cumvalues[0] = first_value

    for i in range(1, len(cashflows)):
        cumvalues[i] = cumvalues[i-1] * (1 + rate) + cashflows[i-1]

    return cumvalues


def discount_factor(
    rate: float,
    periods: int,
    timing: int = 1
) -> np.ndarray:
    """
    Calculate discount factors for a series of periods.

    Args:
        rate: Discount rate (as decimal)
        periods: Number of periods
        timing: Payment timing (0=beginning, 1=end)

    Returns:
        Array of discount factors
    """
    return (1 + rate) ** (np.arange(periods) - timing)


def amortization_payment(
    principal: float,
    rate: float,
    nper: int = 1,
    growth_rate: float = 0.0,
    timing: int = 1
) -> float:
    """
    Calculate amortization payment.

    Args:
        principal: Present value (principal amount)
        rate: Interest rate (as decimal)
        nper: Number of periods
        growth_rate: Growth rate of payments (as decimal)
        timing: Payment timing (0=beginning, 1=end)

    Returns:
        Amortization payment amount
    """
    if nper <= 0:
        return principal

    # Adjusted rate for payment growth
    r = (1 + rate) / (1 + growth_rate) - 1

    if abs(r) < 1e-10:
        # When adjusted rate is ~0, payments are level
        return principal / nper

    # Standard annuity payment formula: PMT = PV * r / (1 - (1+r)^-n)
    # Adjusted for timing (beginning vs end of period)
    annuity_factor = (1 - (1 + r) ** (-nper)) / r

    if timing == 0:
        # Beginning of period: annuity-due
        annuity_factor *= (1 + r)

    if abs(annuity_factor) < 1e-10:
        return principal

    return principal / annuity_factor


def funding_period(
    rate: float,
    principal: float,
    payment: float,
    growth_rate: float = 0.0,
    timing: int = 1
) -> float:
    """
    Calculate number of periods to amortize a liability.

    Args:
        rate: Interest rate (as decimal)
        growth_rate: Growth rate of payments (as decimal)
        principal: Present value (liability amount)
        payment: Payment amount
        timing: Payment timing (0=beginning, 1=end)

    Returns:
        Number of periods required
    """
    r = (1 + rate) / (1 + growth_rate)

    if r == 0:
        return principal / payment

    discount_factor = (1 + r) ** (-timing)
    annuity_factor = payment / (principal * discount_factor)

    # NPER = -ln(1 - annuity_factor) / ln(1 + r)
    if annuity_factor >= 1:
        return 0
    elif annuity_factor <= 0:
        return 100
    else:
        nper = -np.log(1 - annuity_factor) / np.log(1 + r)
        return min(nper, 100)
