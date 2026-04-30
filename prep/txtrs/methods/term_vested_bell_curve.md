# Method: TXTRS current term-vested bell curve (legacy R)

- Method id: `term_vested_bell_curve_txtrs_v1`
- Status: `legacy_only` — preserved to match the TXTRS R baseline
  exactly. Not used by any other plan and not recommended for new
  plans, which use the shared deferred-annuity method documented in
  [`prep/common/methods/term_vested_deferred_annuity.md`](../../common/methods/term_vested_deferred_annuity.md).
- Type: `legacy reconstruction`
- Scope: TXTRS only.

## Purpose

Build the year-by-year benefit cashflow stream for the TXTRS current
term-vested cohort. Output goes to
`plans/txtrs/data/funding/current_term_vested_cashflow.csv` and the
runtime reads it.

The shape of the stream and the construction algorithm match the TXTRS
R model so that the Python runtime's truth tables for TXTRS are
unchanged when the runtime stops constructing the stream in the year
loop and starts reading it as input data.

## Inputs

- `pvfb_term_current` — from `plans/txtrs/config/calibration.json`
  (single class, `all`).
- `economic.dr_current` — from
  `plans/txtrs/config/plan_config.json`, used as the baseline rate.
- `funding.amo_period_term` — number of payment years (50 for TXTRS;
  default).

## Algorithm

Normal-distribution-weighted payments over `amo_period_term` years,
calibrated so that NPV at the baseline rate equals
`pvfb_term_current`.

1. Build weights `w_t = N(t; mean=amo_period/2, sd=amo_period/5)` for
   `t = 1, 2, ..., amo_period`.
2. Form the ratio `ann_ratio_t = w_t / w_1`.
3. `first_payment = pvfb_term_current / NPV(ann_ratio, dr_current)`.
4. `payment_t = first_payment * ann_ratio_t`.

NPV of the stream at `dr_current` equals `pvfb_term_current` by
construction.

## Why this shape is preserved

The TXTRS R model uses this exact construction. Reproducing it
bit-identically is the precondition for the runtime PR (which moves
the construction out of the year loop) leaving TXTRS truth tables
unchanged. Any improvement to actuarial fidelity is out of scope here;
the AV-first variant `txtrs-av` uses the shared deferred-annuity
method instead.

The shape's weakness is that the bell-curve symmetry has no
actuarial basis: it implies payments grow toward the middle of the
amortization window and decline symmetrically, which is unlike a real
deferred-then-annuity term-vested cashflow. See issue #64 for the
larger context and #76 for the refactor that retires this method from
the runtime dispatch.

## Outputs

`plans/txtrs/data/funding/current_term_vested_cashflow.csv`, columns:

- `class_name` — `all`
- `year_offset` — 1..50
- `payment`

## Validation

- NPV identity: NPV(stream, `dr_current`) ≈ `pvfb_term_current` to
  floating-point precision. Build script asserts and
  `scripts/build/verify_term_vested_cashflow.py` checks again.
- Bit-identical match: the produced stream equals the stream the
  runtime currently constructs in
  `compute_current_term_vested_liability` (bell-curve branch) for
  every year. Verify script enforces this via direct array
  comparison.

## Implementation

- `scripts/build/build_txtrs_term_vested_cashflow.py` — uses the same
  weight construction and `_npv` helper the runtime uses today, so
  exact reproduction is by construction, not by tuning.

## Failure modes and limits

- The bell-curve shape is a stylized smoothing pattern, not an
  actuarial cashflow. It is preserved only for R parity.
- The normal-distribution parameters (`mean = amo_period/2`,
  `sd = amo_period/5`) are R-model conventions with no published
  derivation.
