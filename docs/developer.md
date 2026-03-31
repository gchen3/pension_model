# Developer Guide

## Getting Started

```bash
pip install -e .                    # install in development mode
pension-model frs                   # run FRS model + tests
pension-model frs --no-test         # run without tests
pension-model frs --test-only       # tests only
pension-model calibrate             # compute and print calibration diagnostics
pension-model calibrate --write     # also write to configs/frs/calibration.json
```

## Project Layout

```
configs/
  frs/
    calibration.json          # Calibration factors (loaded at runtime)
  scenarios/                  # Future: scenario parameter overrides
src/pension_model/
  core/
    model_constants.py        # All model parameters; loads calibration from JSON
    benefit_tables.py         # Actuarial table construction
    pipeline.py               # Liability computation pipeline
    funding_model.py          # Funding projection (assets, contributions, amortization)
    calibration.py            # Calibration computation and diagnostics
    tier_logic.py             # Plan-specific tier and benefit rules
    cohort_calculator.py      # Cohort-level benefit calculations
    workforce.py              # Workforce projection
  cli.py                      # CLI entry point
baseline_outputs/             # R baseline data and extracted inputs
tests/test_pension_model/     # All tests
docs/                         # Documentation
```

## Calibration Workflow

See [calibration.md](calibration.md) for full details.

### When to run calibration

- **After changing benefit formulas, salary scales, or decrement tables** — these affect the model's raw NC rate and AAL, so calibration factors need recomputing.
- **After updating plan data** (new valuation year, new AV targets) — the targets changed, so recalibrate.
- **NOT after changing policy/scenario assumptions** (discount rate, mortality improvement, COLA) — calibration is a one-time baseline adjustment; scenario runs reuse it.

### Workflow

```bash
# 1. Make your changes to model code or data
# 2. Recalibrate and review diagnostics
pension-model calibrate

# 3. If diagnostics look reasonable, write the new calibration
pension-model calibrate --write

# 4. Run the model to verify outputs
pension-model frs

# 5. All 41+ tests should pass
```

### Red flags in calibration diagnostics

- `nc_cal` outside [0.8, 1.2] — the model is structurally off for that class
- `pvfb_term_current` > 20% of `val_aal` — large unexplained liability gap
- Payroll ratio far from 1.0 — workforce/salary data issues

These suggest model or data problems, not just calibration needs.

## Adding a New Plan

_TODO: document when we generalize beyond FRS_

1. Create `configs/{plan}/calibration.json`
2. Create plan-specific constants (like `frs_constants()`)
3. Provide baseline data in `baseline_outputs/` or equivalent
4. Run `pension-model calibrate {plan}` to compute calibration
5. Add tests

## Testing

```bash
pytest tests/test_pension_model/ -v          # all tests
pytest tests/test_pension_model/test_calibration.py -v   # calibration only
pytest tests/test_pension_model/test_funding_baseline.py -v  # R baseline match
```

### Test categories

- **Benefit table tests** — verify actuarial tables match R extraction
- **Funding baseline tests** — verify full pipeline output matches R for all 7 classes
- **Calibration tests** — verify computed calibration matches stored JSON values

## Architecture Principles

- **Reproduce R first** — match R model results exactly before making improvements
- **Calibration is static** — computed once at baseline, reused for policy runs
- **Calibration should be small** — large factors indicate model problems, not just calibration needs
- **Create issues for improvements** — don't fix model errors in the calibration branch
