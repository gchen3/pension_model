# Pension Model Validation Issues and Findings

## Overview

This document tracks findings from validating the Python pension model against the R baseline for the Florida Retirement System (FRS) Pension Plan.

## Validation Status

### Current Results (2026-03-29)

**Phase 1 - Simple Growth Model**: ✅ All 7 classes passed with 0% difference
**Phase 2 - Decrement Integration**: ⚠️ Mixed results with 48.8% overall pass rate

| Class | Pass Rate | Max % Diff | Status | Notes |
|-------|-----------|------------|--------|-------|
| Special | 100.0% | 0.09% | ✅ PASS | Excellent match |
| Admin | 100.0% | 0.21% | ✅ PASS | Excellent match |
| ECO | 45.2% | 0.80% | ⚠️ PARTIAL | Diverges after year 15 |
| Senior Management | 35.5% | 1.04% | ⚠️ PARTIAL | Declining trend |
| Regular | 25.8% | 1.32% | ❌ NEEDS WORK | Large divergence |
| ESO | 19.4% | 1.91% | ❌ NEEDS WORK | Missing withdrawal table |
| Judges | 16.1% | 2.22% | ❌ NEEDS WORK | Growing divergence |

**Overall**: 106/217 comparisons passed (48.8%)

### Test Configuration

- **Start Year**: 2022
- **Model Period**: 30 years
- **Discount Rate**: 6.7%
- **Payroll Growth**: 3.25%
- **Decrement Tables**: ✅ Loaded and accessible via adapter

## Key Findings from Phase 2 Validation

### ✅ Successfully Working

1. **Decrement Table Integration**
   - All withdrawal, mortality, and retirement tables loading correctly
   - Regular withdrawal table: 19,158 records
   - Regular mortality table: 2,977,459 records
   - Adapter caching tables for performance

2. **Perfect Match Classes**
   - Special Risk: 100% pass rate (max 0.09% difference)
   - Admin: 100% pass rate (max 0.21% difference)
   - These classes demonstrate the framework CAN achieve accuracy

3. **Adapter Pattern Working**
   - `FRSAdapter.load_withdrawal_table()` ✅
   - `FRSAdapter.load_mortality_table()` ✅
   - `FRSAdapter.get_withdrawal_rate()` ✅
   - `FRSAdapter.get_mortality_rate()` ✅

### ⚠️ Issues Identified

1. ~~**ESO Missing Withdrawal Table**~~ - ✅ FIXED (2026-03-29)
   - ESO should use Regular class withdrawal rates (per R model line 588)
   - **Root Cause**: Code checked `class_name` instead of `table_class` for gender mapping
   - **Fix**: Map to table_class FIRST, then check if gender-specific
   - ESO now correctly loads Regular withdrawal rates (19,158 records)

2. ~~**Diverging Projections**~~ - ✅ ROOT CAUSE FOUND (2026-03-29)
   - Regular, ECO, ESO, Judges, Senior Management showed 10-20% divergence
   - **Root Cause**: New entrant formula calculated AFTER separations instead of BEFORE
   - **Fix**: Track pre_decrement_total and post_decrement_total separately
   - R formula: `ne = sum(wf1)*(1+g) - sum(wf2)` where wf1=before, wf2=after
   - With pop_growth=0, new entrants now exactly replace separations

3. **Validation Script Issue** - NEEDS FIX
   - Current validation uses "simplified projection" logic
   - Doesn't use actual WorkforceProjector class
   - Framework fixes not reflected in validation results
   - **Action Required**: Update script to use actual WorkforceProjector

4. **Missing Entrant Profile Data** - BLOCKING
   - R model develops entrant profiles from lowest-YOS cohort(s)
   - Need `{class}_entrant_profile_table` for each membership class
   - Format: `entry_age,entrant_dist` distribution
   - **Action Required**: Extract from R workspace or recreate logic

## Outstanding Issues

### 1. Distribution Files Not Extracted

**Status**: Pending R script execution

The salary/headcount distribution files from `R_model/R_model_original/Reports/extracted inputs/` need to be extracted using the updated `extract_baseline.R` script.

**Files needed**:
- `{class}_dist_count.csv` - Member count by age/YOS grid
- `{class}_dist_salary.csv` - Average salary by age/YOS grid

