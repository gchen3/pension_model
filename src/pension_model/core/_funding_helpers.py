"""
Pure helpers extracted from ``funding_model.py``.

This module is part of the Phase 2 funding-model unification refactor.
Each helper here is *bit-for-bit identical* to the original implementation
in ``funding_model.py``; the goal of Step 1 is to relocate code without
changing any numerical operation.

Bit-identity constraints (do not "simplify"):
  * ``_ava_gain_loss_smoothing`` uses ``math.copysign`` deliberately.
    ``math.copysign(1, 0) == 1`` whereas ``np.sign(0) == 0`` — switching
    to ``np.sign`` would silently change TRS's R-baseline match. The
    cascade order (y4 → y3 → y2 → y1) and the literal arithmetic in each
    branch are also load-bearing.
"""

import math

import numpy as np
import pandas as pd

from pension_model.core.pipeline import _get_pmt


def _get_init_row(init_funding: pd.DataFrame, class_name: str) -> pd.Series:
    """Get initial funding values for a class (with class name normalization)."""
    lookup = class_name.replace("_", " ")
    row = init_funding[init_funding["class"] == lookup]
    if len(row) == 0:
        row = init_funding[init_funding["class"] == class_name]
    return row.iloc[0]


def _ava_gain_loss_smoothing(
    ava_prev, net_cf, mva, dr,
    defer_y1_prev, defer_y2_prev, defer_y3_prev, defer_y4_prev,
):
    """AVA gain/loss deferral smoothing (4-year phased recognition).

    Returns dict with all intermediate and final values.
    """
    exp_inv_income = ava_prev * dr + net_cf * dr / 2
    exp_ava = ava_prev + net_cf + exp_inv_income
    asset_gain_loss = mva - exp_ava

    prev_defer_total = defer_y1_prev + defer_y2_prev + defer_y3_prev + defer_y4_prev
    remain_defer_boy = asset_gain_loss - prev_defer_total

    # Cascade offset logic: y4 → y3 → y2 → y1
    # Step 1: offset defer_y4
    if math.copysign(1, remain_defer_boy) == math.copysign(1, defer_y4_prev) or defer_y4_prev == 0:
        aft_offset_y4 = remain_defer_boy
    else:
        aft_offset_y4 = math.copysign(
            max(0, abs(remain_defer_boy) - abs(defer_y4_prev)),
            remain_defer_boy) if remain_defer_boy != 0 else 0.0
    if math.copysign(1, aft_offset_y4) == math.copysign(1, defer_y3_prev) or defer_y3_prev == 0:
        new_y4 = defer_y3_prev * 0.5
    else:
        new_y4 = math.copysign(
            max(0, abs(defer_y3_prev) - abs(aft_offset_y4)),
            defer_y3_prev) * 0.5 if defer_y3_prev != 0 else 0.0

    # Step 2: offset defer_y3
    if math.copysign(1, aft_offset_y4) == math.copysign(1, defer_y3_prev) or defer_y3_prev == 0:
        aft_offset_y3 = aft_offset_y4
    else:
        aft_offset_y3 = math.copysign(
            max(0, abs(aft_offset_y4) - abs(defer_y3_prev)),
            aft_offset_y4) if aft_offset_y4 != 0 else 0.0
    if math.copysign(1, aft_offset_y3) == math.copysign(1, defer_y2_prev) or defer_y2_prev == 0:
        new_y3 = defer_y2_prev * (2 / 3)
    else:
        new_y3 = math.copysign(
            max(0, abs(defer_y2_prev) - abs(aft_offset_y3)),
            defer_y2_prev) * (2 / 3) if defer_y2_prev != 0 else 0.0

    # Step 3: offset defer_y2
    if math.copysign(1, aft_offset_y3) == math.copysign(1, defer_y2_prev) or defer_y2_prev == 0:
        aft_offset_y2 = aft_offset_y3
    else:
        aft_offset_y2 = math.copysign(
            max(0, abs(aft_offset_y3) - abs(defer_y2_prev)),
            aft_offset_y3) if aft_offset_y3 != 0 else 0.0
    if math.copysign(1, aft_offset_y2) == math.copysign(1, defer_y1_prev) or defer_y1_prev == 0:
        new_y2 = defer_y1_prev * (3 / 4)
    else:
        new_y2 = math.copysign(
            max(0, abs(defer_y1_prev) - abs(aft_offset_y2)),
            defer_y1_prev) * (3 / 4) if defer_y1_prev != 0 else 0.0

    # Step 4: offset defer_y1
    if math.copysign(1, aft_offset_y2) == math.copysign(1, defer_y1_prev) or defer_y1_prev == 0:
        aft_offset_y1 = aft_offset_y2
    else:
        aft_offset_y1 = math.copysign(
            max(0, abs(aft_offset_y2) - abs(defer_y1_prev)),
            aft_offset_y2) if aft_offset_y2 != 0 else 0.0
    new_y1 = aft_offset_y1 * (4 / 5)

    remain_defer_eoy = new_y1 + new_y2 + new_y3 + new_y4
    ava = mva - remain_defer_eoy

    return {
        "exp_inv_income": exp_inv_income,
        "exp_ava": exp_ava,
        "asset_gain_loss": asset_gain_loss,
        "remain_defer_boy": remain_defer_boy,
        "aft_offset_defer_y4": aft_offset_y4,
        "defer_y4": new_y4,
        "aft_offset_defer_y3": aft_offset_y3,
        "defer_y3": new_y3,
        "aft_offset_defer_y2": aft_offset_y2,
        "defer_y2": new_y2,
        "aft_offset_defer_y1": aft_offset_y1,
        "defer_y1": new_y1,
        "remain_defer_eoy": remain_defer_eoy,
        "ava": ava,
    }


