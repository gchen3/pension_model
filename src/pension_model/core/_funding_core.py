"""
Funding model core: the unified compute function.

Holds :func:`_compute_funding`, the single year-loop that runs the
funding model for any plan. Path selection (AVA smoothing,
contribution policy) is dispatched via :class:`FundingContext`
strategies built from ``plan_config.json``; capability differences
(DC, CB, DROP, multi-class) are handled by capability flags on the
context. ``run_funding_model`` in ``funding_model.py`` is a thin
pass-through.

Bit-identity constraints (preserved from the original two-function
implementation):
  * Mid-year exponent ``(1 + dr) ** 0.5`` is computed inside helpers
    from a scalar ``dr``, never from a precomputed ``sqrt_factor``.
  * Aggregate accumulation order matches the original single-cell
    write order; do not convert to bulk ``f.loc[i, cols] = values``.
"""

import numpy as np
import pandas as pd

from pension_model.core._funding_helpers import _maybe_accumulate
from pension_model.core._funding_phases import (
    _finalize_ava_with_drop,
    _nc_rate_agg,
    _phase_amort_rolling,
    _phase_ava_corridor_smoothing,
    _phase_ava_gainloss_smoothing,
    _phase_benefits_refunds,
    _phase_cash_flow_and_solvency,
    _phase_contributions,
    _phase_dc_contributions,
    _phase_drop_projection,
    _phase_er_cont_totals,
    _phase_liability_gl_and_aal,
    _phase_mva,
    _phase_normal_cost,
    _phase_payroll,
    _phase_real_cost_metrics,
    _phase_ual_and_funded_ratios,
    _prepare_return_scenarios,
)
from pension_model.core._funding_setup import (
    FundingContext,
    calibrate_funding_frames,
    resolve_funding_context,
    select_amo_state,
    setup_amort_state,
    setup_funding_frames,
)


def _accumulate_class_payroll(ctx: FundingContext, agg: pd.DataFrame, f: pd.DataFrame, i: int) -> None:
    """Accumulate class payroll columns into the aggregate row."""
    _maybe_accumulate(ctx, agg, f, i, ["total_payroll", "payroll_db_legacy", "payroll_db_new"])
    if ctx.has_dc:
        _maybe_accumulate(ctx, agg, f, i, ["payroll_dc_legacy", "payroll_dc_new"])


def _write_benefit_refund_totals(f: pd.DataFrame, i: int) -> None:
    """Populate per-row total benefit payment and refund columns when present."""
    if "total_ben_payment" in f.columns:
        f.loc[i, "total_ben_payment"] = f.loc[i, "ben_payment_legacy"] + f.loc[i, "ben_payment_new"]
    if "total_refund" in f.columns:
        f.loc[i, "total_refund"] = f.loc[i, "refund_legacy"] + f.loc[i, "refund_new"]


def _accumulate_benefits_refunds(ctx: FundingContext, agg: pd.DataFrame, f: pd.DataFrame, i: int) -> None:
    """Accumulate per-class benefit/refund columns into the aggregate row."""
    _maybe_accumulate(ctx, agg, f, i, ["ben_payment_legacy", "refund_legacy", "ben_payment_new", "refund_new"])
    if "total_ben_payment" in f.columns:
        _maybe_accumulate(ctx, agg, f, i, ["total_ben_payment", "total_refund"])


def _set_liability_gain_loss_sum(ctx: FundingContext, f: pd.DataFrame, i: int) -> None:
    """Write summed liability gain/loss when the AVA schema expects it."""
    if ctx.ava_strategy.emits_liability_gain_loss_sum:
        f.loc[i, "liability_gain_loss"] = (
            f.loc[i, "liability_gain_loss_legacy"] + f.loc[i, "liability_gain_loss_new"]
        )


def _set_dc_rates(f: pd.DataFrame, i: int, cn: str, ctx: FundingContext, constants) -> None:
    """Write DC employer rates for one class row when the plan has a DC leg."""
    if not ctx.has_dc:
        return
    if cn == "drop":
        f.loc[i, "er_dc_rate_legacy"] = 0
        f.loc[i, "er_dc_rate_new"] = 0
        return
    dc_rate = constants.class_data[cn].er_dc_cont_rate
    f.loc[i, "er_dc_rate_legacy"] = dc_rate
    f.loc[i, "er_dc_rate_new"] = dc_rate


def _accumulate_db_contributions(ctx: FundingContext, agg: pd.DataFrame, f: pd.DataFrame, i: int) -> None:
    """Accumulate DB employer contribution columns into the aggregate row."""
    _maybe_accumulate(ctx, agg, f, i, ["er_nc_cont_legacy", "er_nc_cont_new", "er_amo_cont_legacy", "er_amo_cont_new"])
    if "total_er_db_cont" in f.columns:
        _maybe_accumulate(ctx, agg, f, i, ["total_er_db_cont"])


