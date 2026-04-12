"""
Strategy classes for the funding model.

Two axes of variation between funding policies are *orthogonal* and
must be configurable independently:

  1. **Asset value smoothing.** How quickly investment gains/losses are
     recognized into the actuarial value of assets (AVA). Two methods
     are supported:

       * Five-year corridor (recognize 1/5 per year, bounded to a
         [80%, 120%] band around MVA). Operates at the *plan-aggregate*
         level, then allocates earnings back to classes proportionally.
       * Four-year gain/loss deferral cascade. Operates per-class.

  2. **Employer contribution policy.** How the year-loop computes the
     employer's normal cost and amortization payments:

       * Actuarial: pre-calibrated NC rates from the liability pipeline,
         amortization rate from the prior year's amort table payments.
       * Statutory: a base employer rate cascade
         (``base + surcharge * applicable_payroll_pct + extra``)
         drives the effective employer rate; under
         ``funding_policy = "statutory"`` the amortization rate is the
         residual of the statutory effective rate minus the employer
         normal cost rate.

The dispatch on ``len(constants.classes) == 1`` that lives in
``run_funding_model`` today bundles these two axes together — single-
class plans get gain/loss + statutory, multi-class plans get corridor
+ actuarial. The strategies in this module decouple them so a future
plan can mix and match (e.g. corridor + statutory) by changing config,
not code.

All four concrete strategies — ``CorridorSmoothing``, ``GainLossSmoothing``,
``ActuarialContributions``, ``StatutoryContributions`` — are wired into the
active funding compute path in ``_funding_core.py``. The Protocol-based
design means a new strategy can be dropped in (e.g. a three-year corridor,
or a different statutory rate structure) by writing a class that satisfies
the Protocol and selecting it in plan config.

Statutory employer contributions are specified as a **list of rate components**
(see ``RateComponent``), each with its own rate schedule / ramp and its own
payroll share. The effective employer rate is the payroll-share-weighted sum
across components:

    effective_rate(year) = sum(component_rate(year) * component.payroll_share)

This generalizes over any multi-employer cost-sharing structure where
different employer types contribute at different statutory rates over
different fractions of total plan payroll — e.g. Texas's public-ed
surcharge, California school vs non-school rates, or a hazardous-duty
surcharge on a subset of payroll. Nothing in this module knows or cares
about any particular plan's component names; they're labels chosen by the
config author and used only for the output DataFrame's column names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal, Optional, Protocol, runtime_checkable

import pandas as pd

from pension_model.core._funding_helpers import (
    _ava_corridor_smoothing,
    _ava_gain_loss_smoothing,
    _lookup_rate_schedule,
)


# ---------------------------------------------------------------------------
# AVA smoothing strategies
# ---------------------------------------------------------------------------


@runtime_checkable
class AvaSmoothingStrategy(Protocol):
    """One year of asset value smoothing for a single asset leg.

    Smoothing operates per leg (e.g. ``legacy`` and ``new``) and the
    caller invokes the strategy once per leg. The leg name is *not*
    passed in — it lives at the call site, which is responsible for
    reading prior values and writing results onto the appropriate
    columns of the funding DataFrame.

    Implementations declare ``aggregation_level``:

      * ``"plan"``  — call once at the plan-aggregate level after every
        class has been processed for the year, then call
        ``allocate_to_classes`` to distribute earnings back to classes.
      * ``"class"`` — call once *per class* inside the class loop. The
        ``allocate_to_classes`` method is a no-op for these strategies.
    """

    aggregation_level: ClassVar[Literal["plan", "class"]]

    def smooth(
        self,
        ava_prev: float,
        net_cf: float,
        mva: float,
        dr: float,
        state: dict,
    ) -> dict:
        """Compute smoothed AVA values for one year and one asset leg.

        ``state`` carries strategy-specific extra inputs (e.g. prior
        deferral balances for gain/loss smoothing). Strategies that
        have no extra state ignore it.

        Returned dict shape is strategy-specific. The caller knows
        which strategy is in use and writes the keys it expects to
        the appropriate columns. (Step 11 will introduce a unified
        column-write helper that maps strategy result keys to
        DataFrame columns.)
        """
        ...

    def allocate_to_classes(
        self,
        agg: pd.DataFrame,
        funding: dict,
        class_names: list,
        i: int,
    ) -> None:
        """For plan-level smoothing, allocate aggregate AVA earnings
        back to individual classes proportionally to each class's
        ``ava_base``. For per-class smoothing, this is a no-op.
        """
        ...


class CorridorSmoothing:
    """Five-year corridor smoothing at the plan-aggregate level.

    Smooths each leg's AVA toward MVA at 1/5 per year, bounded to
    ``[0.8 * mva, 1.2 * mva]``. After smoothing the aggregate, allocates
    the realized earnings to each class in proportion to that class's
    pre-smoothing ``ava_base`` (= ``ava_prev + net_cf / 2``).
    """

    aggregation_level: ClassVar[Literal["plan", "class"]] = "plan"

    def smooth(
        self,
        ava_prev: float,
        net_cf: float,
        mva: float,
        dr: float,
        state: dict,  # noqa: ARG002 — corridor has no extra state
    ) -> dict:
        return _ava_corridor_smoothing(ava_prev, net_cf, mva, dr)

    def allocate_to_classes(
        self,
        agg: pd.DataFrame,
        funding: dict,
        class_names: list,
        i: int,
    ) -> None:
        """Distribute the aggregate's smoothed earnings to each class
        proportionally to that class's ``ava_base``.

        For each leg (``legacy`` and ``new``)::

            class_alloc = agg_alloc * class_ava_base / agg_ava_base
            class_unadj_ava = class_ava_prev + class_net_cf + class_alloc

        The ``ava_base != 0`` guard mirrors the original FRS code path
        (lines 488 and 492). The mid-year-cashflow base
        (``ava_prev + net_cf / 2``) was already written onto each
        class's frame inside the per-class loop, so this method only
        reads it.
        """
        for cn in class_names:
            f = funding[cn]
            if agg.loc[i, "ava_base_legacy"] != 0:
                f.loc[i, "alloc_inv_earnings_ava_legacy"] = (
                    agg.loc[i, "alloc_inv_earnings_ava_legacy"]
                    * f.loc[i, "ava_base_legacy"]
                    / agg.loc[i, "ava_base_legacy"]
                )
            f.loc[i, "unadj_ava_legacy"] = (
                f.loc[i - 1, "ava_legacy"]
                + f.loc[i, "net_cf_legacy"]
                + f.loc[i, "alloc_inv_earnings_ava_legacy"]
            )

            if agg.loc[i, "ava_base_new"] != 0:
                f.loc[i, "alloc_inv_earnings_ava_new"] = (
                    agg.loc[i, "alloc_inv_earnings_ava_new"]
                    * f.loc[i, "ava_base_new"]
                    / agg.loc[i, "ava_base_new"]
                )
            f.loc[i, "unadj_ava_new"] = (
                f.loc[i - 1, "ava_new"]
                + f.loc[i, "net_cf_new"]
                + f.loc[i, "alloc_inv_earnings_ava_new"]
            )
            funding[cn] = f


class GainLossSmoothing:
    """Four-year gain/loss deferral cascade at the per-class level.

    Each year's asset gain/loss is deferred and recognized in the
    following four years (``y4 → y3 → y2 → y1`` cascade with sign-
    aware offsetting). Operates per class; aggregate-level allocation
    is a no-op because each class has already smoothed its own assets.

    The ``state`` dict required by ``smooth`` must contain four keys:
    ``defer_y1_prev``, ``defer_y2_prev``, ``defer_y3_prev``,
    ``defer_y4_prev``.
    """

    aggregation_level: ClassVar[Literal["plan", "class"]] = "class"

    def smooth(
        self,
        ava_prev: float,
        net_cf: float,
        mva: float,
        dr: float,
        state: dict,
    ) -> dict:
        return _ava_gain_loss_smoothing(
            ava_prev,
            net_cf,
            mva,
            dr,
            state["defer_y1_prev"],
            state["defer_y2_prev"],
            state["defer_y3_prev"],
            state["defer_y4_prev"],
        )

    def allocate_to_classes(
        self,
        agg: pd.DataFrame,
        funding: dict,
        class_names: list,
        i: int,
    ) -> None:
        # No-op: each class is already smoothed inside the per-class loop.
        return None


# ---------------------------------------------------------------------------
# Employer contribution strategies
# ---------------------------------------------------------------------------


@runtime_checkable
class ContributionStrategy(Protocol):
    """Computes the per-class employer NC, EE, and amortization rate
    columns for one year inside the funding loop.

    Implementations differ on:

      * Whether the employer normal-cost rate is computed from the
        calibrated NC rates pre-populated by
        ``_populate_calibrated_nc_rates`` (Actuarial), or from a
        statutory rate cascade (Statutory).
      * Whether the amortization rate is a function of the prior
        year's amort-table payments (Actuarial), or the residual of an
        externally-set statutory effective rate (Statutory, when
        ``funding_policy == "statutory"``).

    The contract is to write these eight columns to ``f.loc[i, :]``::

        nc_rate_legacy, nc_rate_new
        ee_nc_rate_legacy, ee_nc_rate_new
        er_nc_rate_legacy, er_nc_rate_new
        amo_rate_legacy, amo_rate_new

    ``StatutoryContributions`` additionally writes
    ``er_stat_base_rate``, ``public_edu_surcharge_rate``,
    ``er_stat_extra_rate``, and ``er_stat_eff_rate`` (the rate
    cascade). Plans whose frames don't have those columns must not
    instantiate ``StatutoryContributions``.

    Contribution *amounts* (rate × payroll), DC contributions, admin
    expenses, and aggregate accumulation are NOT the strategy's job —
    they're computed at the call site after this method runs.
    """

    def compute_rates(
        self,
        f: pd.DataFrame,
        i: int,
        year: int,
        amo_state: dict,
    ) -> None:
        """Write the eight rate columns (legacy + new) to ``f.loc[i, :]``."""
        ...


def _payroll_new_denom(f: pd.DataFrame, i: int) -> float:
    """Return the appropriate denominator for ``nc_rate_new``.

    For cash-balance plans (TRS-style), the new-hire normal-cost rate
    is divided by ``payroll_db_new + payroll_cb_new``; for plans
    without a cash-balance leg the denominator is just ``payroll_db_new``.
    Schema-driven via the presence of the ``payroll_cb_new`` column on
    the funding frame, the same way ``_populate_calibrated_nc_rates``
    decides whether to write the CB normal-cost rate column.
    """
    if "payroll_cb_new" in f.columns:
        return f.loc[i, "payroll_db_new"] + f.loc[i, "payroll_cb_new"]
    return f.loc[i, "payroll_db_new"]


class ActuarialContributions:
    """Employer contributions driven by the calibrated actuarial pipeline.

    The employer normal-cost rate is the calibrated total NC rate
    minus a flat employee contribution rate; the amortization rate is
    computed from the prior year's amort-table payments divided by
    payroll. There is no statutory rate cascade.

    The amort-table payment arrays are looked up via
    ``amo_state["cur_pay"]`` and ``amo_state["fut_pay"]``; both are
    expected to be 2-D ndarrays indexed (year, layer) and the row at
    ``i - 1`` is summed to get the payment total for the legacy /
    new layer respectively.
    """

    def __init__(self, db_ee_cont_rate: float) -> None:
        self.db_ee_cont_rate = db_ee_cont_rate

    def compute_rates(
        self,
        f: pd.DataFrame,
        i: int,
        year: int,
        amo_state: dict,
    ) -> None:
        ee_rate = self.db_ee_cont_rate
        payroll_db_legacy = f.loc[i, "payroll_db_legacy"]
        payroll_new_denom = _payroll_new_denom(f, i)

        # Total NC rates
        f.loc[i, "nc_rate_legacy"] = (
            f.loc[i, "nc_legacy"] / payroll_db_legacy
            if payroll_db_legacy > 0 else 0
        )
        f.loc[i, "nc_rate_new"] = (
            f.loc[i, "nc_new"] / payroll_new_denom
            if payroll_new_denom > 0 else 0
        )

        # Flat EE rate
        f.loc[i, "ee_nc_rate_legacy"] = ee_rate
        f.loc[i, "ee_nc_rate_new"] = ee_rate

        # ER NC rate is the residual
        f.loc[i, "er_nc_rate_legacy"] = f.loc[i, "nc_rate_legacy"] - ee_rate
        f.loc[i, "er_nc_rate_new"] = f.loc[i, "nc_rate_new"] - ee_rate

        # Amort rate from prior year's amort-table payments
        cur_pay = amo_state["cur_pay"]
        fut_pay = amo_state["fut_pay"]
        f.loc[i, "amo_rate_legacy"] = (
            cur_pay[i - 1].sum() / payroll_db_legacy
            if payroll_db_legacy > 0 else 0
        )
        f.loc[i, "amo_rate_new"] = (
            fut_pay[i - 1].sum() / payroll_new_denom
            if payroll_new_denom > 0 else 0
        )


@dataclass
class RateComponent:
    """One term in a statutory employer-rate cascade.

    Each component contributes ``rate(year) * payroll_share`` to the
    effective employer rate. A plan's statutory structure is described
    by a list of these components; the Python code is agnostic to how
    many there are and what they represent.

    Rate specification — exactly one of:
      * ``schedule``: a list of ``{from_year, rate}`` step-function
        entries, used via :func:`_lookup_rate_schedule`.
      * ``initial_rate`` + ``ramp``: the rate starts at ``initial_rate``
        (read from a per-class column ``f.loc[i - 1, "er_stat_rate_<name>"]``
        for i >= 1), adds ``ramp["rate_per_year"]`` each year up to and
        including ``ramp["end_year"]``, and then stays flat. ``start_year``
        (optional) makes the rate zero until that year is reached.

    ``payroll_share`` scales the term. For example, if only 58.8% of
    plan payroll is subject to a surcharge, set ``payroll_share = 0.588``;
    for rates that apply to all payroll, set ``payroll_share = 1.0``.

    ``name`` is the output column name on the funding frame for this
    component's rate (e.g. "er_stat_base_rate" or "peec_surcharge_rate").
    It's chosen by the config author, carries no model meaning, and is
    only used as a pd.DataFrame column label.
    """

    name: str
    payroll_share: float = 1.0
    schedule: Optional[list] = None
    initial_rate: Optional[float] = None
    ramp: Optional[dict] = None
    start_year: Optional[int] = None

    @classmethod
    def from_config(cls, cfg: dict) -> "RateComponent":
        return cls(
            name=cfg["name"],
            payroll_share=float(cfg.get("payroll_share", 1.0)),
            schedule=cfg.get("schedule"),
            initial_rate=cfg.get("initial_rate"),
            ramp=cfg.get("ramp"),
            start_year=cfg.get("start_year"),
        )


def _evaluate_rate_component(
    component: RateComponent,
    f: pd.DataFrame,
    i: int,
    year: int,
) -> float:
    """Compute the component's rate for year ``year`` (i.e. row ``i``).

    Schedule form: delegates to ``_lookup_rate_schedule``.

    Ramp form: reads the previous year's value of this component from
    its output column (``component.name``) and increments by
    ``ramp["rate_per_year"]`` while ``year <= ramp["end_year"]``,
    otherwise holds flat. ``start_year``, if provided, makes the rate
    zero until that year is reached.

    """
    if component.start_year is not None and year < component.start_year:
        return 0.0

    if component.schedule is not None:
        return _lookup_rate_schedule(component.schedule, year)

    if component.ramp is not None:
        col = component.name
        prev = f.loc[i - 1, col] if i >= 1 and col in f.columns else component.initial_rate
        if prev is None:
            prev = 0.0
        ramp_rate = float(component.ramp.get("rate_per_year", 0.0))
        end_year = component.ramp.get("end_year")
        if end_year is not None and year <= end_year:
            return float(prev) + ramp_rate
        return float(prev)

    # No schedule, no ramp: constant at initial_rate (default 0.0).
    return float(component.initial_rate if component.initial_rate is not None else 0.0)


class StatutoryContributions:
    """Employer contributions driven by a statutory rate cascade.

    The employer effective rate is a payroll-share-weighted sum over a
    list of rate components, with the sum order matching the config's
    component order::

        er_stat_eff_rate = sum(component.rate(year) * component.payroll_share
                               for component in components)

    Term order is *load-bearing* (bit-identity risk #6): floating-point
    addition is non-associative. Components are iterated in config order
    and the accumulator is built up left-to-right via a Python sum.

    Under ``funding_policy == "statutory"`` the amortization rate is
    the residual ``er_stat_eff_rate - er_nc_rate_*``; under any other
    funding policy the amortization rate falls back to the prior year's
    amort-table payments divided by payroll, like the actuarial path.
    The legacy denominator under non-statutory policy is
    ``total_payroll`` (preserved from the pre-refactor TRS code).
    """

    def __init__(
        self,
        funding_policy: str,
        ee_schedule: list,
        components: list,
    ) -> None:
        self.funding_policy = funding_policy
        self.ee_schedule = ee_schedule
        # Accept either a list of RateComponent or a list of raw dicts.
        self.components: list[RateComponent] = [
            c if isinstance(c, RateComponent) else RateComponent.from_config(c)
            for c in components
        ]

    def compute_rates(
        self,
        f: pd.DataFrame,
        i: int,
        year: int,
        amo_state: dict,
    ) -> None:
        payroll_db_legacy = f.loc[i, "payroll_db_legacy"]
        payroll_new_denom = _payroll_new_denom(f, i)

        # Total NC rates
        f.loc[i, "nc_rate_legacy"] = (
            f.loc[i, "nc_legacy"] / payroll_db_legacy
            if payroll_db_legacy > 0 else 0
        )
        f.loc[i, "nc_rate_new"] = (
            f.loc[i, "nc_new"] / payroll_new_denom
            if payroll_new_denom > 0 else 0
        )

        # EE rate from schedule
        ee_rate = _lookup_rate_schedule(self.ee_schedule, year)
        f.loc[i, "ee_nc_rate_legacy"] = ee_rate
        f.loc[i, "ee_nc_rate_new"] = ee_rate

        # ER NC rate is the residual
        f.loc[i, "er_nc_rate_legacy"] = f.loc[i, "nc_rate_legacy"] - ee_rate
        f.loc[i, "er_nc_rate_new"] = f.loc[i, "nc_rate_new"] - ee_rate

        # Per-component statutory rates. Write each component's rate to
        # the column named by the component (e.g. "er_stat_base_rate"),
        # then accumulate the effective rate in config order. Addition
        # order is bit-identity load-bearing — see class docstring.
        eff_rate = 0.0
        for comp in self.components:
            rate = _evaluate_rate_component(comp, f, i, year)
            f.loc[i, comp.name] = rate
            eff_rate = eff_rate + rate * comp.payroll_share
        f.loc[i, "er_stat_eff_rate"] = eff_rate

        # Amort rate: statutory residual or actuarial table fallback
        if self.funding_policy == "statutory":
            f.loc[i, "amo_rate_legacy"] = (
                f.loc[i, "er_stat_eff_rate"] - f.loc[i, "er_nc_rate_legacy"]
            )
            f.loc[i, "amo_rate_new"] = (
                f.loc[i, "er_stat_eff_rate"] - f.loc[i, "er_nc_rate_new"]
            )
        else:
            cur_pay = amo_state["cur_pay"]
            fut_pay = amo_state["fut_pay"]
            total_payroll = f.loc[i, "total_payroll"]
            f.loc[i, "amo_rate_legacy"] = (
                cur_pay[i - 1].sum() / total_payroll
                if total_payroll > 0 else 0
            )
            f.loc[i, "amo_rate_new"] = (
                fut_pay[i - 1].sum() / payroll_new_denom
                if payroll_new_denom > 0 else 0
            )
