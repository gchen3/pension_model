"""Lightweight runtime profiling helpers for the core pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass

from pension_model.core.funding_model import load_funding_inputs, run_funding_model
from pension_model.core.pipeline import (
    PreparedPlanRun,
    prepare_plan_run,
    run_prepared_plan_pipeline,
    summarize_prepared_plan_run,
)


@dataclass(frozen=True)
class RuntimeProfile:
    """Timing summary for a plan run."""

    prepared_run: PreparedPlanRun
    liability_timing: float
    funding_timing: float | None

    @property
    def prepare(self) -> PreparedPlanRun:
        """Backward-compatible alias for the prepared runtime state."""
        return self.prepared_run

    def as_dict(self) -> dict:
        summary = summarize_prepared_plan_run(self.prepared_run)
        summary["liability_timing"] = self.liability_timing
        summary["funding_timing"] = self.funding_timing
        return summary


def profile_plan_runtime(
    constants,
    *,
    include_funding: bool = False,
    research_mode: bool = False,
) -> RuntimeProfile:
    """Profile the prepare/liability/funding stages for a plan."""
    prepared_run = prepare_plan_run(constants, research_mode=research_mode)

    started_at = time.perf_counter()
    liability = run_prepared_plan_pipeline(prepared_run)
    liability_timing = time.perf_counter() - started_at

    funding_timing = None
    if include_funding:
        started_at = time.perf_counter()
        funding_inputs = load_funding_inputs(prepared_run.constants.resolve_data_dir() / "funding")
        run_funding_model(liability, funding_inputs, prepared_run.constants)
        funding_timing = time.perf_counter() - started_at

    return RuntimeProfile(
        prepared_run=prepared_run,
        liability_timing=liability_timing,
        funding_timing=funding_timing,
    )