**Action**: Run the R extraction script:
```r
cd R_model/R_model_original
Rscript ../../scripts/extract_baseline.R
```

### 2. Decrement Tables Integration

**Status**: ✅ COMPLETE (Phase 1 & 2)

#### Mortality
- [x] Created `src/pension_tools/mortality.py` with standard actuarial functions
- [x] Load mortality tables from baseline outputs via adapter
- [x] FRSAdapter.load_mortality_table() working (2.9M+ records per class)
- [x] Apply mortality to active and terminated members in WorkforceProjector

#### Withdrawal/Separation
- [x] Enhanced `src/pension_tools/withdrawal.py` with table loading
- [x] Load withdrawal tables from baseline outputs (19K+ records)
- [x] FRSAdapter.load_withdrawal_table() with gender support
- [x] FRSAdapter.get_withdrawal_rate() using loaded tables
- [ ] ESO withdrawal table mapping issue (should use Regular rates)

#### Retirement
- [x] Enhanced `src/pension_tools/retirement.py` with FRS rules
- [x] Load retirement eligibility tables from baseline outputs
- [x] FRSAdapter.load_retirement_table() by tier/type
- [ ] Apply benefit decisions (retire vs. refund) - needs optimization logic
- [ ] Calculate early retirement factors - in adapter

### 3. Workforce Model Refinements

**Status**: Framework exists, needs integration

The `WorkforceProjector` class in `src/pension_model/core/workforce.py` has the structure for:
- State transitions: Active -> Terminated -> (Refund | Retire) -> Death
- Year-by-year projection
- New entrant handling

**Needs**:
- Integration with loaded decrement tables
- Proper benefit decision logic
- Validation against R baseline year-by-year transitions

### 4. Liability Calculations

**Status**: Not yet validated

The liability model needs validation for:
- [ ] Present Value of Future Benefits (PVFB)
- [ ] Accrued Liability (AL) - Entry Age Normal method
- [ ] Normal Cost (NC)
- [ ] Actuarial Liability for terminated/retired members

### 5. Funding Calculations

**Status**: Not yet validated

The funding model needs validation for:
- [ ] Employer contributions
- [ ] Employee contributions
- [ ] Amortization of unfunded liability
- [ ] Actuarially required contribution (ARC)

## Technical Notes

### Actuarial Methodology

The model follows Winklevoss pension actuarial mathematics:

1. **Survival Probability**:
   - n_p_x = probability of surviving n years from age x
   - Calculated recursively: n_p_x = p_x * (n-1)_p_(x+1)

2. **Discounting**:
   - Present value = payment * v^n where v = 1/(1+i)
   - Discount rate: 6.7% (current valuation rate)

3. **Decrement Model**:
   - Multiple decrement tables for mortality, withdrawal, retirement
   - Dependent vs. independent rates

### FRS-Specific Rules

- **Benefit Multipliers**:
  - Regular: 1.6% (Tier 1), graded1.6-1.68% (Tier 2), 1.65% (Tier 3)
  - Special Risk: 2.0% per YOS
  - Judges: 3.3% per YOS

- **Retirement Eligibility**:
  - Regular Tier 1: Age 62 or6 YOS
  - Regular Tier 2: Age 60 or8 YOS
  - Special Risk: Age 55 or6 YOS

- **COLA**:
  - Tier 1: 3.0% per year
  - Tier 2/3: Variable based on investment returns

## Root Cause Analysis

### Why Special and Admin Pass but Others Fail

**Hypothesis**: Different projection methodologies or parameters

1. **Special & Admin**: Smaller populations, may use simpler projection logic in R
2. **Regular**: Largest class, complex age/YOS distribution causes divergence
3. **Judges**: Growing instead of declining - suggests different new hire assumptions
4. **ESO**: Missing withdrawal table causing default rate usage

### Specific Issues to Investigate

1. **New Entrant Calculation**
   - Python uses: `target = total_active * (1 + pop_growth)`
   - R may use class-specific growth rates or entry age distributions
   - Check if entrant_profile properly loaded for each class

2. **Withdrawal Rate Application**
   - Verify age/YOS lookup matches R model exactly
   - Check if gender-specific rates being used correctly
   - ESO should use Regular rates - verify mapping works

