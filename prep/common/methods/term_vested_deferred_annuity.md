# Method: Current term-vested deferred annuity

- Method id: `term_vested_deferred_annuity_v1`
- Status: `candidate`
- Type: `documented estimation`
- Scope: AV-first plans and any new plan. Not used by the legacy R-anchored
  FRS or TXTRS pipelines, which carry their own one-off methods.

## Purpose

Estimate the year-by-year benefit cashflow stream for the current
term-vested cohort (members who have left active service but are not
yet collecting benefits). Used as runtime input
`plans/{plan}/data/funding/current_term_vested_cashflow.csv`.

The stream is needed because most plans publish only a single rolled-up
present value of future benefits for this cohort
(`pvfb_term_current`), not the underlying member-level cashflows. We
estimate a representative cashflow that, when discounted at the
baseline rate, recovers that PV. Year-by-year, the stream then drives
how Component 1 of the AAL declines over the projection.

## Inputs

- `pvfb_term_current` per class — from
  `plans/{plan}/config/calibration.json`.
- `economic.dr_current` — from `plans/{plan}/config/plan_config.json`,
  used as the baseline rate `r` against which the stream is calibrated.
- `benefit.cola.current_retire` — from plan config, used as the COLA
  growth `cola` during the payout phase.
- `term_vested.avg_deferral_years` (`D`) and
  `term_vested.avg_payout_years` (`L`) — from plan config.

`D` and `L` are plan-level scalars sourced from the AV's term-vested
demographics. `D` approximates the gap between the average current age
of term-vested members and the assumed distribution age. `L`
approximates remaining life expectancy (or the desired payout window)
at the distribution age.

## Cashflow shape

Two phases by year offset `t = 1, 2, ...`:

| years | payment |
|---|---|
| `1..D` | `0` |
| `D+1..D+L` | `c * (1 + cola)^(t - D - 1)` |

where `c` is the calibrated first-payment scalar.

## Calibration

Choose `c` so that NPV at the baseline rate equals
`pvfb_term_current`. Closed form:

```
v = 1 / (1 + r)
g = (1 + cola) / (1 + r)
factor = v^(D + 1) * (1 - g^L) / (1 - g)             if g != 1
factor = L * v^(D + 1)                               if g == 1
c = pvfb_term_current / factor
```

NPV(stream, r) == pvfb_term_current by construction, modulo
floating-point.

## Why this shape

A current term-vested member is not in payment status. Real cashflow
has a deferral phase (until distribution age) and then an
annuity-in-payment phase (until death). The deferred-then-annuity shape
captures both. Compared to legacy methods that omit the deferral
(growing annuity over 50 years from year 1) or peak in the middle
(bell curve), this method produces more realistic duration and
therefore more honest sensitivity to discount-rate stress.

This is "good now, refine later" rather than the actuarial last word.
A future refinement replaces `L` with a true survival-weighted annuity
factor at the distribution age, using mortality and COLA tables. That
is a strictly better version of the same shape and would still match
this method's NPV identity.

## Outputs

`plans/{plan}/data/funding/current_term_vested_cashflow.csv`, with
columns:

- `class_name`
- `year_offset` (1..D+L)
- `payment`

## Validation

- NPV identity: NPV(stream, baseline rate) ≈ pvfb_term_current to
  floating-point precision. Build script asserts and
  `scripts/build/verify_term_vested_cashflow.py` checks again.
- Reasonableness: zero payments in years 1..D, level-times-COLA growth
  in years D+1..D+L, zero after.
- Cross-plan: AV-first plans should produce comparable shapes; large
  outliers in `D` or `L` warrant a documentation pass.

## Implementation

- `scripts/build/term_vested_deferred_annuity.py` — closed-form helper.
- `scripts/build/build_av_term_vested_cashflow.py` — plan-driver that
  reads plan config and calibration, calls the helper, writes the CSV.
- Used by: `txtrs-av`. Future AV-first plans (e.g., `frs-av`) call the
  same driver with their own plan name.

## Plan examples

| plan | D | L | cola | notes |
|---|---|---|---|---|
| txtrs-av | 12 | 25 | 0 | First-cut defaults; refine from valuation term-vested demographics. |

## Failure modes and limits

- The single-scalar `L` averages over all members; a plan with a wide
  age distribution among term-vested members will have less accurate
  per-year shape than one with a tight distribution.
- COLA is treated as a flat plan-wide rate. Plans with conditional or
  stepped COLAs need additional treatment.
- The method assumes all term-vested members eventually collect; refund
  takeup is not modeled here (and is generally not material at the
  plan-aggregate PVFB level).