def _resolve_roa(ret_scen: pd.DataFrame, year: int, return_scen_col: str, dr_current: float) -> float:
    """Return the realized rate of return for a projection year."""
    roa_row = ret_scen[ret_scen["year"] == year]
    return roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current


def _set_plan_level_ava_bases(f: pd.DataFrame, i: int) -> None:
    """Seed plan-level AVA base columns from prior AVA and current net cash flow."""
    f.loc[i, "ava_base_legacy"] = f.loc[i - 1, "ava_legacy"] + f.loc[i, "net_cf_legacy"] / 2
    f.loc[i, "ava_base_new"] = f.loc[i - 1, "ava_new"] + f.loc[i, "net_cf_new"] / 2


def _set_total_contribution_rate(f: pd.DataFrame, i: int) -> None:
    """Compute total contribution rate when the schema includes it."""
    if "tot_cont_rate" not in f.columns:
        return
    total_payroll = f.loc[i, "total_payroll"]
    f.loc[i, "tot_cont_rate"] = (
        (
            f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_amo_cont_legacy"]
            + f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"] + f.loc[i, "er_amo_cont_new"]
            + f.loc[i, "solv_cont"]
        ) / total_payroll
    ) if total_payroll > 0 else 0


def _finalize_aggregate_row(agg: pd.DataFrame, i: int) -> None:
    """Compute aggregate funded ratios and contribution rate for one year."""
    total_aal = agg.loc[i, "total_aal"]
    total_payroll = agg.loc[i, "total_payroll"]
    agg.loc[i, "fr_mva"] = agg.loc[i, "total_mva"] / total_aal if total_aal != 0 else 0
    agg.loc[i, "fr_ava"] = agg.loc[i, "total_ava"] / total_aal if total_aal != 0 else 0
    agg.loc[i, "total_er_cont_rate"] = agg.loc[i, "total_er_cont"] / total_payroll if total_payroll > 0 else 0


def _run_phase1_for_class(
    cn: str,
    i: int,
    funding: dict,
    liability_results: dict,
    agg: pd.DataFrame,
    ctx: FundingContext,
    dr_current: float,
    dr_new: float,
) -> None:
    """Execute phase 1 for one non-DROP class."""
    f = funding[cn]
    liab = liability_results[cn]

    _phase_payroll(f, i, ctx)
    _accumulate_class_payroll(ctx, agg, f, i)

    _phase_benefits_refunds(f, liab, i, ctx)
    _write_benefit_refund_totals(f, i)
    _accumulate_benefits_refunds(ctx, agg, f, i)

    _phase_normal_cost(f, i, ctx)
    _maybe_accumulate(ctx, agg, f, i, ["nc_legacy", "nc_new"])

    _phase_liability_gl_and_aal(f, liab, i, dr_current, dr_new)
    _maybe_accumulate(ctx, agg, f, i, ["aal_legacy", "aal_new", "total_aal"])

    _set_liability_gain_loss_sum(ctx, f, i)
    funding[cn] = f


def _run_phase2_for_class(
    cn: str,
    i: int,
    year: int,
    funding: dict,
    agg: pd.DataFrame,
    amort_state: dict,
    ctx: FundingContext,
    constants,
    cont_strategy,
    ret_scen: pd.DataFrame,
    return_scen_col: str,
    dr_current: float,
    dr_new: float,
) -> None:
    """Execute phase 2 for one class or DROP frame."""
    f = funding[cn]
    amo = select_amo_state(amort_state, cn)
    cont_strategy.compute_rates(f, i, year, amo)

    _set_dc_rates(f, i, cn, ctx, constants)

    _phase_contributions(f, i, ctx)
    _maybe_accumulate(ctx, agg, f, i, ["ee_nc_cont_legacy", "ee_nc_cont_new"])
    _maybe_accumulate(ctx, agg, f, i, ["admin_exp_legacy", "admin_exp_new"])

    if ctx.is_multi_class:
        if "total_er_db_cont" in ctx.init_funding.columns:
            f.loc[i, "total_er_db_cont"] = (
                f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
                + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"]
            )
        _accumulate_db_contributions(ctx, agg, f, i)

    if ctx.has_dc:
        _phase_dc_contributions(f, i)
        _maybe_accumulate(ctx, agg, f, i, ["er_dc_cont_legacy", "er_dc_cont_new", "total_er_dc_cont"])

    roa = _resolve_roa(ret_scen, year, return_scen_col, dr_current)
    f.loc[i, "roa"] = roa
    if ctx.is_multi_class:
        agg.loc[i, "roa"] = roa

    _phase_cash_flow_and_solvency(f, i, roa)
    _maybe_accumulate(ctx, agg, f, i, ["net_cf_legacy", "net_cf_new"])

    _phase_mva(f, i, roa)
    _maybe_accumulate(ctx, agg, f, i, ["mva_legacy", "mva_new", "total_mva"])

    if ctx.ava_strategy.aggregation_level == "plan":
        _set_plan_level_ava_bases(f, i)
    if ctx.ava_strategy.aggregation_level == "class":
        _phase_ava_gainloss_smoothing(f, i, ctx.ava_strategy, dr_current, dr_new)

    funding[cn] = f


