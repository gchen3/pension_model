"""
Pension Model Core Module

Production pipeline for pension modeling:
- benefit_tables: Build actuarial tables from raw inputs
- pipeline: End-to-end liability computation
- funding_model: Funding projection (assets, contributions, amortization)
"""

from .pipeline import run_plan_pipeline, build_plan_benefit_tables
from .data_loader import load_plan_inputs
from .funding_model import load_funding_inputs, run_funding_model

__all__ = [
    "run_plan_pipeline",
    "build_plan_benefit_tables",
    "load_plan_inputs",
    "load_funding_inputs",
    "run_funding_model",
]
