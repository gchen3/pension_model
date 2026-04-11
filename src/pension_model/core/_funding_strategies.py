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

This module is *protocol scaffolding only*: the smoothing strategies
delegate verbatim to the existing helpers in ``_funding_helpers.py``;
the contribution strategy classes carry signatures and docstrings but
their method bodies are filled in by Step 10 of the unification
refactor (``Wire strategies into call sites``). Importing this module
introduces no numerical change to either funding path.
"""

from __future__ import annotations

from typing import ClassVar, Literal, Protocol, runtime_checkable

import pandas as pd

from pension_model.core._funding_helpers import (
    _ava_corridor_smoothing,
    _ava_gain_loss_smoothing,
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


class StatutoryContributions:
    """Employer contributions driven by a statutory rate cascade.

    The employer effective rate is::

        er_stat_eff_rate = (
            er_stat_base_rate(year)
            + public_edu_surcharge_rate(year) * public_edu_payroll_pct
            + er_stat_extra_rate(year)
        )

    Term order is *load-bearing* (bit-identity risk #6): floating-point
    addition is non-associative; the original TRS code adds the
    surcharge term before the extra term, and this implementation must
    preserve that order.

    Under ``funding_policy == "statutory"`` the amortization rate is
    the residual ``er_stat_eff_rate - er_nc_rate_*``; under any other
    funding policy the amortization rate falls back to the prior
    year's amort-table payments divided by payroll, like the actuarial
    path. The TRS-side fallback uses ``total_payroll`` (not
    ``payroll_db_legacy``) as the legacy denominator under non-
    statutory policies; that asymmetry is preserved by reading
    ``f.loc[i, "total_payroll"]`` in the non-statutory branch.
    """

    def __init__(
        self,
        funding_policy: str,
        public_edu_payroll_pct: float,
        extra_er_stat_cont: float,
        extra_er_start_year: int,
        surcharge_ramp_end: int,
        surcharge_ramp_rate: float,
        er_base_schedule: list,
        ee_schedule: list,
    ) -> None:
        self.funding_policy = funding_policy
        self.public_edu_payroll_pct = public_edu_payroll_pct
        self.extra_er_stat_cont = extra_er_stat_cont
        self.extra_er_start_year = extra_er_start_year
        self.surcharge_ramp_end = surcharge_ramp_end
        self.surcharge_ramp_rate = surcharge_ramp_rate
        self.er_base_schedule = er_base_schedule
        self.ee_schedule = ee_schedule

    def compute_rates(
        self,
        f: pd.DataFrame,
        i: int,
        year: int,
        amo_state: dict,
    ) -> None:
        from pension_model.core._funding_helpers import _lookup_rate_schedule

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

        # Statutory rate cascade
        f.loc[i, "er_stat_base_rate"] = _lookup_rate_schedule(
            self.er_base_schedule, year)

        if year <= self.surcharge_ramp_end:
            f.loc[i, "public_edu_surcharge_rate"] = (
                f.loc[i - 1, "public_edu_surcharge_rate"]
                + self.surcharge_ramp_rate
            )
        else:
            f.loc[i, "public_edu_surcharge_rate"] = (
                f.loc[i - 1, "public_edu_surcharge_rate"]
            )

        f.loc[i, "er_stat_extra_rate"] = (
            self.extra_er_stat_cont
            if year >= self.extra_er_start_year else 0
        )

        # NOTE: term order is bit-identity load-bearing — see docstring
        f.loc[i, "er_stat_eff_rate"] = (
            f.loc[i, "er_stat_base_rate"]
            + f.loc[i, "public_edu_surcharge_rate"] * self.public_edu_payroll_pct
            + f.loc[i, "er_stat_extra_rate"]
        )

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
