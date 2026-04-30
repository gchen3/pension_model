# Method: FRS current term-vested growing annuity (legacy R)

- Method id: `term_vested_growing_annuity_frs_v1`
- Status: `legacy_only` — preserved to match the FRS R baseline
  exactly. Not used by any other plan and not recommended for new
  plans, which use the shared deferred-annuity method documented in
  [`prep/common/methods/term_vested_deferred_annuity.md`](../../common/methods/term_vested_deferred_annuity.md).
- Type: `legacy reconstruction`
- Scope: FRS only.

## Purpose

Build the year-by-year benefit cashflow stream for the FRS current
term-vested cohort. Output goes to
`plans/frs/data/funding/current_term_vested_cashflow.csv` and the
runtime reads it.

The shape of the stream and the construction algorithm match the FRS R
model so that the Python runtime's truth tables for FRS are unchanged
when the runtime stops constructing the stream in the year loop and
starts reading it as input data.

## Inputs

- `pvfb_term_current` per class — from
  `plans/frs/config/calibration.json`.
- `economic.dr_current` — from `plans/frs/config/plan_config.json`,
  used as the baseline rate.
- `economic.payroll_growth` — also from plan config; the growth rate
  applied year over year to the level-percent-of-payroll first
  payment.
- `funding.amo_period_term` — number of payment years (50 for FRS).

## Algorithm

Level-percent-of-payroll amortization with growth.

1. Compute `first_payment` so that, when grown at `payroll_growth`
   over `amo_period_term` years and discounted at `dr_current`, the
   resulting stream's NPV equals `pvfb_term_current`. This is the
   standard `PMT()` of a growing annuity (R `get_pmt`, mirrored in
   Python by `_get_pmt`).
2. Build the payment stream `payment_t = first_payment * (1 + payroll_growth)^(t - 1)`
   for `t = 1, 2, ..., amo_period_term`.

NPV of the stream at `dr_current` equals `pvfb_term_current` by
construction.

## Why this shape is preserved

The FRS R model uses this exact construction. Reproducing it
bit-identically is the precondition for the runtime PR (which moves
the construction out of the year loop) leaving FRS truth tables
unchanged. Any improvement to actuarial fidelity is out of scope here;
the AV-first variant of FRS would use the shared deferred-annuity
method instead.

The shape's main weakness is that it has no deferral period —
term-vested members are modeled as paying out from year 1, even though
in reality most are not yet at distribution age. This understates
duration and biases rate-stress sensitivities low. See issue #64 for
the larger context and #76 for the refactor that retires this method
from the runtime dispatch.

## Outputs

`plans/frs/data/funding/current_term_vested_cashflow.csv`, columns:

- `class_name` — one row per FRS class
- `year_offset` — 1..50
- `payment`

## Validation

- NPV identity: NPV(stream, `dr_current`) ≈ `pvfb_term_current` to
  floating-point precision. Build script asserts and
  `scripts/build/verify_term_vested_cashflow.py` checks again.
- Bit-identical match: the produced stream equals the stream the
  runtime currently constructs in
  `compute_current_term_vested_liability` (growing-annuity branch) for
  every class and year. Verify script enforces this via direct
  array comparison.

## Implementation

- `scripts/build/build_frs_term_vested_cashflow.py` — uses the same
  `_get_pmt` and `_recur_grow3` helpers the runtime uses today, so
  exact reproduction is by construction, not by tuning.

## Failure modes and limits

- Single-class outputs depend on per-class `pvfb_term_current`
  calibration values; if calibration drifts, this stream drifts with
  it.
- The level-percent-of-payroll shape is a smoothed amortization
  pattern, not an actuarial cashflow. It is preserved here only for R
  parity.
