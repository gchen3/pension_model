"""
Pension Model Module

Core calculation engines for pension modeling.

This module provides:
- Workforce projection
- Benefit calculation
- Liability calculation
- Funding calculation
- Main model orchestrator

Design Principles:
- Stream year-by-year to avoid keeping all years in memory
- Use long format for core data (one row = one entity)
- Separate plan-specific logic from general actuarial calculations
- Support multiple pension plans through configuration abstraction
"""

from .model import PensionModel, run_pension_model

__all__ = [
    'PensionModel',
    'run_pension_model'
]
