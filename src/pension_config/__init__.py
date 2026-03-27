"""
pension_config module

Configuration management for pension modeling.

This module handles loading and validating plan-specific parameters,
actuarial assumptions, tier definitions, scenario management,
and plan adapters for multi-plan support.
"""

from pension_config.plan import MembershipClass, Tier, FundingPolicy, AmortizationMethod, ReturnScenario
from pension_config.plan_config import PlanConfig
from pension_config.assumptions import Assumptions
from pension_config.tiers import TierConfig
from pension_config.scenarios import ScenarioManager
from pension_config.adapters import PlanAdapter, BasePlanAdapter, PlanRegistry
from pension_config.frs_adapter import FRSAdapter, register_frs_adapter

__all__ = [
    # Core types
    "MembershipClass",
    "Tier",
    "FundingPolicy",
    "AmortizationMethod",
    "ReturnScenario",
    # Configuration classes
    "PlanConfig",
    "Assumptions",
    "TierConfig",
    "ScenarioManager",
    # Adapter framework
    "PlanAdapter",
    "BasePlanAdapter",
    "PlanRegistry",
    "FRSAdapter",
    "register_frs_adapter",
]
