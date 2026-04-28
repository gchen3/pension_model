# TXTRS-AV Year-0 Validation Against AV Table 2

## Purpose

This note compares the txtrs-av year-0 (2024) liability output to the
AV Table 2 published values. It is a diagnostic for understanding where
the model diverges from the AV before any calibration is applied.

## How to reproduce

```
pension-model run txtrs-av --no-test
python scripts/diagnostic/compare_txtrs_av_to_av.py
```

Output is also saved as `prep/txtrs-av/reports/av_comparison_year0.csv`
for spreadsheet review.

## Comparison

```
==========================================================================================
Quantity                                              Model             AV            Gap
==========================================================================================
Active total payroll (cohort-derived)          $     57.44B   $     57.48B         -0.07%
PVFB - active members                          $    184.98B   $    187.88B         -1.55%
PVFB - retirees in pay or deferred             $    133.20B   $    133.93B         -0.54%
PVFB - retiree future survivor                            0   $      2.08B       -100.00%
PVFB - vested inactive                                    0   $      7.51B       -100.00%
PVFB - inactive nonvested                                 0   $      1.22B       -100.00%
PVFB - total                                   $    318.18B   $    332.62B         -4.34%
PVFNC (employee + employer)                    $     62.89B   $     59.52B         +5.66%
AAL - active (PVFB - PVFNC)                    $    122.09B   $    128.36B         -4.89%
AAL - current retirees                         $    133.20B   $    133.93B         -0.54%
AAL - other (term + survivor + nonvested)                 0   $     10.81B       -100.00%
AAL - total                                    $    255.29B   $    273.10B         -6.52%
==========================================================================================
```

## Where the Gap Comes From

Total AAL is $17.81B below AV (-6.52%). Decomposing:

| Bucket | Model | AV | Gap | Share of total gap |
|---|---|---|---|---|
| Active AAL | $122.09B | $128.36B | -$6.27B | 35% |
| Current-retiree AAL | $133.20B | $133.93B | -$0.72B | 4% |
| Other (term + survivor + nonvested) AAL | $0 | $10.81B | -$10.81B | 61% |
| **Total** | $255.29B | $273.10B | -$17.81B | 100% |

These three buckets imply three distinct issues, with three distinct
fixes.

### Issue A: Term-vested and other inactive members not modeled (61% of gap)

The model returns zero AAL for term-vested members, future survivor
benefits, and inactive nonvested members. The runtime architecture has
this path: the legacy `txtrs` plan reports $10.46B of `aal_term`,
matching the AV's $10.81B closely.

The mechanism is the runtime config field
`funding.term_vested_method = "bell_curve"` and a calibration constant
`pvfb_term_current` per class in `config/calibration.json`. Inspection
of `core/calibration.py` shows that `pvfb_term_current` is computed as
`val_aal - model_aal` after the rest of calibration has run; the
runtime then renders that value as `aal_term_current_est`, which adds
to `total_aal_est`. So in the current architecture the term-vested
liability is treated as a calibration plug, not as a separate
demographic cohort.

The txtrs-av plan_config explicitly omits `term_vested_method` from its
runtime fields. That omission, plus the absence of
`config/calibration.json`, is why the term AAL bucket is zero.

### Issue B: PVFNC overstated, AAL_active understated (35% of gap)

Active PVFB matches AV within 1.55% (model $184.98B vs AV $187.88B).
That is strong validation of the active grid, salary projection,
decrements, and discount-rate handling.

Where the active gap shows up is on the PVFNC side: model reports
$62.89B vs AV $59.52B — model is +5.66% over AV. Since
`AAL_active = PVFB_active - PVFNC` by identity, an over-projected
PVFNC produces an under-projected active AAL.

Implied gross NC rate:
- AV: 12.10% (Table 2 line 4a, published)
- Model implied: $62.89B PVFNC / ~$491B implied PVFS ≈ 12.79%

So the model is computing a slightly higher entry-age normal cost rate
than the AV. The legacy `txtrs/config/calibration.json` carries
`nc_cal = 0.999` and a `cal_factor = 0.993` that together align the
model's NC and benefits to the AV. txtrs-av has neither.

### Issue C: Current-retiree AAL slightly under (4% of gap)

Model retiree AAL is 0.54% below AV. Comfortably within the 3%
validation tolerance. Likely sources, in rough priority order:

- mortality basis difference: txtrs-av uses the TX-custom approximation
  estimator, which is anchored to TRS 2021 sample checkpoints but
  does not exactly reproduce the AV's full table
- retiree-distribution lumping: ages "Up to 35" through "55-59" all
  collapsed into runtime ages 55-59, which slightly compresses the age
  profile
- minor convention differences in how the runtime applies the
  improvement scale to current retirees

This bucket does not need its own fix; calibration and the existing
mortality/retiree-distribution issues capture it.

## What Matches Well

These quantities validate the cohort-derived AV-faithful build:

- active total payroll within 0.07% of AV
- active PVFB within 1.55% of AV
- current-retiree AAL within 0.54% of AV
- AVA, MVA, projected payroll match AV exactly through the
  `init_funding.csv` seed

## Recommended Next Steps

1. Run the existing calibration tool (`pension-model calibrate txtrs-av`)
   to produce `config/calibration.json`. This will:
   - compute `cal_factor` to align model PVFB to AV PVFB (closes most of
     the active-side gap)
   - compute per-class `nc_cal` to align model NC rate to AV NC rate
     (closes the PVFNC excess)
   - compute per-class `pvfb_term_current` to absorb the residual gap
     (the term-vested + survivor + nonvested + retiree-side residual)
   - bring total AAL within the 3% tolerance by construction

2. Re-run this comparison after calibration to confirm closure and
   document the calibrated alignment.

3. The substantive modeling gaps that calibration would mask are
   already tracked:
   - issue #48 — `pvfb_term_current` should eventually be replaced by an
     explicit current term-vested liability model. The AV publishes
     usable inputs (138,146 vested-inactive members, $7.51B PVFB) that
     would feed such a model directly.
   - issue #42 — TRS NC rate convention diverges from AV. Although
     #42 is framed around DC payroll in the denominator (not relevant
     for txtrs-av which is DB-only), the symptom — model NC rate higher
     than AV NC rate — is the same here. Worth a follow-up to confirm
     the same convention difference applies to txtrs-av's DB-only
     setup.
