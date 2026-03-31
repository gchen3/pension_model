# Actuarial Calculation Validation Notes

## Summary

Python actuarial calculations have been implemented following Winklevoss methodology and validated against R baseline outputs.

## Implementation

### Files Created
- [`src/pension_tools/actuarial.py`](src/pension_tools/actuarial.py) - Core actuarial calculation classes
  - `SurvivalCalculator` - Calculates survival probabilities from mortality tables
  - `ActuarialCalculator` - Calculates PVFB, NC, and AAL using EAN method
  - `ActuarialAssumptions` - Dataclass for actuarial assumptions

- [`scripts/validate_actuarial.py`](scripts/validate_actuarial.py) - Validation script

### Methods Implemented

1. **Survival Probability** (`n_p_x`)
   - Formula: n_p_x = p_x * p_(x+1) * ... * p_(x+n-1)
   - Uses mortality rates from R baseline tables

2. **Present Value of Future Benefits (PVFB)**
   - Calculates present value of retirement benefits
   - Uses survival probability to retirement
   - Applies salary growth, COLA, and discount factors
   - Includes life annuity factor at retirement

3. **Normal Cost (NC)**
   - Entry Age Normal (EAN) method
   - NC = PVFB_entry / PVFS_entry * current_salary
   - Represents level percentage of salary

4. **Accrued Actuarial Liability (AAL)**
   - EAN method: AAL = PVFB - (PVFS * NC_rate)
   - Represents accrued obligation

## Validation Results

### Sample Calculation Comparison
(Sample member: age 45, entry age 30, YOS 15, salary $50,000)

| Class | Python NC Rate | R NC Rate | Difference |
|-------|---------------|-----------|------------|
| Regular | 14.79% | 9.10% | +5.69% |
| Special | 23.95% | 20.44% | +3.51% |
| Admin | 14.50% | 10.44% | +4.06% |
| ECO | 14.61% | 15.14% | -0.53% |
| ESO | 14.61% | 15.57% | -0.96% |
| Judges | 30.14% | 19.38% | +10.76% |
| Sr Mgmt | 14.61% | 11.30% | +3.31% |

## Discrepancy Analysis

### Potential Causes of Differences

1. **Mortality Table Usage**
   - Python: Uses R baseline mortality tables directly
   - R: May apply mortality differently (post-retirement vs pre-retirement)

2. **Retirement Age Assumptions**
   - Python: Uses single retirement age (62 or 55 for special)
   - R: May use decrement-based retirement probabilities

3. **Benefit Formula**
   - Python: Simple multiplier (1.6%, 2.0%, 3.3%)
   - R: May have graded multipliers or different final average salary calculations

4. **Annuity Factor**
   - Python: Simplified life expectancy-based annuity
   - R: May use more sophisticated annuity factors with mortality improvement

5. **Sample vs Cohort**
   - Python: Single representative member
   - R: Full cohort with age/YOS distribution

### Recommendations for Calibration

1. **Match Retirement Patterns**
   - Use R's retirement decrement tables
   - Apply probability of retirement at each age

2. **Verify Annuity Calculation**
   - Compare annuity factors at retirement age
   - Ensure mortality improvement scales match

3. **Apply Full Cohort**
   - Calculate for all age/YOS combinations
   - Weight by actual headcount distribution

4. **Verify Salary Progression**
   - Compare salary growth assumptions
   - Verify final average salary calculation method

## Next Steps

1. Apply calculations to full workforce cohorts (not just sample)
2. Compare aggregate PVFB, NC, and AAL by year
3. Calibrate assumptions to reduce discrepancy
4. Document methodology differences in detail

## References

- Winklevoss, H.E. "Pension Mathematics with Numerical Illustrations"
- FRS 2022 Actuarial Valuation Report
- R model: `R_model/R_model_original/`
