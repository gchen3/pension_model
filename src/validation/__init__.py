"""
Validation Module

Compares Python model outputs against R baseline outputs.

This module provides:
- Comparison of workforce projections
- Comparison of benefit calculations
- Comparison of liability calculations
- Comparison of funding calculations
- Discrepancy reporting
"""

from .comparators import (
    Validator,
    ValidationConfig,
    ComparisonResult,
    ComparisonSummary,
    validate_model_outputs
)
from .actuarial_validation import (
    ActuarialValidator,
    ValidationResult,
    run_actuarial_validation
)

__all__ = [
    'Validator',
    'ValidationConfig',
    'ComparisonResult',
    'ComparisonSummary',
    'validate_model_outputs',
    'ActuarialValidator',
    'ValidationResult',
    'run_actuarial_validation'
]
