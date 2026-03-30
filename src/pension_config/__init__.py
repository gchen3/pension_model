"""
pension_config module

Configuration management for pension modeling.

This module handles loading and validating plan-specific parameters,
actuarial assumptions, tier definitions, scenario management,
and plan adapters for multi-plan support.
"""

# Import enums from types.py (no circular imports)
from .types import MembershipClass, Tier, FundingPolicy, AmortizationMethod, ReturnScenario

# Import plan configuration
from .plan import PlanConfig, TierConfig, MembershipClassConfig, create_frs_config

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
    # Plan configuration
    "PlanConfig",
    "TierConfig",
    "MembershipClassConfig",
    "create_frs_config",
    # Adapters
    "PlanAdapter",
    "BasePlanAdapter",
    "PlanRegistry",
    "FRSAdapter",
]
