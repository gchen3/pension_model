"""Shared deferred-annuity method for current term-vested cashflows.

Used by AV-first plans (txtrs-av, frs-av) and any future plan. The two
legacy-R methods (FRS growing annuity, TXTRS bell curve) are NOT
expressed through this module; they live alongside their own plans as
one-off legacy reconstructions.

Method
======

A current term-vested member has not yet started collecting benefits.
Two phases:

  1. Deferral period of D years - no payments (member is waiting until
     the assumed distribution age).
  2. Annuity in payment of L years - level-with-COLA cashflow during
     the assumed payout window.

Stream by year_offset t (t=1 means the first projection year after the
valuation date):

  t in 1..D       -> payment = 0
  t in D+1..D+L   -> payment_t = c * (1 + cola)^(t - D - 1)

The scalar c is calibrated so that NPV at the baseline discount rate
equals the published pvfb_term_current. Closed-form:

  v = 1 / (1 + r)
  g = (1 + cola) / (1 + r)
  factor = v^(D+1) * (1 - g^L) / (1 - g)              if g != 1
  factor = L * v^(D+1)                                if g == 1
  c = pvfb_term_current / factor

So NPV(stream, r) == pvfb_term_current by construction, modulo
floating-point.

Why this is better than the legacy methods for AV-first plans
=============================================================

Legacy FRS (growing annuity over 50 years starting in year 1) and TXTRS
(bell curve peaking at year 25) both ignore that term-vested members
are not yet in pay status. The deferred-then-annuity shape captures the
most important first-order property of the real cashflow: there is a
deferral period, then payments. Duration under rate stress moves more
realistically. Per-plan parameters (D, L, cola) should be sourced from
the AV's term-vested demographics; defaults can be tuned later.

Out of scope
============

- True survival-weighted annuity using mortality and COLA tables. That
  is a refinement of L (or replaces it with a true life annuity factor
  at the assumed distribution age). The simpler scalar L is "good
  enough now" per the design discussion in issue #76.
- Joint-life or beneficiary continuation.
- Plan-specific tier or class-conditional deferral periods.
"""

from __future__ import annotations


def deferred_annuity_stream(
    pvfb_term_current: float,
    baseline_rate: float,
    cola: float,
    deferral_years: int,
    payout_years: int,
) -> list[float]:
    """Return the year_offset 1..(D+L) payment stream.

    Years 1..D are zeros; years D+1..D+L grow at cola from the
    calibrated first payment. NPV at baseline_rate equals
    pvfb_term_current.
    """
    if deferral_years < 0 or payout_years <= 0:
        raise ValueError(
            f"deferral_years must be >= 0 and payout_years must be > 0; "
            f"got {deferral_years}, {payout_years}"
        )

    n = deferral_years + payout_years
    stream = [0.0] * n
    if pvfb_term_current == 0:
        return stream

    v = 1.0 / (1.0 + baseline_rate)
    g = (1.0 + cola) / (1.0 + baseline_rate)
    if abs(g - 1.0) < 1e-12:
        factor = payout_years * v ** (deferral_years + 1)
    else:
        factor = v ** (deferral_years + 1) * (1.0 - g ** payout_years) / (1.0 - g)

    c = pvfb_term_current / factor

    for k in range(payout_years):
        stream[deferral_years + k] = c * (1.0 + cola) ** k

    return stream
