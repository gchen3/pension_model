"""
pension_tools module

Actuarial functions for pension modeling.

This module contains pure functions (no state) for all actuarial calculations
including financial functions, salary growth, mortality, withdrawal rates,
retirement eligibility, benefit calculations, and amortization.
"""

# Import submodules (lazy loading to avoid circular imports)
from pension_tools.actuarial import (
    ActuarialAssumptions,
    SurvivalCalculator,
    ActuarialCalculator,
    create_calculator_for_class,
)

__all__ = [
    "ActuarialAssumptions",
    "SurvivalCalculator",
    "ActuarialCalculator",
    "create_calculator_for_class",
]
