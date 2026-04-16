"""
Pension Model Core Module

Production pipeline for pension modeling:
- benefit_tables: Build actuarial tables from raw inputs
- pipeline: End-to-end liability computation
- funding_model: Funding projection (assets, contributions, amortization)
"""

from .pipeline import (
    PreparedPlanRun,
    build_plan_benefit_tables,
    prepare_plan_run,
    run_plan_pipeline,
    run_prepared_plan_pipeline,
    summarize_prepared_plan_run,
)
from .data_loader import load_plan_inputs
from .funding_model import load_funding_inputs, run_funding_model
from .profiling import profile_plan_runtime

__all__ = [
    "PreparedPlanRun",
    "run_plan_pipeline",
    "prepare_plan_run",
    "run_prepared_plan_pipeline",
    "summarize_prepared_plan_run",
    "build_plan_benefit_tables",
    "load_plan_inputs",
    "load_funding_inputs",
    "run_funding_model",
    "profile_plan_runtime",
]
