# Calibration

## Overview

Calibration adjusts the model so that its baseline outputs match the actuarial valuation (AV) report. It accounts for structural gaps between what the model computes from first principles and what the actuary reports. Ideally calibration factors are small — large factors indicate model or data problems worth investigating.

## Architecture

Calibration is computed **once** against the baseline AV and stored in `plans/{plan}/config/calibration.json`. Policy analysis runs (different discount rate, mortality table, etc.) reuse the same calibration factors — they do not recalibrate. The calibration captures structural model gaps, not assumption sensitivity.

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  AV targets      │     │  Uncalibrated     │     │  calibration.json   │
│  (init_funding,  │────>│  pipeline run     │────>│  (cal_factor,       │
│   val_norm_cost) │     │  (nc_cal=1.0,     │     │   nc_cal per class, │
│                  │     │   pvfb_term=0)    │     │   pvfb_term_current │
└─────────────────┘     └──────────────────┘     │   per class)        │
                                                   └────────┬────────────┘
                                                            │
                                                            v
                                                   ┌─────────────────────┐
                                                   │  Policy/scenario    │
                                                   │  runs load fixed    │
                                                   │  calibration from   │
                                                   │  JSON               │
                                                   └─────────────────────┘
```

## The Three Calibration Factors

### 1. `cal_factor` (global, currently 0.9)

- **What**: Multiplied into every DB benefit calculation
- **Where**: `core/benefit_tables.py` and `core/cohort_calculator.py`
- **Formula**: `db_benefit = yos * ben_mult * fas * reduce_factor * cal_factor`
- **Effect**: Reduces all computed benefits by 10%
- **Origin**: Set by the R modelers (Reason Foundation) as a rounded first approximation. The R source comment says: "Calibration factor for the benefit model. This is to adjust the normal cost to match the normal cost from the val report."
- **Evidence**: After applying 0.9, the two largest classes (regular, special) need only ~1.5% further NC adjustment via nc_cal, confirming 0.9 was tuned for the dominant classes.

### 2. `nc_cal` (per class, range 0.83–1.40)

- **What**: Multiplied into normal cost rates in the funding model
- **Where**: `core/funding_model.py`
- **Formula**: `nc_cal = val_norm_cost / model_norm_cost`
- **Effect**: Adjusts each class's NC rate to match the AV exactly
- **Computed by**: `pension-model calibrate`

The model computes NC rates with `cal_factor=0.9` already applied. `nc_cal` is the residual adjustment. Values near 1.0 mean the model is accurate for that class; values far from 1.0 indicate the model is systematically off.

| Class | nc_cal | Interpretation |
|-------|--------|----------------|
| regular | 0.985 | Model NC 1.5% too high — excellent |
| special | 0.985 | Model NC 1.5% too high — excellent |
| senior_management | 0.961 | Model NC 4% too high — good |
| eso | 0.940 | Model NC 6% too high — acceptable |
| judges | 0.917 | Model NC 8% too high — investigate |
| eco | 0.828 | Model NC 17% too high — investigate |
| admin | 1.396 | Model NC 40% too low — investigate |

### 3. `pvfb_term_current` (per class, range -$2M to $6.6B)

- **What**: The AAL gap between model and AV, amortized as a growing payment stream
- **Where**: `core/pipeline.py` (`compute_current_term_vested_liability`)
- **Formula**: `pvfb_term_current = val_aal - model_aal`
- **Effect**: Adds a liability component that closes the AAL gap over 50 years
- **Computed by**: `pension-model calibrate`

## Running Calibration

```bash
pension-model calibrate frs              # compute and print diagnostics
pension-model calibrate frs --write      # overwrite plans/frs/config/calibration.json
pension-model calibrate frs --write --output path/to/calibration.json
```

Output includes:
- **Normal cost calibration table**: model NC vs AV NC, nc_cal factor, flags for outliers
- **AAL calibration table**: model AAL vs AV AAL, pvfb_term_current, gap percentage
- **Out-of-sample checks**: quantities NOT calibrated (e.g., payroll) that serve as model quality indicators

## Diagnostic Interpretation

### Healthy calibration
- nc_cal between 0.8 and 1.2 for all classes
- pvfb_term_current < 10% of val_aal
- Out-of-sample ratios near 1.0

### Red flags (investigate the model, not just calibrate)
- nc_cal outside [0.8, 1.2] — model is structurally off for that class
- pvfb_term_current > 20% of val_aal — large unexplained liability gap
- Payroll ratio far from 1.0 — workforce/salary data issues

## Key Files

```
plans/{plan}/config/calibration.json   # Computed calibration factors (loaded at runtime)
src/pension_model/core/calibration.py  # Calibration computation and diagnostics
src/pension_model/plan_config.py       # PlanConfig loads calibration; acfr_data holds AV targets
```

## Targets

Calibration targets come from the `acfr_data` section of `plan_config.json`:
- `val_norm_cost`: per-class normal cost rate from the AV
- `val_aal`: per-class total AAL from the AV

Optional diagnostic targets (reported but not calibrated against):
- `val_payroll`: per-class total payroll from the AV (used for out-of-sample checks)
