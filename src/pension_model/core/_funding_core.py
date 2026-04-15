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
    ava_strategy = ctx.ava_strategy
    cont_strategy = ctx.cont_strategy

    ret_scen = _prepare_return_scenarios(ctx, dr_current)

    funding = setup_funding_frames(ctx)
    calibrate_funding_frames(funding, liability_results, ctx, constants)
    amort_state = setup_amort_state(ctx, funding, constants)

    for i in range(1, n_years):
        year = start_year + i
        agg = funding[agg_name]

        # --- Phase 1: payroll, benefits, NC, liability GL + AAL ---
        for cn in ctx.class_names:
            f = funding[cn]
            liab = liability_results[cn]

            _phase_payroll(f, i, ctx)
            _maybe_accumulate(ctx, agg, f, i, [
                "total_payroll", "payroll_db_legacy", "payroll_db_new",
            ])
            if ctx.has_dc:
                _maybe_accumulate(ctx, agg, f, i, [
                    "payroll_dc_legacy", "payroll_dc_new",
                ])

            _phase_benefits_refunds(f, liab, i, ctx)
            if "total_ben_payment" in f.columns:
                f.loc[i, "total_ben_payment"] = f.loc[i, "ben_payment_legacy"] + f.loc[i, "ben_payment_new"]
            if "total_refund" in f.columns:
                f.loc[i, "total_refund"] = f.loc[i, "refund_legacy"] + f.loc[i, "refund_new"]
            _maybe_accumulate(ctx, agg, f, i, [
                "ben_payment_legacy", "refund_legacy",
                "ben_payment_new", "refund_new",
            ])
            if "total_ben_payment" in f.columns:
                _maybe_accumulate(ctx, agg, f, i, ["total_ben_payment", "total_refund"])

            _phase_normal_cost(f, i, ctx)
            _maybe_accumulate(ctx, agg, f, i, ["nc_legacy", "nc_new"])

            _phase_liability_gl_and_aal(f, liab, i, dr_current, dr_new)
            _maybe_accumulate(ctx, agg, f, i, ["aal_legacy", "aal_new", "total_aal"])

            if ctx.ava_strategy.emits_liability_gain_loss_sum:
                f.loc[i, "liability_gain_loss"] = (
                    f.loc[i, "liability_gain_loss_legacy"]
                    + f.loc[i, "liability_gain_loss_new"]
                )

            funding[cn] = f

        if ctx.is_multi_class:
            _nc_rate_agg(agg, i, ctx)
        if ctx.has_drop:
            _phase_drop_projection(funding, agg, i, ctx)

        # --- Phase 2: contributions, ROA, cash flow, MVA, AVA prep ---
        for cn in ctx.all_classes:
            f = funding[cn]
            amo = select_amo_state(amort_state, cn)

            cont_strategy.compute_rates(f, i, year, amo)

            if ctx.has_dc:
                if cn == "drop":
                    f.loc[i, "er_dc_rate_legacy"] = 0
                    f.loc[i, "er_dc_rate_new"] = 0
                else:
                    dc_rate = constants.class_data[cn].er_dc_cont_rate
                    f.loc[i, "er_dc_rate_legacy"] = dc_rate
                    f.loc[i, "er_dc_rate_new"] = dc_rate

            _phase_contributions(f, i, ctx)
            _maybe_accumulate(ctx, agg, f, i, ["ee_nc_cont_legacy", "ee_nc_cont_new"])
            _maybe_accumulate(ctx, agg, f, i, ["admin_exp_legacy", "admin_exp_new"])

            if ctx.is_multi_class:
                if "total_er_db_cont" in ctx.init_funding.columns:
                    f.loc[i, "total_er_db_cont"] = (
                        f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
                        + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"]
                    )
                _maybe_accumulate(ctx, agg, f, i, [
                    "er_nc_cont_legacy", "er_nc_cont_new",
                    "er_amo_cont_legacy", "er_amo_cont_new",
                ])
                if "total_er_db_cont" in ctx.init_funding.columns:
                    _maybe_accumulate(ctx, agg, f, i, ["total_er_db_cont"])

            if ctx.has_dc:
                _phase_dc_contributions(f, i)
                _maybe_accumulate(ctx, agg, f, i, [
                    "er_dc_cont_legacy", "er_dc_cont_new", "total_er_dc_cont",
                ])

            roa_row = ret_scen[ret_scen["year"] == year]
            roa = roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current
            f.loc[i, "roa"] = roa
            if ctx.is_multi_class:
                agg.loc[i, "roa"] = roa

            _phase_cash_flow_and_solvency(f, i, roa)
            _maybe_accumulate(ctx, agg, f, i, ["net_cf_legacy", "net_cf_new"])

            _phase_mva(f, i, roa)
            _maybe_accumulate(ctx, agg, f, i, ["mva_legacy", "mva_new", "total_mva"])

            if ctx.ava_strategy.aggregation_level == "plan":
                f.loc[i, "ava_base_legacy"] = f.loc[i - 1, "ava_legacy"] + f.loc[i, "net_cf_legacy"] / 2
                f.loc[i, "ava_base_new"] = f.loc[i - 1, "ava_new"] + f.loc[i, "net_cf_new"] / 2

            if ctx.ava_strategy.aggregation_level == "class":
                _phase_ava_gainloss_smoothing(f, i, ava_strategy, dr_current, dr_new)

            funding[cn] = f

        if ctx.ava_strategy.aggregation_level == "plan":
            _phase_ava_corridor_smoothing(agg, i, ava_strategy, dr_current, dr_new)
            ava_strategy.allocate_to_classes(agg, funding, ctx.all_classes, i)
            _finalize_ava_with_drop(funding, agg, i, ctx)

        # --- Phase 3: UAL / funded ratios / contribution totals ---
        for cn in ctx.all_classes:
            f = funding[cn]
            _phase_ual_and_funded_ratios(f, i)
            _maybe_accumulate(ctx, agg, f, i, ["total_ava"])
            _maybe_accumulate(ctx, agg, f, i, [
                "ual_ava_legacy", "ual_ava_new", "total_ual_ava",
            ])
            _maybe_accumulate(ctx, agg, f, i, [
                "ual_mva_legacy", "ual_mva_new", "total_ual_mva",
            ])

            _phase_er_cont_totals(f, i, ctx)
            _maybe_accumulate(ctx, agg, f, i, ["total_er_cont"])

            if "tot_cont_rate" in f.columns:
                f.loc[i, "tot_cont_rate"] = (
                    (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
                     + f.loc[i, "er_amo_cont_legacy"]
                     + f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
                     + f.loc[i, "er_amo_cont_new"] + f.loc[i, "solv_cont"])
                    / f.loc[i, "total_payroll"]
                ) if f.loc[i, "total_payroll"] > 0 else 0

            if ctx.ava_strategy.emits_real_cost_metrics:
                _phase_real_cost_metrics(f, i, year, start_year, ctx.inflation)

            funding[cn] = f

        if ctx.is_multi_class:
            agg.loc[i, "fr_mva"] = agg.loc[i, "total_mva"] / agg.loc[i, "total_aal"] if agg.loc[i, "total_aal"] != 0 else 0
            agg.loc[i, "fr_ava"] = agg.loc[i, "total_ava"] / agg.loc[i, "total_aal"] if agg.loc[i, "total_aal"] != 0 else 0
            agg.loc[i, "total_er_cont_rate"] = agg.loc[i, "total_er_cont"] / agg.loc[i, "total_payroll"] if agg.loc[i, "total_payroll"] > 0 else 0

        _phase_amort_rolling(funding, amort_state, i, ctx)

    # For single-class plans the aggregate is a distinct copy of the
    # sole class frame (no aliasing). Multi-class plans built the
    # aggregate via _maybe_accumulate during the loop.
    if not ctx.is_multi_class:
        funding[agg_name] = funding[ctx.class_names[0]].copy()

    return funding
