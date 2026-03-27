"""
pension_config module

Configuration management for pension modeling.

This module handles loading and validating plan-specific parameters,
actuarial assumptions, tier definitions, and scenario management.
"""

from pension_config.plan_config import PlanConfig
from pension_config.assumptions import Assumptions
from pension_config.tiers import TierConfig
from pension_config.scenarios import ScenarioManager

__all__ = [
    "PlanConfig",
    "Assumptions",
    "TierConfig",
    "ScenarioManager",
]
