"""
Pension Model Module

End-to-end pension model: stage 3 data -> benefit tables -> liability -> funding.

Production modules:
- core.pipeline: Liability computation pipeline
- core.funding_model: Funding projection
- core.benefit_tables: Actuarial table construction
- plan_config: Plan parameters and table-driven tier/benefit rules
"""

from .core import (
    build_plan_benefit_tables,
    load_funding_inputs,
    run_funding_model,
    run_plan_pipeline,
)

__all__ = [
    "run_plan_pipeline",
    "build_plan_benefit_tables",
    "run_funding_model",
    "load_funding_inputs",
]
