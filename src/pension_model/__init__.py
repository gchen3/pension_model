"""
Pension Model Module

End-to-end pension model: stage 3 data -> benefit tables -> liability -> funding.

Production modules:
- core.pipeline: Liability computation pipeline
- core.funding_model: Funding projection
- core.benefit_tables: Actuarial table construction
- plan_config: Plan parameters and table-driven tier/benefit rules
"""

from .core import run_class_pipeline_e2e, compute_funding, load_funding_inputs

__all__ = [
    "run_class_pipeline_e2e",
    "compute_funding",
    "load_funding_inputs",
]
