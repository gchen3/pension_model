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

import pandas as pd


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