3. **Benefit Decision Logic**
   - Currently placeholder: assumes all eligible members retire
   - R model optimizes refund vs annuity based on present value comparison
   - Need to implement PV comparison for optimal benefit decision

## Next Steps (Prioritized)

### Immediate (Phase 3)
1. **Fix ESO withdrawal table loading** - Verify eso → regular mapping
2. **Review new entrant logic** - Check entrant profiles and distribution
3. **Compare one detailed year** - Pick year 2025, compare cell-by-cell for Regular class
4. **Document age/YOS distribution** - Understand entry cohort structure

### Short-term (Phase 4)
5. **Implement benefit decision optimization** - Refund vs annuity PV comparison
6. **Validate tier determination logic** - Ensure correct tier assignment
7. **Validate mortality application** - Verify survival probabilities match R
8. **Run liability calculations** - Compare NC, AAL, PVFB, PVFS

### Medium-term (Phase 5)
9. **Validate funding calculations** - Compare funding ratios and contributions
10. **Performance profiling** - Identify optimization opportunities
11. **Create comprehensive test suite** - Unit tests for all components
12. **Document generalization guide** - How to add new pension plans

## Calibration Investigation Issues

Issues identified by `pension-model calibrate` diagnostics (2026-03-31).
These are model improvement investigations — NOT bugs in the current R-matching implementation.

### CAL-1: Investigate cal_factor=0.9 origin

The R model uses `cal_factor=0.9` as a global benefit multiplier, reducing all computed DB benefits by 10%. The R source comment says: "Calibration factor for the benefit model. This is to adjust the normal cost to match the normal cost from the val report."

Evidence suggests the R modelers (Reason Foundation) set 0.9 as a rounded first approximation. After applying it, the two largest classes (regular, special) have nc_cal ~0.985, needing only ~1.5% further adjustment. **Can we derive a more principled value?** Does 0.9 correspond to a known actuarial concept (DB participation, benefit accrual pattern, workforce composition)?

### CAL-2: Admin class nc_cal=1.40 — model underestimates NC by 40%

The admin class requires nc_cal=1.40, meaning the model's computed normal cost is only 72% of the actuarial valuation value (0.10436 vs 0.14570). This is by far the largest calibration factor. Investigate:
- Is the admin benefit formula correct?
- Are the admin salary/headcount distributions accurate?
- Is there something structurally different about admin that the model doesn't capture?

### CAL-3: ECO class nc_cal=0.83 — model overestimates NC by 17%

ECO has the lowest nc_cal (0.83), meaning the model produces 20% higher NC than the AV. ECO also has a 20% AAL gap. Investigate whether ECO data or benefit rules differ from what the model assumes.

### CAL-4: Payroll systematically underestimated (~93% of AV for regular)

Out-of-sample check shows model payroll is systematically ~93% of AV payroll for the regular class. This may relate to DB/DC plan participation ratios, headcount adjustments, or salary scale assumptions. Since payroll is not calibrated, this gap flows through to NC dollar amounts and benefit payments.

### CAL-5: R model forces payroll growth rate

The R model appears to force total payroll to grow at the assumed payroll_growth rate (3.25%). In actuarial practice, the payroll growth assumption is used for amortization calculations (level % of payroll), but actual projected payroll should emerge from the demographic model (headcounts x salary scale x decrements). These are conceptually different. Investigate whether the R model conflates the two and whether it matters for results.

### CAL-6: Additional calibration targets

Currently we calibrate only NC rate and AAL. Other quantities that could serve as calibration targets or out-of-sample checks:
- PVFB (present value of future benefits)
- PV future salary
- First-year benefit payments
- Active/retiree headcounts
- Funded ratio (if AVA is known)

These would provide richer diagnostics on where the model is accurate vs where it diverges. For a future calibration_targets.json.

### CAL-7: Static calibration vs policy run architecture

Calibration factors should be computed once against the baseline AV and stored in JSON. Policy analysis runs (different discount rate, mortality table, etc.) reuse the same calibration — they don't recalibrate. The calibration captures structural model gaps, not assumption sensitivity. This architectural principle should be documented and enforced as we add scenario/policy run support.

## References

- Winklevoss, H.E. "Pension Mathematics with Numerical Illustrations"
- FRS 2022 Actuarial Valuation Report
- R model: `R_model/R_model_original/`
