"""
Funding model core: the two compute functions.

This module holds the two long-running funding compute functions —
``_compute_funding_corridor`` (5-year corridor smoothing, multi-class
plan-aggregate) and ``_compute_funding_gainloss`` (4-year gain/loss
deferral, single-class) — moved out of ``funding_model.py`` so the
public module is a thin entry point.

Both functions receive their AVA smoothing strategy and contribution
strategy by direct instantiation; ``run_funding_model`` (in
``funding_model.py``) selects which core function to call based on the
``funding.ava_smoothing.method`` config field, not on class count.

The two function bodies remain separate by design: a single merged
year loop would have to handle ~12 schema and control-flow differences
between the corridor and gain/loss paths via column-presence detection
and multiple config flags, and a single misplaced operation would
silently break R-baseline reproduction. The strategy abstractions and
helpers in ``_funding_helpers.py`` and ``_funding_strategies.py``
already give a future plan everything it needs to add a third path
without changing either of these functions.

Bit-identity constraints (preserved from the original implementations):
  * Mid-year exponent ``(1 + dr) ** 0.5`` is computed inside helpers
    from a scalar ``dr``, never from a precomputed ``sqrt_factor``.
  * Aggregate accumulation order matches the original single-cell
    write order; do not convert to bulk ``f.loc[i, cols] = values``.
  * The corridor function uses ``agg`` as the local variable name for
    the plan-aggregate frame; the original code called it ``frs``.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from pension_model.core.pipeline import _get_pmt
from pension_model.core._funding_helpers import (
    _aal_rollforward,
    _accumulate_to_aggregate,
    _get_init_row,
    _mva_rollforward,
    _populate_calibrated_nc_rates,
    _roll_amort_layer,
    _solvency_cont,
)
from pension_model.core._funding_strategies import (
    ActuarialContributions,
    CorridorSmoothing,
    GainLossSmoothing,
    RateComponent,
    StatutoryContributions,
)


@dataclass
class FundingContext:
    """Resolved configuration for one funding compute run.

    A container for scalars, flags, strategies, and pre-loaded frames
    that both ``_compute_funding_corridor`` and
    ``_compute_funding_gainloss`` need during setup and year-loop
    execution. Built once per call via :func:`_resolve_funding_context`.

    Having a single dataclass means adding a new config field or flag
    involves one parse point, not two; and the year-loop phase helpers
    (Step 2.E) take ``ctx: FundingContext`` rather than ~15 loose
    scalars.
    """

    # Scalars — economic and funding parameters
    dr_current: float
    dr_new: float
    dr_old: Optional[float]
    payroll_growth: float
    inflation: float
    amo_pay_growth: float
    amo_period_new: int
    funding_lag: int
    db_ee_cont_rate: float
    model_return: float
    start_year: int
    n_years: int

    # Strategies
    ava_strategy: Any
    cont_strategy: Any

    # Class iteration
    class_names: list
    agg_name: str
    has_drop: bool
    drop_ref_class: Optional[str]
    all_classes: list  # class_names + ["drop"] if has_drop

    # Plan capabilities — derived from config or schema; each field
    # earns its place via at least one phase-helper consumer.
    has_cb: bool  # cash-balance leg present (benefit_types contains "cb")
    has_dc: bool  # DC leg flows through the funding frame (schema-driven)

    # Raw config sub-maps (for legacy paths that still read funding_raw)
    funding_policy: str
    return_scen_col: str

    # Input frames
    init_funding: pd.DataFrame
    amort_layers: Optional[pd.DataFrame]

    # Return-scenario frame — prepared per strategy (Step 2.F will move
    # the prep into a dedicated helper).
    ret_scen: pd.DataFrame = field(default_factory=pd.DataFrame)


def _resolve_funding_context(
    constants,
    funding_inputs: dict,
) -> FundingContext:
    """Build a :class:`FundingContext` from the plan config and inputs.

    Reads ``constants.economic``, ``constants.funding``,
    ``constants.ranges``, and ``constants.raw`` to extract all scalars,
    flags, and strategy selections a funding compute run needs.

    Selects ``ava_strategy`` from ``funding.ava_smoothing.method``
    (``"corridor"`` → ``CorridorSmoothing``; ``"gain_loss"`` →
    ``GainLossSmoothing``) and ``cont_strategy`` from whether
    ``funding.statutory_rates`` is present in config (→
    ``StatutoryContributions``) or not (→ ``ActuarialContributions``).

    The ``ret_scen`` frame is returned unmodified from
    ``funding_inputs["return_scenarios"]``; strategy-dependent
    overrides are applied by the caller.
    """
    econ = constants.economic
    fund = constants.funding
    r = constants.ranges
    raw = constants.raw if hasattr(constants, "raw") else {}
    funding_raw = raw.get("funding", {})

    # amo_method normalization (legacy pre-Phase-3 code path)
    amo_method = fund.amo_method if hasattr(fund, "amo_method") else "level_pct"
    amo_pay_growth = fund.amo_pay_growth
    if amo_method == "level $":
        amo_pay_growth = 0

    # Class / DROP topology
    class_names = list(constants.classes)
    agg_name = constants.plan_name
    has_drop = funding_raw.get("has_drop", False)
    drop_ref_class = funding_raw.get("drop_reference_class", class_names[0]) if class_names else None
    all_classes = class_names + (["drop"] if has_drop else [])

    # Plan capabilities
    has_cb = "cb" in constants.benefit_types
    # has_dc is schema-driven: TRS has "dc" in benefit_types but its ORP
    # is outside the trust and its funding frame has no DC columns, so
    # benefit_types is the wrong source. The init_funding schema is
    # authoritative for what columns the funding model expects to read/write.
    has_dc = "payroll_dc_legacy" in funding_inputs["init_funding"].columns

    # Strategy selection
    method = (fund.ava_smoothing or {}).get("method")
    if method == "corridor":
        ava_strategy = CorridorSmoothing()
    elif method == "gain_loss":
        ava_strategy = GainLossSmoothing()
    else:
        raise ValueError(
            f"Unknown funding.ava_smoothing.method: {method!r}. "
            f"Supported: 'corridor', 'gain_loss'."
        )

    stat_rates = funding_raw.get("statutory_rates")
    if stat_rates:
        ee_schedule = stat_rates.get(
            "ee_rate_schedule",
            [{"from_year": 0, "rate": constants.benefit.db_ee_cont_rate}],
        )
        cont_strategy = StatutoryContributions(
            funding_policy=fund.funding_policy,
            ee_schedule=ee_schedule,
            components=_resolve_er_rate_components(funding_raw),
        )
    else:
        cont_strategy = ActuarialContributions(
            db_ee_cont_rate=constants.benefit.db_ee_cont_rate,
        )

    return FundingContext(
        dr_current=econ.dr_current,
        dr_new=econ.dr_new,
        dr_old=getattr(econ, "dr_old", None),
        payroll_growth=econ.payroll_growth,
        inflation=econ.inflation,
        amo_pay_growth=amo_pay_growth,
        amo_period_new=fund.amo_period_new,
        funding_lag=getattr(fund, "funding_lag", 0),
        db_ee_cont_rate=constants.benefit.db_ee_cont_rate,
        model_return=econ.model_return,
        start_year=r.start_year,
        n_years=r.model_period + 1,
        ava_strategy=ava_strategy,
        cont_strategy=cont_strategy,
        class_names=class_names,
        agg_name=agg_name,
        has_drop=has_drop,
        drop_ref_class=drop_ref_class,
        all_classes=all_classes,
        has_cb=has_cb,
        has_dc=has_dc,
        funding_policy=fund.funding_policy,
        return_scen_col=raw.get("economic", {}).get("return_scen", "assumption"),
        init_funding=funding_inputs["init_funding"],
        amort_layers=funding_inputs.get("amort_layers"),
        ret_scen=funding_inputs["return_scenarios"].copy(),
    )


def _resolve_er_rate_components(funding_raw: dict) -> list:
    """Build the list of statutory employer rate components from config.

    Reads ``funding.statutory_rates.er_rate_components`` (a list of
    component dicts) and returns the corresponding list of
    ``RateComponent`` objects. Each dict is passed to
    ``RateComponent.from_config``.

    A plan that uses the statutory contribution strategy must declare
    its components explicitly — there are no hardcoded defaults.
    """
    stat_rates = funding_raw.get("statutory_rates", {})
    components = stat_rates.get("er_rate_components")
    if components is None:
        raise ValueError(
            "funding.statutory_rates.er_rate_components is required when "
            "using the statutory contribution strategy. See "
            "plans/txtrs/config/plan_config.json for an example schema."
        )
    return [RateComponent.from_config(c) for c in components]


# ---------------------------------------------------------------------------
# Year-loop phase helpers
#
# Each helper executes one phase of the year loop for one class's funding
# frame. They're called from both compute functions with the same
# signature so the two bodies converge on a common shape.
# ---------------------------------------------------------------------------


def _phase_payroll(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    """Project payroll columns for row ``i`` on one class's frame.

    Writes ``total_payroll``, ``payroll_db_legacy``, ``payroll_db_new``,
    and (when the plan has a cash-balance leg) ``payroll_cb_new``.

    DC-leg payroll (``payroll_dc_legacy`` / ``payroll_dc_new``) and
    plan-aggregate accumulation remain at the call site for now; they
    move into helpers in later phase-extraction commits.
    """
    f.loc[i, "total_payroll"] = f.loc[i - 1, "total_payroll"] * (1 + ctx.payroll_growth)
    f.loc[i, "payroll_db_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_legacy_ratio"]
    f.loc[i, "payroll_db_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_new_ratio"]
    if ctx.has_cb:
        f.loc[i, "payroll_cb_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_cb_new_ratio"]
    if ctx.has_dc:
        f.loc[i, "payroll_dc_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_legacy_ratio"]
        f.loc[i, "payroll_dc_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_new_ratio"]


def _phase_dc_contributions(f: pd.DataFrame, i: int) -> None:
    """Compute DC employer contribution dollars for one class's row.

    Writes ``er_dc_cont_legacy``, ``er_dc_cont_new``, and the total
    ``total_er_dc_cont``. Assumes the per-leg DC rates
    (``er_dc_rate_legacy/new``) and DC payrolls have already been
    written onto the row — DC rates are set at the call site because
    they depend on plan config (the class's ``er_dc_cont_rate``) and
    on DROP-cohort special-casing.

    Used only when the plan has a DC leg flowing through the funding
    frame (``ctx.has_dc``).
    """
    f.loc[i, "er_dc_cont_legacy"] = f.loc[i, "er_dc_rate_legacy"] * f.loc[i, "payroll_dc_legacy"]
    f.loc[i, "er_dc_cont_new"] = f.loc[i, "er_dc_rate_new"] * f.loc[i, "payroll_dc_new"]
    f.loc[i, "total_er_dc_cont"] = f.loc[i, "er_dc_cont_legacy"] + f.loc[i, "er_dc_cont_new"]


def _phase_benefits_refunds(
    f: pd.DataFrame, liab: pd.DataFrame, i: int, ctx: FundingContext
) -> None:
    """Copy benefit payments and refunds from the liability pipeline.

    Writes ``ben_payment_legacy`` (active + current retiree + term),
    ``refund_legacy``, ``ben_payment_new``, and ``refund_new``. For
    plans with a cash-balance leg, CB contributions are added to the
    ``*_new`` columns; for DB-only plans, only the DB component is
    read.

    Plan-aggregate totals (``total_ben_payment``, ``total_refund``)
    and aggregate accumulation remain at the call site because they're
    corridor-only.
    """
    f.loc[i, "ben_payment_legacy"] = (
        liab["retire_ben_db_legacy_est"].iloc[i]
        + liab["retire_ben_current_est"].iloc[i]
        + liab["retire_ben_term_est"].iloc[i]
    )
    f.loc[i, "refund_legacy"] = liab["refund_db_legacy_est"].iloc[i]

    ben_new = liab["retire_ben_db_new_est"].iloc[i]
    refund_new = liab["refund_db_new_est"].iloc[i]
    if ctx.has_cb:
        ben_new = ben_new + liab["retire_ben_cb_new_est"].iloc[i]
        refund_new = refund_new + liab["refund_cb_new_est"].iloc[i]
    f.loc[i, "ben_payment_new"] = ben_new
    f.loc[i, "refund_new"] = refund_new


def _prepare_return_scenarios(ctx: FundingContext, dr_current: float) -> pd.DataFrame:
    """Apply projection overrides to the return-scenarios frame.

    ``ret_scen["model"]`` and ``ret_scen["assumption"]`` get written
    with ``ctx.model_return`` and ``dr_current`` respectively. The AVA
    strategy decides whether the override applies to all rows or only
    to projected rows (year >= start_year + 2) — corridor preserves
    the first two rows' CSV values; gainloss overrides unconditionally.

    Mutates a copy of ``ctx.ret_scen`` and returns it; ctx is unchanged.
    """
    rs = ctx.ret_scen
    if ctx.ava_strategy.ret_scen_gates_projection:
        first_proj_year = ctx.start_year + 2
        mask = rs["year"] >= first_proj_year
        rs.loc[mask, "model"] = ctx.model_return
        rs.loc[mask, "assumption"] = dr_current
    else:
        rs["model"] = ctx.model_return
        rs["assumption"] = dr_current
    return rs


def _nc_rate_agg(agg: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    """Write ``nc_rate`` on the aggregate frame using the canonical
    denominator (DB legacy + DB new + CB new when applicable).

    Used by the corridor path to recompute the plan-aggregate NC rate
    after the class loop and again after DROP contributions have been
    accumulated in.
    """
    denom = agg.loc[i, "payroll_db_legacy"] + agg.loc[i, "payroll_db_new"]
    if ctx.has_cb:
        denom = denom + agg.loc[i, "payroll_cb_new"]
    agg.loc[i, "nc_rate"] = (agg.loc[i, "nc_legacy"] + agg.loc[i, "nc_new"]) / denom if denom > 0 else 0


def _phase_normal_cost(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    """Compute normal-cost dollars and rate for row ``i`` on one class's frame.

    Writes ``nc_legacy``, ``nc_new``, and ``nc_rate``. The new-leg NC
    includes a CB component (``nc_rate_cb_new * payroll_cb_new``) for
    plans with a cash-balance leg.

    ``nc_rate`` uses the canonical denominator — the payroll on which
    normal cost dollars are actually accrued: DB legacy + DB new + CB
    new (when present). This excludes DC payroll (which accrues no DB
    normal cost) and matches the TRS AV's "Projected Payroll for
    Contributions" definition. See GH #42 for the research and
    migration notes.
    """
    f.loc[i, "nc_legacy"] = f.loc[i, "nc_rate_db_legacy"] * f.loc[i, "payroll_db_legacy"]
    nc_new = f.loc[i, "nc_rate_db_new"] * f.loc[i, "payroll_db_new"]
    denom = f.loc[i, "payroll_db_legacy"] + f.loc[i, "payroll_db_new"]
    if ctx.has_cb:
        nc_new = nc_new + f.loc[i, "nc_rate_cb_new"] * f.loc[i, "payroll_cb_new"]
        denom = denom + f.loc[i, "payroll_cb_new"]
    f.loc[i, "nc_new"] = nc_new
    f.loc[i, "nc_rate"] = (f.loc[i, "nc_legacy"] + nc_new) / denom if denom > 0 else 0


def _phase_drop_projection(
    funding: dict, agg: pd.DataFrame, i: int, ctx: FundingContext
) -> None:
    """Project the DROP cohort and accumulate it into the aggregate.

    Scales the DROP frame's payroll by ``ctx.payroll_growth``, pulls
    benefit/refund shares from the reference class (``ctx.drop_ref_class``)
    using R's mechanical-share logic, reuses the aggregate's realized
    NC rates to compute DROP NC dollars, and rolls DROP AAL forward
    with a mid-year-cashflow convention.

    Then accumulates the DROP frame into ``agg`` and recomputes the
    aggregate's NC rate columns (which were computed in the class loop
    before DROP was added).

    Corridor-only: ``_compute_funding_gainloss`` has no DROP path.
    """
    drop = funding["drop"]
    reg = funding[ctx.drop_ref_class]

    drop.loc[i, "total_payroll"] = drop.loc[i - 1, "total_payroll"] * (1 + ctx.payroll_growth)
    drop.loc[i, "payroll_db_legacy"] = drop.loc[i, "total_payroll"] * (
        reg.loc[i, "payroll_db_legacy_ratio"] + reg.loc[i, "payroll_dc_legacy_ratio"]
    )
    drop.loc[i, "payroll_db_new"] = drop.loc[i, "total_payroll"] * (
        reg.loc[i, "payroll_db_new_ratio"] + reg.loc[i, "payroll_dc_new_ratio"]
    )

    if reg.loc[i - 1, "total_ben_payment"] > 0:
        drop.loc[i, "total_ben_payment"] = (
            drop.loc[i - 1, "total_ben_payment"]
            * reg.loc[i, "total_ben_payment"] / reg.loc[i - 1, "total_ben_payment"]
        )
    if reg.loc[i - 1, "total_refund"] > 0:
        drop.loc[i, "total_refund"] = (
            drop.loc[i - 1, "total_refund"]
            * reg.loc[i, "total_refund"] / reg.loc[i - 1, "total_refund"]
        )

    if reg.loc[i, "total_ben_payment"] > 0:
        drop.loc[i, "ben_payment_legacy"] = drop.loc[i, "total_ben_payment"] * reg.loc[i, "ben_payment_legacy"] / reg.loc[i, "total_ben_payment"]
        drop.loc[i, "ben_payment_new"] = drop.loc[i, "total_ben_payment"] * reg.loc[i, "ben_payment_new"] / reg.loc[i, "total_ben_payment"]
    if reg.loc[i, "total_refund"] > 0:
        drop.loc[i, "refund_legacy"] = drop.loc[i, "total_refund"] * reg.loc[i, "refund_legacy"] / reg.loc[i, "total_refund"]
        drop.loc[i, "refund_new"] = drop.loc[i, "total_refund"] * reg.loc[i, "refund_new"] / reg.loc[i, "total_refund"]

    drop.loc[i, "nc_rate_db_legacy"] = agg.loc[i, "nc_legacy"] / agg.loc[i, "payroll_db_legacy"] if agg.loc[i, "payroll_db_legacy"] > 0 else 0
    drop.loc[i, "nc_rate_db_new"] = agg.loc[i, "nc_new"] / agg.loc[i, "payroll_db_new"] if agg.loc[i, "payroll_db_new"] > 0 else 0
    drop.loc[i, "nc_legacy"] = drop.loc[i, "nc_rate_db_legacy"] * drop.loc[i, "payroll_db_legacy"]
    drop.loc[i, "nc_new"] = drop.loc[i, "nc_rate_db_new"] * drop.loc[i, "payroll_db_new"]

    drop.loc[i, "aal_legacy"] = (
        drop.loc[i - 1, "aal_legacy"] * (1 + ctx.dr_current)
        + (drop.loc[i, "nc_legacy"] - drop.loc[i, "ben_payment_legacy"] - drop.loc[i, "refund_legacy"])
        * (1 + ctx.dr_current) ** 0.5
    )
    drop.loc[i, "aal_new"] = (
        drop.loc[i - 1, "aal_new"] * (1 + ctx.dr_new)
        + (drop.loc[i, "nc_new"] - drop.loc[i, "ben_payment_new"] - drop.loc[i, "refund_new"])
        * (1 + ctx.dr_new) ** 0.5
    )
    drop.loc[i, "total_aal"] = drop.loc[i, "aal_legacy"] + drop.loc[i, "aal_new"]
    funding["drop"] = drop

    _accumulate_to_aggregate(agg, drop, i, [
        "total_payroll", "payroll_db_legacy", "payroll_db_new",
    ])
    _accumulate_to_aggregate(agg, drop, i, [
        "ben_payment_legacy", "refund_legacy",
        "ben_payment_new", "refund_new",
        "total_ben_payment", "total_refund",
    ])
    _accumulate_to_aggregate(agg, drop, i, ["nc_legacy", "nc_new"])

    _nc_rate_agg(agg, i, ctx)
    agg.loc[i, "nc_rate_db_legacy"] = agg.loc[i, "nc_legacy"] / agg.loc[i, "payroll_db_legacy"] if agg.loc[i, "payroll_db_legacy"] > 0 else 0
    agg.loc[i, "nc_rate_db_new"] = agg.loc[i, "nc_new"] / agg.loc[i, "payroll_db_new"] if agg.loc[i, "payroll_db_new"] > 0 else 0
    _accumulate_to_aggregate(agg, drop, i, [
        "aal_legacy", "aal_new", "total_aal",
    ])


def _finalize_ava_with_drop(
    funding: dict, agg: pd.DataFrame, i: int, ctx: FundingContext
) -> None:
    """Post-smoothing AVA finalization, with DROP reallocation when applicable.

    When ``ctx.has_drop``: computes the DROP's net AVA reallocation so
    that its AVA share matches its AAL share of the aggregate, applies
    it to the DROP frame, then redistributes the offset across the
    regular classes in proportion to their AAL.

    When no DROP: simply copies each class's ``unadj_ava_*`` to the
    final ``ava_*`` columns.

    Corridor-only: ``_compute_funding_gainloss`` is per-class smoothing
    and has no aggregate reallocation step.
    """
    if ctx.has_drop:
        drop = funding["drop"]
        if agg.loc[i, "aal_legacy"] != 0:
            drop.loc[i, "net_reallocation_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "aal_legacy"] * agg.loc[i, "ava_legacy"] / agg.loc[i, "aal_legacy"]
        drop.loc[i, "ava_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "net_reallocation_legacy"]
        if agg.loc[i, "aal_new"] != 0:
            drop.loc[i, "net_reallocation_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "aal_new"] * agg.loc[i, "ava_new"] / agg.loc[i, "aal_new"]
        drop.loc[i, "ava_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "net_reallocation_new"]
        funding["drop"] = drop

        for cn in ctx.class_names:
            f = funding[cn]
            agg_ex_drop_leg = agg.loc[i, "aal_legacy"] - drop.loc[i, "aal_legacy"]
            prop_leg = f.loc[i, "aal_legacy"] / agg_ex_drop_leg if agg_ex_drop_leg != 0 else 0
            f.loc[i, "net_reallocation_legacy"] = prop_leg * drop.loc[i, "net_reallocation_legacy"]
            f.loc[i, "ava_legacy"] = f.loc[i, "unadj_ava_legacy"] + f.loc[i, "net_reallocation_legacy"]

            agg_ex_drop_new = agg.loc[i, "aal_new"] - drop.loc[i, "aal_new"]
            prop_new = f.loc[i, "aal_new"] / agg_ex_drop_new if agg_ex_drop_new != 0 else 0
            f.loc[i, "net_reallocation_new"] = prop_new * drop.loc[i, "net_reallocation_new"]
            f.loc[i, "ava_new"] = f.loc[i, "unadj_ava_new"] + f.loc[i, "net_reallocation_new"]
            funding[cn] = f
    else:
        for cn in ctx.class_names:
            f = funding[cn]
            f.loc[i, "ava_legacy"] = f.loc[i, "unadj_ava_legacy"]
            f.loc[i, "ava_new"] = f.loc[i, "unadj_ava_new"]
            funding[cn] = f


def _phase_ava_corridor_smoothing(
    agg: pd.DataFrame, i: int, ava_strategy, dr_current: float, dr_new: float
) -> None:
    """Run plan-aggregate corridor AVA smoothing for both legs.

    Used for plans whose AVA strategy is plan-level (``aggregation_level
    == "plan"``). Calls ``ava_strategy.smooth`` once per leg against
    the aggregate frame and writes ``exp_inv_earnings_ava_*``,
    ``exp_ava_*``, ``ava_*``, ``alloc_inv_earnings_ava_*``, and
    ``ava_base_*`` onto ``agg.loc[i, :]``.

    The corridor strategy carries no extra state between years, so
    ``state`` is always an empty dict. The per-class reallocation of
    the aggregate's realized earnings is handled separately by
    ``ava_strategy.allocate_to_classes``.
    """
    for leg, dr in (("legacy", dr_current), ("new", dr_new)):
        result = ava_strategy.smooth(
            ava_prev=agg.loc[i - 1, f"ava_{leg}"],
            net_cf=agg.loc[i, f"net_cf_{leg}"],
            mva=agg.loc[i, f"mva_{leg}"],
            dr=dr,
            state={},
        )
        agg.loc[i, f"exp_inv_earnings_ava_{leg}"] = result["exp_inv_earnings_ava"]
        agg.loc[i, f"exp_ava_{leg}"] = result["exp_ava"]
        agg.loc[i, f"ava_{leg}"] = result["ava"]
        agg.loc[i, f"alloc_inv_earnings_ava_{leg}"] = result["alloc_inv_earnings_ava"]
        agg.loc[i, f"ava_base_{leg}"] = result["ava_base"]


def _phase_ava_gainloss_smoothing(
    f: pd.DataFrame, i: int, ava_strategy, dr_current: float, dr_new: float
) -> None:
    """Run per-leg AVA gain/loss deferral smoothing on one class's frame.

    Used for plans whose AVA strategy is class-level (``aggregation_level
    == "class"``). The 4-year deferral state is carried on the frame
    itself via ``defer_y1_*`` through ``defer_y4_*`` columns; the
    strategy's ``smooth`` method returns a dict of keys whose values
    are written to ``{k}_legacy`` and ``{k}_new`` columns.

    ``exp_inv_income`` / ``exp_ava`` / ``ava`` keys map to the usual
    column names; everything else (the defer_* keys) gets the leg
    suffix appended.
    """
    for leg, dr in (("legacy", dr_current), ("new", dr_new)):
        result = ava_strategy.smooth(
            ava_prev=f.loc[i - 1, f"ava_{leg}"],
            net_cf=f.loc[i, f"net_cf_{leg}"],
            mva=f.loc[i, f"mva_{leg}"],
            dr=dr,
            state={
                "defer_y1_prev": f.loc[i - 1, f"defer_y1_{leg}"],
                "defer_y2_prev": f.loc[i - 1, f"defer_y2_{leg}"],
                "defer_y3_prev": f.loc[i - 1, f"defer_y3_{leg}"],
                "defer_y4_prev": f.loc[i - 1, f"defer_y4_{leg}"],
            },
        )
        for k, v in result.items():
            if k == "exp_inv_income":
                f.loc[i, f"exp_inv_income_{leg}"] = v
            elif k == "exp_ava":
                f.loc[i, f"exp_ava_{leg}"] = v
            elif k == "ava":
                f.loc[i, f"ava_{leg}"] = v
            else:
                f.loc[i, f"{k}_{leg}"] = v


def _phase_real_cost_metrics(
    f: pd.DataFrame, i: int, year: int, start_year: int, inflation: float
) -> None:
    """Write inflation-adjusted cost metrics for one row.

    Deflates ``total_er_cont`` and ``total_ual_mva`` to real terms
    using the supplied ``inflation`` rate, accumulates cumulative real
    ER contributions, and writes the ``all_in_cost_real`` = cumulative
    real cost + end-of-horizon real UAL summary.

    Gainloss-path-only today; the unified compute will gate this on
    a plan-capability flag.
    """
    deflator = (1 + inflation) ** (year - start_year)
    f.loc[i, "total_er_cont_real"] = f.loc[i, "total_er_cont"] / deflator
    f.loc[i, "cum_er_cont_real"] = (
        f.loc[i, "total_er_cont_real"] if i == 1
        else f.loc[i - 1, "cum_er_cont_real"] + f.loc[i, "total_er_cont_real"]
    )
    f.loc[i, "total_ual_mva_real"] = f.loc[i, "total_ual_mva"] / deflator
    f.loc[i, "all_in_cost_real"] = f.loc[i, "cum_er_cont_real"] + f.loc[i, "total_ual_mva_real"]


def _phase_er_cont_totals(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    """Write aggregate employer contribution dollars and rate.

    ``total_er_cont`` is the sum of all employer outflows that hit
    the plan in year ``i``: ER NC, ER amortization, ER DC (when the
    plan has a DC leg), and the solvency contribution. ``total_er_cont_rate``
    is that total divided by total payroll.

    Written for every class (and the aggregate, via ``_accumulate_to_aggregate``
    followed by a caller-side rate re-division for the aggregate).
    """
    total = (
        f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
        + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"]
        + f.loc[i, "solv_cont"]
    )
    if ctx.has_dc:
        total = total + f.loc[i, "total_er_dc_cont"]
    f.loc[i, "total_er_cont"] = total
    total_payroll = f.loc[i, "total_payroll"]
    f.loc[i, "total_er_cont_rate"] = total / total_payroll if total_payroll > 0 else 0


def _phase_ual_and_funded_ratios(f: pd.DataFrame, i: int) -> None:
    """Compute total AVA, UAL (on both AVA and MVA bases), and funded
    ratios for row ``i`` on one class's frame.

    Writes ``total_ava``, ``ual_ava_legacy/new``, ``total_ual_ava``,
    ``ual_mva_legacy/new``, ``total_ual_mva``, ``fr_mva``, and
    ``fr_ava``. Reads the already-written ``ava_legacy/new``,
    ``aal_legacy/new``, ``total_aal``, ``mva_legacy/new``,
    ``total_mva``.
    """
    f.loc[i, "total_ava"] = f.loc[i, "ava_legacy"] + f.loc[i, "ava_new"]

    f.loc[i, "ual_ava_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "ava_legacy"]
    f.loc[i, "ual_ava_new"] = f.loc[i, "aal_new"] - f.loc[i, "ava_new"]
    f.loc[i, "total_ual_ava"] = f.loc[i, "ual_ava_legacy"] + f.loc[i, "ual_ava_new"]

    f.loc[i, "ual_mva_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "mva_legacy"]
    f.loc[i, "ual_mva_new"] = f.loc[i, "aal_new"] - f.loc[i, "mva_new"]
    f.loc[i, "total_ual_mva"] = f.loc[i, "ual_mva_legacy"] + f.loc[i, "ual_mva_new"]

    total_aal = f.loc[i, "total_aal"]
    f.loc[i, "fr_mva"] = f.loc[i, "total_mva"] / total_aal if total_aal != 0 else 0
    f.loc[i, "fr_ava"] = f.loc[i, "total_ava"] / total_aal if total_aal != 0 else 0


def _phase_contributions(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    """Compute admin-expense rate and per-leg contribution dollars.

    Reads rates that the contribution strategy has already written via
    ``cont_strategy.compute_rates`` (``ee_nc_rate_*``, ``er_nc_rate_*``,
    ``amo_rate_*``) and multiplies them by the applicable payroll
    bases, writing eight dollar columns:

        ee_nc_cont_legacy, ee_nc_cont_new
        admin_exp_legacy, admin_exp_new
        er_nc_cont_legacy, er_nc_cont_new       (includes admin_exp)
        er_amo_cont_legacy, er_amo_cont_new

    Also rolls ``admin_exp_rate`` forward from the prior row.

    The new-leg denominator is ``payroll_db_new + payroll_cb_new``
    when the plan has a cash-balance leg, else ``payroll_db_new``
    alone. Applies to EE, admin, ER NC, and ER amo for the new leg.

    Amortization uses the statutory (DB-payroll-denominator)
    convention for both legs — the only convention exercised by
    current plans.
    """
    f.loc[i, "admin_exp_rate"] = f.loc[i - 1, "admin_exp_rate"]

    payroll_new = f.loc[i, "payroll_db_new"]
    if ctx.has_cb:
        payroll_new = payroll_new + f.loc[i, "payroll_cb_new"]

    f.loc[i, "ee_nc_cont_legacy"] = f.loc[i, "ee_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
    f.loc[i, "ee_nc_cont_new"] = f.loc[i, "ee_nc_rate_new"] * payroll_new

    f.loc[i, "admin_exp_legacy"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_legacy"]
    f.loc[i, "admin_exp_new"] = f.loc[i, "admin_exp_rate"] * payroll_new

    f.loc[i, "er_nc_cont_legacy"] = (
        f.loc[i, "er_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
        + f.loc[i, "admin_exp_legacy"]
    )
    f.loc[i, "er_nc_cont_new"] = (
        f.loc[i, "er_nc_rate_new"] * payroll_new
        + f.loc[i, "admin_exp_new"]
    )

    f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
    f.loc[i, "er_amo_cont_new"] = f.loc[i, "amo_rate_new"] * payroll_new


def _phase_cash_flow_and_solvency(f: pd.DataFrame, i: int, roa: float) -> None:
    """Compute DB cash flows, the solvency contribution, and net cash flow.

    Reads per-leg contributions (``ee_nc_cont_*``, ``er_nc_cont_*``,
    ``er_amo_cont_*``, ``admin_exp_*``) and liability outflows
    (``ben_payment_*``, ``refund_*``) off the frame for year ``i``.

    Writes ``solv_cont`` (the aggregate solvency top-up required to
    keep MVA non-negative), splits it across legs by AAL share, and
    writes ``net_cf_legacy`` / ``net_cf_new`` — the operational cash
    flow that feeds the MVA roll-forward.

    DC contributions are deliberately excluded from cash flow: DC money
    is paid directly to member accounts and never flows through the DB
    fund.
    """
    cf_legacy = (
        f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
        + f.loc[i, "er_amo_cont_legacy"] - f.loc[i, "ben_payment_legacy"]
        - f.loc[i, "refund_legacy"] - f.loc[i, "admin_exp_legacy"]
    )
    cf_new = (
        f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
        + f.loc[i, "er_amo_cont_new"] - f.loc[i, "ben_payment_new"]
        - f.loc[i, "refund_new"] - f.loc[i, "admin_exp_new"]
    )

    f.loc[i, "solv_cont"] = _solvency_cont(
        mva_prev=f.loc[i - 1, "total_mva"],
        cf_total=cf_legacy + cf_new,
        roa=roa,
    )
    if f.loc[i, "total_aal"] > 0:
        f.loc[i, "solv_cont_legacy"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_legacy"] / f.loc[i, "total_aal"]
        f.loc[i, "solv_cont_new"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_new"] / f.loc[i, "total_aal"]

    f.loc[i, "net_cf_legacy"] = cf_legacy + f.loc[i, "solv_cont_legacy"]
    f.loc[i, "net_cf_new"] = cf_new + f.loc[i, "solv_cont_new"]


def _phase_mva(f: pd.DataFrame, i: int, roa: float) -> None:
    """Roll MVA forward one year for both legs.

    Reads ``net_cf_legacy`` / ``net_cf_new`` and the prior-year
    ``mva_legacy`` / ``mva_new`` off the frame and writes the new
    year's ``mva_legacy``, ``mva_new``, and ``total_mva``.

    The caller is responsible for having written ``net_cf_*`` first
    (i.e. contributions, solvency, and the net cash-flow combination
    must already be done on row ``i``).
    """
    f.loc[i, "mva_legacy"] = _mva_rollforward(
        f.loc[i - 1, "mva_legacy"], f.loc[i, "net_cf_legacy"], roa)
    f.loc[i, "mva_new"] = _mva_rollforward(
        f.loc[i - 1, "mva_new"], f.loc[i, "net_cf_new"], roa)
    f.loc[i, "total_mva"] = f.loc[i, "mva_legacy"] + f.loc[i, "mva_new"]


def _phase_liability_gl_and_aal(
    f: pd.DataFrame, liab: pd.DataFrame, i: int, dr_current: float, dr_new: float
) -> None:
    """Copy liability gain/loss and roll the AAL forward for both legs.

    Reads ``liability_gain_loss_legacy_est`` / ``liability_gain_loss_new_est``
    from the liability pipeline output (always populated — see
    pipeline.py), runs ``_aal_rollforward`` for each leg, and writes
    ``aal_legacy``, ``aal_new``, ``total_aal``.

    The gainloss-path ``liability_gain_loss = legacy + new`` sum column
    is corridor-schema-absent and stays inline in that caller.
    """
    f.loc[i, "liability_gain_loss_legacy"] = liab["liability_gain_loss_legacy_est"].iloc[i]
    f.loc[i, "liability_gain_loss_new"] = liab["liability_gain_loss_new_est"].iloc[i]

    f.loc[i, "aal_legacy"] = _aal_rollforward(
        aal_prev=f.loc[i - 1, "aal_legacy"],
        nc=f.loc[i, "nc_legacy"],
        ben=f.loc[i, "ben_payment_legacy"],
        refund=f.loc[i, "refund_legacy"],
        liab_gl=f.loc[i, "liability_gain_loss_legacy"],
        dr=dr_current,
    )
    f.loc[i, "aal_new"] = _aal_rollforward(
        aal_prev=f.loc[i - 1, "aal_new"],
        nc=f.loc[i, "nc_new"],
        ben=f.loc[i, "ben_payment_new"],
        refund=f.loc[i, "refund_new"],
        liab_gl=f.loc[i, "liability_gain_loss_new"],
        dr=dr_new,
    )
    f.loc[i, "total_aal"] = f.loc[i, "aal_legacy"] + f.loc[i, "aal_new"]


def _compute_funding_corridor(
    liability_results: dict,
    funding_inputs: dict,
    constants,
) -> dict:
    """Corridor-smoothing funding model (multi-class, plan-aggregate AVA).

    Args:
        liability_results: Dict mapping class_name -> liability pipeline output DataFrame.
        funding_inputs: Output of load_funding_inputs().
        constants: Plan configuration.

    Returns:
        Dict mapping class_name -> funding DataFrame, plus the
        ``constants.plan_name`` aggregate frame and an optional
        ``"drop"`` frame for plans with ``has_drop=true``.
    """
    # Local import to avoid a circular import via funding_model.py.
    from pension_model.core.funding_model import build_amort_period_tables

    ctx = _resolve_funding_context(constants, funding_inputs)
    dr_current = ctx.dr_current
    dr_new = ctx.dr_new
    dr_old = ctx.dr_old
    payroll_growth = ctx.payroll_growth
    amo_pay_growth = ctx.amo_pay_growth
    amo_period_new = ctx.amo_period_new
    funding_lag = ctx.funding_lag
    db_ee_cont_rate = ctx.db_ee_cont_rate
    inflation = ctx.inflation
    start_year = ctx.start_year
    n_years = ctx.n_years
    ava_strategy = ctx.ava_strategy
    cont_strategy = ctx.cont_strategy
    class_names = ctx.class_names
    agg_name = ctx.agg_name
    has_drop = ctx.has_drop
    drop_ref_class = ctx.drop_ref_class
    all_classes = ctx.all_classes
    return_scen_col = ctx.return_scen_col
    init_funding = ctx.init_funding
    amort_layers = ctx.amort_layers

    ret_scen = _prepare_return_scenarios(ctx, dr_current)

    # Initialize funding tables
    funding = {}
    for cn in all_classes + [agg_name]:
        init_row = _get_init_row(init_funding, cn)
        cols = [c for c in init_funding.columns if c != "class"]
        df = pd.DataFrame(0.0, index=range(n_years), columns=cols)
        df["year"] = range(start_year, start_year + n_years)
        for col in cols:
            if col != "year":
                val = init_row.get(col, 0)
                df.loc[0, col] = float(val if pd.notna(val) else 0)
        funding[cn] = df

    # Calibration
    for cn in class_names:
        f = funding[cn]
        liab = liability_results[cn]

        for ratio_col, num_col, denom_col in [
            ("payroll_db_legacy_ratio", "payroll_db_legacy_est", "total_payroll_est"),
            ("payroll_db_new_ratio", "payroll_db_new_est", "total_payroll_est"),
            ("payroll_dc_legacy_ratio", "payroll_dc_legacy_est", "total_payroll_est"),
            ("payroll_dc_new_ratio", "payroll_dc_new_est", "total_payroll_est"),
        ]:
            if ratio_col not in f.columns:
                f[ratio_col] = 0.0
            denom = liab[denom_col].values
            ratios = np.divide(liab[num_col].values, denom,
                               out=np.zeros_like(denom), where=denom != 0)
            f.loc[1:, ratio_col] = ratios[:-1]

        if "nc_rate_db_legacy" not in f.columns:
            f["nc_rate_db_legacy"] = 0.0
            f["nc_rate_db_new"] = 0.0

        # NC rate calibration: R multiplies liability NC rates by nc_cal
        # nc_cal = val_norm_cost / model_norm_cost (additional adjustment beyond cal_factor=0.9)
        nc_cal = constants.class_data[cn].nc_cal
        _populate_calibrated_nc_rates(f, liab, nc_cal, n_years)

        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
        f.loc[0, "total_aal"] = liab["total_aal_est"].iloc[0]
        f.loc[0, "ual_ava_legacy"] = f.loc[0, "aal_legacy"] - f.loc[0, "ava_legacy"]
        f.loc[0, "total_ual_ava"] = f.loc[0, "total_aal"] - f.loc[0, "total_ava"]

        funding[cn] = f

    # Amortization tables
    amo_tables = {}
    for cn in all_classes:
        cur_per, fut_per, init_bal, max_col = build_amort_period_tables(
            amort_layers, cn, amo_period_new, funding_lag, n_years - 1)

        cur_debt = np.zeros((n_years, max_col + 1))
        if len(init_bal) > 0:
            cur_debt[0, :len(init_bal)] = init_bal
        fut_debt = np.zeros((n_years, max_col + 1))

        cur_pay = np.zeros((n_years, max_col))
        for j in range(max_col):
            if cur_per[0, j] > 0 and abs(cur_debt[0, j]) > 1e-6:
                cur_pay[0, j] = _get_pmt(dr_old, amo_pay_growth, int(cur_per[0, j]),
                                         cur_debt[0, j], t=0.5)
        if funding_lag > 0:
            cur_pay[0, :funding_lag] = 0

        fut_pay = np.zeros((n_years, max_col))

        amo_tables[cn] = {
            "cur_per": cur_per, "fut_per": fut_per,
            "cur_debt": cur_debt, "fut_debt": fut_debt,
            "cur_pay": cur_pay, "fut_pay": fut_pay,
            "max_col": max_col,
        }

    # ========== Main year loop ==========
    for i in range(1, n_years):
        agg = funding[agg_name]

        # --- Membership classes ---
        for cn in class_names:
            f = funding[cn]
            liab = liability_results[cn]

            _phase_payroll(f, i, ctx)

            _accumulate_to_aggregate(agg, f, i, [
                "total_payroll", "payroll_db_legacy", "payroll_db_new",
                "payroll_dc_legacy", "payroll_dc_new",
            ])

            _phase_benefits_refunds(f, liab, i, ctx)
            f.loc[i, "total_ben_payment"] = f.loc[i, "ben_payment_legacy"] + f.loc[i, "ben_payment_new"]
            f.loc[i, "total_refund"] = f.loc[i, "refund_legacy"] + f.loc[i, "refund_new"]

            _accumulate_to_aggregate(agg, f, i, [
                "ben_payment_legacy", "refund_legacy",
                "ben_payment_new", "refund_new",
                "total_ben_payment", "total_refund",
            ])

            _phase_normal_cost(f, i, ctx)
            _accumulate_to_aggregate(agg, f, i, ["nc_legacy", "nc_new"])

            _phase_liability_gl_and_aal(f, liab, i, dr_current, dr_new)

            _accumulate_to_aggregate(agg, f, i, [
                "aal_legacy", "aal_new", "total_aal",
            ])

            funding[cn] = f

        _nc_rate_agg(agg, i, ctx)

        # --- DROP (only for plans with has_drop=true) ---
        if has_drop:
            _phase_drop_projection(funding, agg, i, ctx)

        # --- Contributions, MVA, AVA ---
        for cn in all_classes:
            f = funding[cn]
            amo = amo_tables[cn]

            cont_strategy.compute_rates(f, i, start_year + i, amo)

            if cn == "drop":
                f.loc[i, "er_dc_rate_legacy"] = 0
                f.loc[i, "er_dc_rate_new"] = 0
            else:
                dc_rate = constants.class_data[cn].er_dc_cont_rate
                f.loc[i, "er_dc_rate_legacy"] = dc_rate
                f.loc[i, "er_dc_rate_new"] = dc_rate

            _phase_contributions(f, i, ctx)
            _accumulate_to_aggregate(agg, f, i, [
                "ee_nc_cont_legacy", "ee_nc_cont_new",
            ])
            _accumulate_to_aggregate(agg, f, i, [
                "admin_exp_legacy", "admin_exp_new",
            ])
            f.loc[i, "total_er_db_cont"] = (f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
                                             + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"])
            _accumulate_to_aggregate(agg, f, i, [
                "er_nc_cont_legacy", "er_nc_cont_new",
                "er_amo_cont_legacy", "er_amo_cont_new",
                "total_er_db_cont",
            ])

            _phase_dc_contributions(f, i)
            _accumulate_to_aggregate(agg, f, i, [
                "er_dc_cont_legacy", "er_dc_cont_new", "total_er_dc_cont",
            ])

            year = start_year + i
            roa_row = ret_scen[ret_scen["year"] == year]
            roa = roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current
            f.loc[i, "roa"] = roa
            agg.loc[i, "roa"] = roa

            _phase_cash_flow_and_solvency(f, i, roa)
            _accumulate_to_aggregate(agg, f, i, ["net_cf_legacy", "net_cf_new"])

            _phase_mva(f, i, roa)
            _accumulate_to_aggregate(agg, f, i, [
                "mva_legacy", "mva_new", "total_mva",
            ])

            f.loc[i, "ava_base_legacy"] = f.loc[i - 1, "ava_legacy"] + f.loc[i, "net_cf_legacy"] / 2
            f.loc[i, "ava_base_new"] = f.loc[i - 1, "ava_new"] + f.loc[i, "net_cf_new"] / 2

            funding[cn] = f

        # --- AVA smoothing at plan aggregate level ---
        _phase_ava_corridor_smoothing(agg, i, ava_strategy, dr_current, dr_new)

        # --- Allocate AVA earnings to classes (no-op for class-level smoothing) ---
        ava_strategy.allocate_to_classes(agg, funding, all_classes, i)

        # --- Finalize AVA (DROP reallocation when applicable) ---
        _finalize_ava_with_drop(funding, agg, i, ctx)

        # --- UAL, funded ratios ---
        for cn in all_classes:
            f = funding[cn]
            _phase_ual_and_funded_ratios(f, i)
            _accumulate_to_aggregate(agg, f, i, ["total_ava"])
            _accumulate_to_aggregate(agg, f, i, [
                "ual_ava_legacy", "ual_ava_new", "total_ual_ava",
            ])
            _accumulate_to_aggregate(agg, f, i, [
                "ual_mva_legacy", "ual_mva_new", "total_ual_mva",
            ])

            _phase_er_cont_totals(f, i, ctx)
            _accumulate_to_aggregate(agg, f, i, ["total_er_cont"])
            funding[cn] = f

        agg.loc[i, "fr_mva"] = agg.loc[i, "total_mva"] / agg.loc[i, "total_aal"] if agg.loc[i, "total_aal"] != 0 else 0
        agg.loc[i, "fr_ava"] = agg.loc[i, "total_ava"] / agg.loc[i, "total_aal"] if agg.loc[i, "total_aal"] != 0 else 0
        agg.loc[i, "total_er_cont_rate"] = agg.loc[i, "total_er_cont"] / agg.loc[i, "total_payroll"] if agg.loc[i, "total_payroll"] > 0 else 0

        # --- Amortization layers ---
        for cn in all_classes:
            f = funding[cn]
            amo = amo_tables[cn]
            mc = amo["max_col"]

            _roll_amort_layer(
                debt=amo["cur_debt"], pay=amo["cur_pay"], per=amo["cur_per"],
                i=i, max_col=mc, ual=f.loc[i, "ual_ava_legacy"],
                dr=dr_current, amo_pay_growth=amo_pay_growth,
            )
            _roll_amort_layer(
                debt=amo["fut_debt"], pay=amo["fut_pay"], per=amo["fut_per"],
                i=i, max_col=mc, ual=f.loc[i, "ual_ava_new"],
                dr=dr_new, amo_pay_growth=amo_pay_growth,
            )

        funding[agg_name] = agg

    return funding


def _compute_funding_gainloss(
    liability_results: dict,
    funding_inputs: dict,
    constants,
) -> dict:
    """Gain/loss deferral funding model (statutory-rate, single-class).

    Args:
        liability_results: Dict mapping class_name -> liability pipeline
            output DataFrame. Currently restricted to a single-class
            dict; multi-class support is enabled by Step 2.I.
        funding_inputs: Output of load_funding_inputs().
        constants: PlanConfig.

    Returns:
        Dict mapping class_name -> funding DataFrame, plus an aggregate
        frame keyed by ``constants.plan_name``. For a single-class plan
        the aggregate is a distinct copy of the class frame (no
        DataFrame aliasing); downstream code can mutate one without
        affecting the other.
    """
    ctx = _resolve_funding_context(constants, funding_inputs)
    class_names = ctx.class_names
    first_class = class_names[0]
    liab = liability_results[first_class]
    agg_name = ctx.agg_name

    dr_current = ctx.dr_current
    dr_new = ctx.dr_new
    payroll_growth = ctx.payroll_growth
    inflation = ctx.inflation
    amo_pay_growth = ctx.amo_pay_growth
    amo_period_new = ctx.amo_period_new
    funding_policy = ctx.funding_policy
    start_year = ctx.start_year
    n_years = ctx.n_years
    return_scen_col = ctx.return_scen_col
    ava_strategy = ctx.ava_strategy
    cont_strategy = ctx.cont_strategy

    # --- Load initial row ---
    init = ctx.init_funding.iloc[0]

    ret_scen = _prepare_return_scenarios(ctx, dr_current)

    # --- Legacy funding config parameters (not yet on ctx) ---
    raw = constants.raw if hasattr(constants, "raw") else {}
    funding_raw = raw.get("funding", {})
    amo_period_current = funding_raw.get("amo_period_current", 30)

    # nc_cal: authoritative source is calibration.json (class_data), with
    # funding_raw as legacy fallback
    nc_cal = 1.0
    if hasattr(constants, "class_data") and "all" in constants.class_data:
        cd = constants.class_data["all"]
        if hasattr(cd, "nc_cal") and cd.nc_cal != 1.0:
            nc_cal = cd.nc_cal
    if nc_cal == 1.0:
        nc_cal = funding_raw.get("nc_cal", 1.0)

    # --- Initialize DataFrame from initial funding row ---
    # Column names are expected to follow the standardized convention
    # (lowercase, total_ prefix for aggregates). See plans/*/data/funding/.
    cols = list(init.index)
    f = pd.DataFrame(0.0, index=range(n_years), columns=cols)
    f["year"] = range(start_year, start_year + n_years)
    for col in cols:
        if col != "year":
            val = init.get(col, 0)
            f.loc[0, col] = float(val if pd.notna(val) else 0)

    # --- Calibration: payroll ratios and NC rates from liability pipeline ---
    # R uses lag(ratio) — ratio from previous year applied to next year's payroll
    pay_est = liab["total_payroll_est"].values
    for ratio_col, num_col in [
        ("payroll_db_legacy_ratio", "payroll_db_legacy_est"),
        ("payroll_db_new_ratio", "payroll_db_new_est"),
    ]:
        if ratio_col not in f.columns:
            f[ratio_col] = 0.0
        num = liab[num_col].values if num_col in liab.columns else np.zeros(n_years)
        ratios = np.divide(num, pay_est, out=np.zeros_like(pay_est), where=pay_est != 0)
        # lag by 1
        f.loc[1:, ratio_col] = ratios[:-1]

    # CB payroll ratio
    if "payroll_cb_new_ratio" not in f.columns:
        f["payroll_cb_new_ratio"] = 0.0
    if "payroll_cb_new_est" in liab.columns:
        cb_ratios = np.divide(liab["payroll_cb_new_est"].values, pay_est,
                              out=np.zeros_like(pay_est), where=pay_est != 0)
        f.loc[1:, "payroll_cb_new_ratio"] = cb_ratios[:-1]

    # NC rate calibration (with nc_cal and lag)
    _populate_calibrated_nc_rates(f, liab, nc_cal, n_years)

    # AAL initialization
    if "aal_legacy_est" in liab.columns:
        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
    elif "aal_legacy_est" in liab.columns:
        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
    f.loc[0, "total_aal"] = f.loc[0, "aal_legacy"] + f.loc[0, "aal_new"]
    f.loc[0, "ual_ava_legacy"] = f.loc[0, "aal_legacy"] - f.loc[0, "ava_legacy"]
    f.loc[0, "total_ual_ava"] = f.loc[0, "total_aal"] - f.loc[0, "total_ava"]

    # --- Amortization period tables ---
    amo_seq_current = list(range(amo_period_current, 0, -1))
    amo_seq_new = list(range(amo_period_new, 0, -1))
    n_amo = max(len(amo_seq_current), len(amo_seq_new))

    # Current-hire period table: row 0 = existing countdown, rows 1+ = new layers
    amo_per_current = np.zeros((n_years, n_amo))
    amo_per_current[0, :len(amo_seq_current)] = amo_seq_current
    for row in range(1, n_years):
        amo_per_current[row, :len(amo_seq_new)] = amo_seq_new
    # Shift onto diagonals
    for j in range(1, n_amo):
        for row in range(n_years):
            if row - j >= 0:
                amo_per_current[row, j] = amo_per_current[row - j, j] if row == j else amo_per_current[row, j]
    # Rebuild with proper diagonal shift (match R's lag logic)
    amo_per_current_diag = np.zeros((n_years, n_amo))
    amo_per_current_diag[0, :len(amo_seq_current)] = amo_seq_current
    for row in range(1, n_years):
        amo_per_current_diag[row, 0] = amo_seq_new[0] if len(amo_seq_new) > 0 else 0
    for j in range(1, n_amo):
        for row in range(j, n_years):
            prev = amo_per_current_diag[row - 1, j - 1]
            amo_per_current_diag[row, j] = max(prev - 1, 0) if prev > 0 else 0

    amo_per_new = np.zeros((n_years, n_amo))
    for j in range(n_amo):
        for row in range(j + 1, n_years):
            idx = row - j - 1
            amo_per_new[row, j] = max(amo_seq_new[0] - idx, 0) if idx < amo_seq_new[0] else 0
    # Simpler: diagonal from row j+1, col j, counting down
    amo_per_new = np.zeros((n_years, n_amo))
    for j in range(n_amo):
        for row in range(j + 1, n_years):
            amo_per_new[row, j] = max(amo_period_new - (row - j - 1), 0)

    # Debt and payment tables
    debt_current = np.zeros((n_years, n_amo + 1))
    pay_current = np.zeros((n_years, n_amo))
    debt_new = np.zeros((n_years, n_amo + 1))
    pay_new = np.zeros((n_years, n_amo))

    # Initialize first debt layer and payment
    debt_current[0, 0] = f.loc[0, "total_ual_ava"]
    if amo_per_current_diag[0, 0] > 0:
        pay_current[0, 0] = _get_pmt(
            dr_current, amo_pay_growth, int(amo_per_current_diag[0, 0]),
            debt_current[0, 0], t=0.5)

    # Strategies (ava_strategy, cont_strategy) already instantiated by
    # _resolve_funding_context above.

    # --- Main year loop ---
    for i in range(1, n_years):
        year = start_year + i

        # Payroll projection
        _phase_payroll(f, i, ctx)

        # Benefit payments from liability pipeline
        _phase_benefits_refunds(f, liab, i, ctx)

        # Normal cost (rate written by helper using canonical denominator — GH #42)
        _phase_normal_cost(f, i, ctx)

        # Liability gain/loss + AAL roll-forward
        _phase_liability_gl_and_aal(f, liab, i, dr_current, dr_new)
        # Gainloss-only sum column (not in corridor schema)
        f.loc[i, "liability_gain_loss"] = f.loc[i, "liability_gain_loss_legacy"] + f.loc[i, "liability_gain_loss_new"]

        # NC, EE, ER NC, statutory cascade, and amort rates
        cont_strategy.compute_rates(
            f, i, year,
            amo_state={"cur_pay": pay_current, "fut_pay": pay_new},
        )

        # Contribution dollars (admin rate + EE/admin/ER NC/ER amo per leg)
        _phase_contributions(f, i, ctx)

        # Return on assets
        roa_row = ret_scen[ret_scen["year"] == year]
        roa = roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current
        f.loc[i, "roa"] = roa

        # Cash flows and solvency contribution
        _phase_cash_flow_and_solvency(f, i, roa)

        # MVA projection
        _phase_mva(f, i, roa)

        # AVA gain/loss deferral smoothing (both legs)
        _phase_ava_gainloss_smoothing(f, i, ava_strategy, dr_current, dr_new)

        # Total AVA, UAL, funded ratios
        _phase_ual_and_funded_ratios(f, i)

        # Contribution totals (total_er_cont, total_er_cont_rate)
        _phase_er_cont_totals(f, i, ctx)
        # Gainloss-path-only total contribution rate
        f.loc[i, "tot_cont_rate"] = (
            (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
             + f.loc[i, "er_amo_cont_legacy"]
             + f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
             + f.loc[i, "er_amo_cont_new"] + f.loc[i, "solv_cont"])
            / f.loc[i, "total_payroll"]) if f.loc[i, "total_payroll"] > 0 else 0

        # Real cost metrics (gainloss-path-only; capability-gated once unified)
        _phase_real_cost_metrics(f, i, year, start_year, inflation)

        # Amortization layer updates — current hires (legacy)
        _roll_amort_layer(
            debt=debt_current, pay=pay_current, per=amo_per_current_diag,
            i=i, max_col=n_amo, ual=f.loc[i, "ual_ava_legacy"],
            dr=dr_current, amo_pay_growth=amo_pay_growth,
        )

        # Amortization layer updates — new hires
        _roll_amort_layer(
            debt=debt_new, pay=pay_new, per=amo_per_new,
            i=i, max_col=n_amo, ual=f.loc[i, "ual_ava_new"],
            dr=dr_new, amo_pay_growth=amo_pay_growth,
        )

    # Build the aggregate frame as a distinct copy. For a single-class
    # plan the aggregate IS the class frame mathematically; a copy
    # preserves that while ensuring the dict's two entries point at
    # different DataFrame objects (no mutation aliasing).
    return {first_class: f, agg_name: f.copy()}
