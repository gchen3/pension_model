"""
pension_tools module

Actuarial functions for pension modeling.

This module contains pure functions (no state) for all actuarial calculations
including financial functions, salary growth, mortality, withdrawal rates,
retirement eligibility, benefit calculations, and amortization.
"""

from pension_tools import financial, salary, mortality, withdrawal, retirement, benefit, amortization

__all__ = [
    "financial",
    "salary",
    "mortality",
    "withdrawal",
    "retirement",
    "benefit",
    "amortization",
]
