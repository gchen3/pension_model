"""
Pension Model Core Module

Core calculation engines for pension modeling:
- Workforce projection
- Benefit calculation
- Liability calculation
- Funding calculation
"""

from .workforce import (
    WorkforceProjector,
    WorkforceState,
    project_workforce
)

from .benefit import (
    BenefitCalculator,
    BenefitCalculation,
    calculate_benefit_table
)

from .liability import (
    LiabilityCalculator,
    LiabilitySummary,
    calculate_liabilities
)

from .funding import (
    FundingCalculator,
    FundingSummary,
    calculate_funding
)

__all__ = [
    # Workforce
    'WorkforceProjector',
    'WorkforceState',
    'project_workforce',

    # Benefit
    'BenefitCalculator',
    'BenefitCalculation',
    'calculate_benefit_table',

    # Liability
    'LiabilityCalculator',
    'LiabilitySummary',
    'calculate_liabilities',

    # Funding
    'FundingCalculator',
    'FundingSummary',
    'calculate_funding'
]
