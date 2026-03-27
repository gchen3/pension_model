"""
pension_config module

Configuration management for pension modeling.

This module handles loading and validating plan-specific parameters,
actuarial assumptions, tier definitions, scenario management,
and plan adapters for multi-plan support.
"""

# Import enums from types.py (no circular imports)
from .types import MembershipClass, Tier, FundingPolicy, AmortizationMethod, ReturnScenario

# Import adapters
from .adapters import PlanAdapter, BasePlanAdapter, PlanRegistry
from .frs_adapter import FRSAdapter

__all__ = [
    # Core types
    "MembershipClass",
    "Tier",
    "FundingPolicy",
    "AmortizationMethod",
    "ReturnScenario",
    # Adapters
    "PlanAdapter",
    "BasePlanAdapter",
    "PlanRegistry",
    "FRSAdapter",
]