def _run_phase3_for_class(
    cn: str,
    i: int,
    year: int,
    funding: dict,
    agg: pd.DataFrame,
    ctx: FundingContext,
    start_year: int,
) -> None:
    """Execute phase 3 for one class or DROP frame."""
    f = funding[cn]
    _phase_ual_and_funded_ratios(f, i)
    _maybe_accumulate(ctx, agg, f, i, ["total_ava"])
    _maybe_accumulate(ctx, agg, f, i, ["ual_ava_legacy", "ual_ava_new", "total_ual_ava"])
    _maybe_accumulate(ctx, agg, f, i, ["ual_mva_legacy", "ual_mva_new", "total_ual_mva"])

    _phase_er_cont_totals(f, i, ctx)
    _maybe_accumulate(ctx, agg, f, i, ["total_er_cont"])

    _set_total_contribution_rate(f, i)
    if ctx.ava_strategy.emits_real_cost_metrics:
        _phase_real_cost_metrics(f, i, year, start_year, ctx.inflation)

    funding[cn] = f
def _compute_funding(
    liability_results: dict,
    funding_inputs: dict,
    constants,
) -> dict:
    """Run the funding model for any plan.

    A single compute function that handles any AVA smoothing method,
    contribution policy, class count, and DC/CB/DROP capability. Path
    selection is config-driven via :class:`FundingContext`:
    ``ava_strategy`` and ``cont_strategy`` come from
    plan_config.json; capability flags (``has_dc``, ``has_cb``,
    ``has_drop``, ``is_multi_class``) gate the appropriate code paths
    inside the year loop.

    Returns:
        Dict mapping class_name -> funding DataFrame, plus an
        aggregate frame keyed by ``constants.plan_name``. For
        single-class plans the aggregate is a distinct copy of the
        sole class frame (no DataFrame aliasing). Plans with
        ``has_drop=true`` also get a ``"drop"`` frame.
    """
    ctx = resolve_funding_context(constants, funding_inputs)
    dr_current = ctx.dr_current
    dr_new = ctx.dr_new
    start_year = ctx.start_year
    n_years = ctx.n_years
    agg_name = ctx.agg_name
    return_scen_col = ctx.return_scen_col
    ret_scen = _prepare_return_scenarios(ctx, dr_current)

    funding = setup_funding_frames(ctx)
    calibrate_funding_frames(funding, liability_results, ctx, constants)
    amort_state = setup_amort_state(ctx, funding, constants)

    for i in range(1, n_years):
        year = start_year + i
        agg = funding[agg_name]

        # --- Phase 1: payroll, benefits, NC, liability GL + AAL ---
        for cn in ctx.class_names:
            _run_phase1_for_class(cn, i, funding, liability_results, agg, ctx, dr_current, dr_new)

        if ctx.is_multi_class:
            _nc_rate_agg(agg, i, ctx)
        if ctx.has_drop:
            _phase_drop_projection(funding, agg, i, ctx)

        # --- Phase 2: contributions, ROA, cash flow, MVA, AVA prep ---
        for cn in ctx.all_classes:
            _run_phase2_for_class(
                cn, i, year, funding, agg, amort_state, ctx, constants,
                ctx.cont_strategy, ret_scen, return_scen_col, dr_current, dr_new,
            )

        if ctx.ava_strategy.aggregation_level == "plan":
            _phase_ava_corridor_smoothing(agg, i, ctx.ava_strategy, dr_current, dr_new)
            ctx.ava_strategy.allocate_to_classes(agg, funding, ctx.all_classes, i)
            _finalize_ava_with_drop(funding, agg, i, ctx)

        # --- Phase 3: UAL / funded ratios / contribution totals ---
        for cn in ctx.all_classes:
            _run_phase3_for_class(cn, i, year, funding, agg, ctx, start_year)

        if ctx.is_multi_class:
            _finalize_aggregate_row(agg, i)

        _phase_amort_rolling(funding, amort_state, i, ctx)

    # For single-class plans the aggregate is a distinct copy of the
    # sole class frame (no aliasing). Multi-class plans built the
    # aggregate via _maybe_accumulate during the loop.
    if not ctx.is_multi_class:
        funding[agg_name] = funding[ctx.class_names[0]].copy()

    return funding