def _aal_rollforward(aal_prev, nc, ben, refund, liab_gl, dr):
    """Roll the actuarial accrued liability forward one year.

    Identical formula used by both the corridor (FRS) and gain/loss (TRS)
    funding paths::

        aal_t = aal_{t-1} * (1 + dr)
              + (nc - ben - refund) * (1 + dr) ** 0.5
              + liab_gl

    The mid-year cashflow is brought forward at half a year of interest
    via ``(1 + dr) ** 0.5``. **Always pass scalar** ``dr`` — never a
    precomputed ``sqrt_factor`` — so the floating-point operations match
    the original inline expression bit-for-bit (see bit-identity risk #1).
    """
    return (
        aal_prev * (1 + dr)
        + (nc - ben - refund) * (1 + dr) ** 0.5
        + liab_gl
    )


def _mva_rollforward(mva_prev, net_cf, roa):
    """Roll the market value of assets forward one year.

    Identical formula used by both funding paths::

        mva_t = mva_{t-1} * (1 + roa) + net_cf * (1 + roa) ** 0.5

    Mid-year cashflow is brought forward at half a year of investment
    return. Pass scalar ``roa`` so the operations match the original
    inline expression bit-for-bit (bit-identity risk #1).
    """
    return mva_prev * (1 + roa) + net_cf * (1 + roa) ** 0.5


def _solvency_cont(mva_prev, cf_total, roa):
    """Solvency contribution: minimum cash needed to keep MVA non-negative.

    Identical formula in both funding paths::

        max(
            -(mva_prev * (1 + roa) + cf_total * (1 + roa) ** 0.5)
              / (1 + roa) ** 0.5,
            0,
        )

    Pass scalar ``roa`` and pre-summed ``cf_total`` (the original FRS call
    site computes ``cf_leg + cf_new`` inline; that addition produces an
    identical float to the TRS pre-computed ``cf_total = cf_legacy +
    cf_new``).
    """
    return max(
        -(mva_prev * (1 + roa) + cf_total * (1 + roa) ** 0.5) / (1 + roa) ** 0.5,
        0,
    )


def _roll_amort_layer(debt, pay, per, i, max_col, ual, dr, amo_pay_growth):
    """Roll one set of amortization layers forward by one year (in place).

    Operates on 2-D ndarrays indexed (year, layer):
      * ``debt`` shape ``(n_years, max_col + 1)`` — column 0 is the new
        layer formed at year ``i``, columns 1..max_col are existing
        layers being rolled forward.
      * ``pay``  shape ``(n_years, max_col)``   — amortization payments.
      * ``per``  shape ``(n_years, max_col)``   — remaining period (yrs)
        for each layer at each year.

    Steps:
      1. Roll existing layers forward with one year of interest, less
         the prior year's payment accrued at half a year (mid-year).
      2. Set layer 0 to the residual ``ual - sum(rolled layers)``.
      3. Compute the new payment for each layer via ``_get_pmt``; layers
         with no remaining period or negligible debt get zero payment.

    Periods are non-negative integers in practice (CSV-loaded then
    decremented by 1 each year), so ``int(per)`` truncation is exact.

    Used by both the corridor (FRS) and gain/loss (TRS) funding paths;
    each plan calls it twice per year (current/legacy + future/new
    layer sets). The amort *table construction* (diagonal fill) is
    intentionally NOT unified — see the build_amort_period_tables
    helper and the TRS-side diagonal-shift code.
    """
    debt[i, 1:max_col + 1] = (
        debt[i - 1, :max_col] * (1 + dr)
        - pay[i - 1, :max_col] * (1 + dr) ** 0.5
    )
    debt[i, 0] = ual - debt[i, 1:max_col + 1].sum()
    for j in range(max_col):
        if per[i, j] > 0 and abs(debt[i, j]) > 1e-6:
            pay[i, j] = _get_pmt(
                dr, amo_pay_growth, int(per[i, j]), debt[i, j], t=0.5,
            )
        else:
            pay[i, j] = 0


