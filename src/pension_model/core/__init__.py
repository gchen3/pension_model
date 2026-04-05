"""
Pension Model Core Module

Production pipeline for pension modeling:
- benefit_tables: Build actuarial tables from raw inputs
- pipeline: End-to-end liability computation
- funding_model: Funding projection (assets, contributions, amortization)
"""

from .pipeline import run_class_pipeline_e2e
from .funding_model import compute_funding, load_funding_inputs

__all__ = [
    "run_class_pipeline_e2e",
    "compute_funding",
    "load_funding_inputs",
]
