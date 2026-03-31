"""
Pension Model Core Module

Production pipeline for pension modeling:
- benefit_tables: Build actuarial tables from raw inputs
- pipeline: End-to-end liability computation
- funding_model: Funding projection (assets, contributions, amortization)
- tier_logic: Plan-specific tier and benefit rules
- model_constants: All model parameters and constants
"""

from .pipeline import run_class_pipeline
from .funding_model import compute_funding, load_funding_inputs
from .model_constants import (
    ModelConstants, frs_constants, load_calibration, apply_calibration, neutral_calibration,
)

__all__ = [
    "run_class_pipeline",
    "compute_funding",
    "load_funding_inputs",
    "ModelConstants",
    "frs_constants",
    "load_calibration",
    "apply_calibration",
    "neutral_calibration",
]