def _populate_calibrated_nc_rates(f, liab, nc_cal, n_years):
    """Write the lag-1 calibrated normal cost rates onto the funding frame.

    For both funding paths::

        f.loc[1:, "nc_rate_db_legacy"] = liab.nc_rate_db_legacy_est * nc_cal  (lagged 1 yr)
        f.loc[1:, "nc_rate_db_new"]    = liab.nc_rate_db_new_est    * nc_cal  (lagged 1 yr)

    For cash-balance plans (TRS-style), also writes::

        f.loc[1:, "nc_rate_cb_new"]    = liab.nc_rate_cb_new_est            (lagged 1 yr)

    The CB write is gated on ``"payroll_cb_new_est" in liab.columns``,
    which is the cash-balance marker (FRS-style data does not have it).

    ``nc_cal`` MUST be passed in by the caller — do not look it up here.
    FRS reads it from ``constants.class_data[cn].nc_cal``; TRS reads from
    ``constants.class_data["all"].nc_cal`` with a ``funding_raw.nc_cal``
    legacy fallback. Pushing the lookup into this helper would break
    TRS's fallback chain (bit-identity risk #2 in the plan).
    """
    nc_legacy = liab["nc_rate_db_legacy_est"].values * nc_cal
    nc_new_db = liab.get(
        "nc_rate_db_new_est", pd.Series(np.zeros(n_years))
    ).values * nc_cal
    f.loc[1:, "nc_rate_db_legacy"] = nc_legacy[:-1]
    f.loc[1:, "nc_rate_db_new"] = nc_new_db[:-1]

    if "payroll_cb_new_est" in liab.columns:
        nc_new_cb = liab.get(
            "nc_rate_cb_new_est", pd.Series(np.zeros(n_years))
        ).values
        f.loc[1:, "nc_rate_cb_new"] = nc_new_cb[:-1]


def _ava_corridor_smoothing(ava_prev, net_cf, mva, dr):
    """Five-year corridor AVA smoothing (recognize 1/5 of gain/loss).

    Used by the corridor (FRS-style) funding path *at the plan-aggregate
    level*. The smoothed AVA is the prior AVA plus expected mid-year
    investment income, plus 1/5 of the gap to MVA, then bounded to the
    [80%, 120%] corridor around MVA::

        exp_inv_earnings_ava = ava_prev * dr + net_cf * dr / 2
        exp_ava              = ava_prev + net_cf + exp_inv_earnings_ava
        ava_unbounded        = exp_ava + (mva - exp_ava) * 0.2
        ava                  = clip(ava_unbounded, 0.8 * mva, 1.2 * mva)
        alloc_inv_earnings_ava = ava - ava_prev - net_cf
        ava_base             = ava_prev + net_cf / 2

    Returned values match the column names written by the original
    inline FRS smoothing block (legacy and new layers each get their
    own call). ``ava_base`` is the per-leg base used to allocate the
    plan-aggregate ``alloc_inv_earnings_ava`` to individual classes.
    """
    exp_inv_earnings_ava = ava_prev * dr + net_cf * dr / 2
    exp_ava = ava_prev + net_cf + exp_inv_earnings_ava
    ava = max(
        min(
            exp_ava + (mva - exp_ava) * 0.2,
            mva * 1.2,
        ),
        mva * 0.8,
    )
    alloc_inv_earnings_ava = ava - ava_prev - net_cf
    ava_base = ava_prev + net_cf / 2
    return {
        "exp_inv_earnings_ava": exp_inv_earnings_ava,
        "exp_ava": exp_ava,
        "ava": ava,
        "alloc_inv_earnings_ava": alloc_inv_earnings_ava,
        "ava_base": ava_base,
    }


def _accumulate_to_aggregate(target, source, i, cols):
    """Add ``source.loc[i, col]`` to ``target.loc[i, col]`` for each col.

    Used to roll per-class (or DROP) values up into a plan-aggregate
    DataFrame inside the funding loop. Pure scalar additions in the
    listed column order — no vector ``f.loc[i, cols] = values`` bulk
    write, because that can dtype-promote and produce different bytes
    (bit-identity risk #9 in the plan).
    """
    for col in cols:
        target.loc[i, col] += source.loc[i, col]


def _lookup_rate_schedule(schedule: list, year: int) -> float:
    """Look up a rate from a year-based schedule.

    Schedule is a list of {"from_year": Y, "rate": R} sorted ascending.
    Returns the rate for the latest entry where from_year <= year.
    """
    rate = schedule[0]["rate"]
    for entry in schedule:
        if year >= entry["from_year"]:
            rate = entry["rate"]
        else:
            break
    return rate
