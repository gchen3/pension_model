"""
Core type definitions for pension configuration.

This module defines enums and types used throughout the pension model.
It has no dependencies on other modules to avoid circular imports.
"""

from enum import Enum


class MembershipClass(str, Enum):
    """Membership class enumeration."""
    REGULAR = "regular"
    SPECIAL = "special"
    ADMIN = "admin"
    ECO = "eco"
    ESO = "eso"
    JUDGES = "judges"
    SENIOR_MANAGEMENT = "senior_management"


class Tier(str, Enum):
    """Tier enumeration."""
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class FundingPolicy(str, Enum):
    """Funding policy enumeration."""
    STATUTORY = "statutory"
    ADEQUACY = "adequacy"


class AmortizationMethod(str, Enum):
    """Amortization method enumeration."""
    LEVEL_PERCENT = "level %"
    LEVEL_DOLLAR = "level $"


class ReturnScenario(str, Enum):
    """Return scenario enumeration."""
    ASSUMPTION = "assumption"
    STRESS = "stress"
