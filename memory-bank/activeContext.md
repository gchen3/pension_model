# Active Context

**Session Date:** 2026-03-30
**Current Phase:** Phase B COMPLETE - All Liability Components Validated

---

## Session Update (2026-03-30 - Projected Liability Validation COMPLETE)

### What Was Accomplished This Session

**Phase B: Benefit/Liability - FULLY VALIDATED**

1. **Extracted R benefit_table intermediate data** via `scripts/extract_liability_data.R`
   - `{class}_bt_term.csv` - cum_mort_dr for term vested discount
   - `{class}_bvt_term.csv` - pvfb_db_at_term_age from benefit_val_table
   - `{class}_bt_refund.csv` - db_ee_balance for refund calculations
   - `{class}_bt_retire.csv` - db_benefit, cola for projected retirees
   - `{class}_af_retire.csv` - ann_factor for projected retiree PVFB
   - `{class}_proj_components.csv` - per-year aggregated liability components

2. **Validated ALL projected liability components** (all 7 classes, 0.00% diff):
   - `aal_term_db_legacy_est` - term vested projected: 0.00%
   - `aal_term_db_new_est` - term vested new: 0.00%
   - `refund_db_legacy_est` - refund legacy: 0.00%
   - `refund_db_new_est` - refund new: 0.00%
   - `retire_ben_db_legacy_est` - retire benefit legacy: 0.00%
   - `retire_ben_db_new_est` - retire benefit new: 0.00%
   - `aal_retire_db_legacy_est` - retire AAL legacy: 0.00%
   - `aal_retire_db_new_est` - retire AAL new: 0.00%

3. **Validated total AAL aggregation** (all 7 classes, 0.00% diff):
   - `aal_legacy_est`: 0.00%
   - `aal_new_est`: 0.00%
   - `total_aal_est`: 0.00%
   - `tot_ben_refund_legacy_est`: 0.00%
   - `tot_ben_refund_new_est`: 0.00%
   - Liability gain/loss = 0.0 (confirms experience = assumptions)

### Phase B Complete Validation Summary

| Component | Status | Max Diff |
|-----------|--------|----------|
| Active payroll DB legacy | VALIDATED | 0.00% |
| Active PVFB DB legacy | VALIDATED | 0.00% |
| Active PVFNC DB legacy | VALIDATED | 0.00% |
| Active AAL DB legacy | VALIDATED | 0.00% |
| Active NC rate | VALIDATED | 0.00% |
| Projected term AAL (legacy+new) | VALIDATED | 0.00% |
| Projected retire AAL (legacy+new) | VALIDATED | 0.00% |
| Projected refund (legacy+new) | VALIDATED | 0.00% |
| Current retiree AAL | VALIDATED | 0.00% |
| Current term vested AAL | VALIDATED | 0.00% |
| Total AAL (all components) | VALIDATED | 0.00% |
| Liability gain/loss | VALIDATED | 0.0 |

### End-to-End Pipeline (2026-03-30)

**Built and validated**: Raw inputs → benefit tables → liability output
- All 7 classes: **0.0000%** diff vs R baseline
- Pipeline time: ~5 min for all classes
- 17 unit tests, all passing

**Key modules created:**
- `src/pension_model/core/model_constants.py` — All R constants in frozen dataclasses
- `src/pension_model/core/tier_logic.py` — Tier, benefit multiplier, reduction factor logic
- `src/pension_model/core/benefit_tables.py` — 8 table-building functions (salary→FAS→benefit→PVFB→NC)
- `src/pension_model/core/pipeline.py` — End-to-end orchestrator
- `tests/test_pension_model/test_benefit_tables.py` — 17 tests against R extractions

**Computation chain:**
1. salary_headcount_table (raw salary/headcount CSV → long format with entry_salary)
2. salary_benefit_table (salary projection, FAS, db_ee_balance per cohort)
3. separation_rate_table (withdrawal + retirement rates by tier)
4. ann_factor_table (cumulative survival × discount × COLA from mortality table)
5. benefit_table (db_benefit, pvfb_db_at_term_age)
6. benefit_val_table (PVFB, PVFS, NC via EAN method)
7. Liability aggregation (join workforce flows with benefit tables, aggregate by year)

**Bug found and fixed:** Admin's early retirement reduction factor used wrong NRA (55 instead of 62). R checks `class_name == "special"` only, not `class_name in ("special", "admin")`.

### Phase C: Funding Model (In Progress - 2026-03-30)

**Built:** `src/pension_model/core/funding_model.py` — full year-by-year funding projection
- Payroll projection (growth at payroll_growth assumption)
- Benefit payments/refunds from liability model
- Normal cost projection
- AAL roll-forward: AAL[t] = AAL[t-1]*(1+dr) + (NC-benefits-refunds)*(1+dr)^0.5 + gain/loss
- MVA projection: MVA[t] = MVA[t-1]*(1+ROA) + net_cf*(1+ROA)^0.5
- AVA smoothing: expected + 20% of (MVA-expected), bounded 80%-120% of MVA
- DROP: makeshift model tied to Regular class ratios
- FRS system: sum across all classes
- UAAL amortization: layered with declining periods
- Employer contributions: NC + amortization + admin + DC + solvency

**Current status:** AAL roll-forward close (~0.08% drift), but contributions diverge due to missing NC calibration factor. Next: implement nc_cal.

### What Remains

- NC rate calibration (nc_cal = val_norm_cost / model_norm_cost) — fixes contribution chain
- Debug AVA divergence (follows from NC fix)
- Validate all funding outputs against R for all 7 classes + DROP + FRS

### Key Technical Findings

1. **FAS uses lagged window**: R's `baseR.rollmean` computes FAS at yos=t as avg of salary[t-5:t], NOT salary[t-4:t+1]
2. **DB/DC allocation is 3-tier**: before_2018 (75% DB), after_2018 (25% DB), new>=2024 (0% to legacy, 25% to new)
3. **ben_payment_ratio**: R model input uses 0.9358, NOT 0.9602574 from calibration JSON
4. **Calibration factors**: cal_factor=0.9 applied to db_benefit globally; per-class NC factors are derived ratios
5. **Current retirees**: Projected using ann_factor_retire_table with mortality and COLA; PVFB = avg_ben * (ann_factor - 1)

---

## Session Update (2026-03-30)

### Phase A: Workforce Validation - COMPLETE
All 7 membership classes pass calibrated workforce validation at **100.0% (217/217 comparisons, 0.00% max difference)**. Active population counts match R baseline exactly for all 31 projection years.

**Important caveat:** The term/retire/refund stock accumulation logic differs from R model structure. R tracks cumulative stocks with aging; Python tracks flows differently. Active counts match perfectly because separation rates and new entrant logic are correct. The downstream stock differences will need attention when validating benefit/liability calculations.

### Bug Fixes Applied (2026-03-30)
1. **financial.py line 214** - `amortization_payment()` had undefined `payment` variable. Rewrote with proper annuity formula: `PMT = PV / annuity_factor`.
2. **retirement.py lines 319-325** - Three broken stub functions with missing comparison operands. Replaced with proper implementations.
3. **benefit.py line 170-178** - Mortality table column names wrong (`age`/`year` → `dist_age`/`dist_year`). Fixed with flexible column detection.
4. **benefit.py line 377** - `calculate_accrued_liability` missing `entry_year` parameter. Added.
5. **liability.py line 195** - Lambda in groupby replaced with pre-computed weighted columns.
6. **liability.py lines 178-181, 291-292, 337-338, 401-402** - `allocation[0]`/`[1]` integer indexing of dict-keyed DataFrame. Fixed to use `allocation['n_db_legacy']` etc.
7. **liability.py line 462** - Hardcoded 5% mortality for retirees. Replaced with age-based Gompertz approximation.
8. **liability.py line 465** - Hardcoded 1.03 COLA. Made configurable.

---

## Critical Bug Fixes (2026-03-29)

### 1. ESO Withdrawal Table Mapping Bug
**File:** [`src/pension_data/decrement_loader.py`](../src/pension_data/decrement_loader.py:185)

**Problem:** ESO mapped to "regular" (gender-specific) but code checked `class_name` instead of `table_class`

**Fix:**
```python
# Map class to table FIRST
table_class = WITHDRAWAL_CLASS_MAP.get(class_name)  # eso → "regular"

# Then check if table_class (not class_name) is gender-specific
if table_class in gender_classes:  # Check "regular" not "eso"
    filename = f"withdrawal_{table_class}_{gender}.csv"
```

### 2. New Entrant Calculation Formula Bug
**File:** [`src/pension_model/core/workforce.py`](../src/pension_model/core/workforce.py:268)

**Problem:** Python calculated new entrants AFTER separations, resulting in 0 new entrants when pop_growth=0

**R Model Formula** (utility_functions.R line 181):
```r
ne <- sum(wf1)*(1 + g) - sum(wf2)
# wf1 = workforce BEFORE separations
# wf2 = workforce AFTER separations
```

**Fixed Python:**
```python
pre_decrement_total = prev_state.active['n_active'].sum()   # BEFORE
post_decrement_total = active_aged['n_active'].sum()        # AFTER
new_entrants = pre_decrement_total * (1 + pop_growth) - post_decrement_total
```

**Impact:** Maintains workforce equilibrium when pop_growth=0 (R baseline uses 0% growth)

---

## Key Discovery: R Baseline Uses Zero Population Growth

From [`baseline_outputs/input_params.json`](../baseline_outputs/input_params.json):
```json
{"pop_growth": [0]}
```

**What This Means:**
- R maintains CONSTANT active population (e.g., Regular = 536,077 every year)
- New entrants exactly replace separations each year
- The 10-20% Python decline was due to calculating 0 new entrants with buggy formula

---

## Missing Functions - NOW IMPLEMENTED

The following functions were identified as missing but have been added:

### pension_tools/mortality.py
- `complement_of_survival()` - Calculate (1 - qx) values
- `survival_probability()` - Cumulative survival over age range

### pension_tools/retirement.py
- `is_normal_retirement_eligible()` - Check if member meets normal retirement age/YOS
- `is_early_retirement_eligible()` - Check if member meets early retirement criteria
- `calculate_early_retirement_factor()` - FRS 5% per year reduction formula

---

## Completed Work

### Phase 1: Foundation (COMPLETE)
- [x] Project structure established
- [x] Git repository initialized and pushed to https://github.com/donboyd5/pension_model.git
- [x] Memory bank structure created
- [x] Python environment confirmed (Python 3.14.0)

### Phase 2: Configuration (COMPLETE)
- [x] Configuration module implemented
  - `src/pension_config/plan.py` - Pydantic models for plan configuration
  - MembershipClass enum (7 classes)
  - FundingPolicy, AmortizationMethod, ReturnScenario, Tier enums
  - PlanConfig BaseModel with all plan parameters

### Phase 3: Data Module (COMPLETE)
- [x] Data module implemented
  - `src/pension_data/loaders.py` - ExcelLoader and CSVLoader classes
  - `src/pension_data/schemas.py` - Pydantic data models (long format design)
  - `src/pension_data/data_transformer.py` - Data transformers
  - Key Design: Long format for core data (one row = one entity)

### Phase 4: Tools Module (COMPLETE)
- [x] Pension tools module implemented
  - `src/pension_tools/financial.py` - Financial functions (PV, NPV, FV, discount factors, amortization)
  - `src/pension_tools/salary.py` - Salary growth functions
  - `src/pension_tools/mortality.py` - Mortality functions (qx, complement of survival, life expectancy)
  - `src/pension_tools/withdrawal.py` - Withdrawal rate functions
  - `src/pension_tools/retirement.py` - Retirement eligibility (normal/early checks, early factors)
  - `src/pension_tools/benefit.py` - Benefit calculations (normal cost, accrued liability, PVFB, PVFS)

### Phase 5: Pension Model Module (COMPLETE)
- [x] Core calculation engines implemented
  - `src/pension_model/core/workforce.py` - Workforce projection engine
    - WorkforceProjector class for projecting active, terminated, refund, retiree populations
    - Markov chain approach for population transitions
    - Year-by-year streaming to avoid keeping all years in memory

  - `src/pension_model/core/benefit.py` - Benefit calculation engine
    - BenefitCalculator class for calculating benefits, NC, AAL, PVFB, PVFS
    - Benefit formulas by membership class (Regular, Special Risk, etc.)
    - Tier determination logic (tier_1, tier_2, tier_3)
    - Annuity factor calculation with COLA

  - `src/pension_model/core/liability.py` - Liability calculation engine
    - LiabilityCalculator class for calculating actuarial liabilities
    - Plan design allocation (DB vs DC, legacy vs new)
    - Active, terminated, retiree, refund liabilities
    - Roll-forward method for AAL (matching R model approach)
    - Liability gain/loss calculation

  - `src/pension_model/core/funding.py` - Funding calculation engine
    - FundingCalculator class for calculating funding status
    - AAL roll-forward with mid-year timing: AAL_t = AAL_{t-1} * (1 + dr) + (NC - Benefits - Refunds) * (1 + dr)^0.5
    - Liability gain/loss calculation
    - Payroll projection with growth
    - Funding ratio calculation

  - `src/pension_model/model.py` - Main model orchestrator
    - PensionModel class coordinating all calculation engines
    - Data loading from Excel/CSV
    - Sequential execution: workforce → benefit → liability → funding
    - Results aggregation by membership class and year

### Phase 6: Output Module (COMPLETE)
- [x] Output generation module implemented
  - `src/pension_output/generators.py` - Output generators
    - OutputGenerator class for generating summaries and detailed tables
    - Workforce summary generation
    - Benefit summary generation
    - Liability summary generation
    - Funding summary generation
    - FRS system summary aggregation
    - Export to CSV, Excel, and JSON formats

### Phase 7: Validation Framework (COMPLETE)
- [x] Validation module implemented
  - `src/validation/comparators.py` - Comparison logic
    - ComparisonResult dataclass for single comparison
    - ComparisonSummary dataclass for summary of comparisons
    - ValidationConfig dataclass for tolerance levels
    - Validator class for validating Python outputs against R baseline
    - Compare at multiple tolerance levels (strict 1%, moderate 5%, lenient 10%)
    - Provide detailed discrepancy reports
    - Calculate pass/fail rates
  - Support for comparison by year, class, and metric

---

## Current Task

**Decrement Table Extraction** - COMPLETE (2026-03-28)

Extracted all decrement tables from R model's Excel files and integrated with Python model:

### Phase 8: Decrement Table Extraction (COMPLETE)
- [x] Created extraction script at `scripts/extract_decrement_tables.py`
- [x] Extracted withdrawal tables:
  - Special Risk (male/female variants)
  - Senior Management (male/female variants)
  - ECO, ESO, Judges (single tables)
  - Tables expanded from age bands to single ages (18-120)
- [x] Extracted retirement tables:
  - Normal retirement (tier 1 & tier 2)
  - Early retirement (tier 1 & tier 2)
  - DROP entry (tier 1 & tier 2)
- [x] Updated `src/pension_data/decrement_loader.py`:
  - New methods: `load_withdrawal_table()`, `load_retirement_table()`
  - Helper methods: `get_withdrawal_rate()`, `get_retirement_rate()`
  - Class mapping for retirement tables (regular→regular_non_k12, etc.)
  - Gender-aware loading for withdrawal tables

### Generated Files (baseline_outputs/decrement_tables/):
- `withdrawal_special_male.csv` - 3,193 records
- `withdrawal_special_female.csv` - 3,193 records
- `withdrawal_senior_management_male.csv` - 3,193 records
- `withdrawal_senior_management_female.csv` - 3,193 records
- `withdrawal_eco.csv` - 3,193 records
- `withdrawal_eso.csv` - 3,193 records
- `withdrawal_judges.csv` - 3,193 records
- `normal_retirement_tier1.csv` - 270 records (ages 45-80)
- `normal_retirement_tier2.csv` - 220 records (ages 50-80)
- `early_retirement_tier1.csv` - 160 records (ages 52-80)
- `early_retirement_tier2.csv` - 136 records (ages 55-80)
- `drop_entry_tier1.csv` - 270 records
- `drop_entry_tier2.csv` - 270 records

---

## Key Implementation Notes

**R Model Methodology:**
- Roll-forward method for AAL: AAL_t = AAL_{t-1} * (1 + dr) + (NC - Benefits - Refunds) * (1 + dr)^0.5
- Mid-year timing: NC accrual and benefit payments occur at mid-year (discounted by (1+dr)^0.5)
- Liability gain/loss: Difference between estimated and rolled-forward AAL

**Python Implementation:**
- All core engines follow R model's methodology
- Long format design for memory efficiency
- Year-by-year streaming to avoid keeping all years in memory
- Pure functions in tools module for testability
- Pydantic validation for type safety

**Baseline Extraction Status:**
- Script created at `scripts/extract_baseline.R`
- Only generated 2 files (input_params.json, salary_growth_table.csv)
- Full baseline extraction needs to be run to generate all comparison data

---

### Phase 9: Decrement Integration & Full Validation (COMPLETE - 2026-03-29)
- [x] Integrated DecrementLoader into FRSAdapter
- [x] Added table loading methods: load_withdrawal_table(), load_mortality_table(), load_retirement_table()
- [x] Enhanced adapter rate methods to use loaded tables with config fallback
- [x] Updated PensionModel.run_workforce_projection() to use adapter tables
- [x] Created test_decrement_integration.py - 2/3 tests passed
- [x] Ran full workforce validation - 48.8% overall pass rate (106/217 comparisons)

### Validation Results Summary:
- **Perfect Match** (100% pass): Special, Admin
- **Partial Match** (35-45% pass): ECO, Senior Management
- **Needs Work** (16-26% pass): Regular, ESO, Judges

### Key Findings:
- Framework working correctly (proven by Special/Admin perfect match)
- Divergence in Regular/ESO/Judges suggests:
  - Possible new entrant logic differences
  - ESO missing withdrawal table issue (should use Regular rates)
  - Benefit decision logic needs optimization (refund vs retire)

## Phase 10: Entrant Profile Extraction (COMPLETE - 2026-03-29)

### ✅ Entrant Profile Tables Extracted

Successfully extracted entrant profiles from R model using [`scripts/extract_entrant_profiles.R`](../scripts/extract_entrant_profiles.R)

**Location:** `baseline_outputs/entrant_profiles/`

| Class | Entry Ages | File |
|-------|------------|------|
| Regular | 11 (18-65) | `regular_entrant_profile.csv` |
| Special | 11 (18-65) | `special_entrant_profile.csv` |
| Admin | 5 (20-45) | `admin_entrant_profile.csv` |
| ECO | 8 (30-65) | `eco_entrant_profile.csv` |
| ESO | 9 (25-65) | `eso_entrant_profile.csv` |
| Judges | 8 (30-65) | `judges_entrant_profile.csv` |
| Senior Mgmt | 10 (20-65) | `senior_management_entrant_profile.csv` |

**Format:**
```csv
entry_age,start_sal,entrant_dist
18,12901.09,0.0097
20,23702.26,0.0893
25,31841.50,0.1555
...
```

**How R Creates Entrant Profiles** (from `Florida FRS benefit model.R` lines 55-59):
```r
entrant_profile <- salary_headcount_table %>%
  filter(entry_year == max(entry_year)) %>%   # Most recent entry year
  mutate(entrant_dist = count/sum(count)) %>% # Normalize to distribution
  select(entry_age, entry_salary, entrant_dist)
```

---

## Next Steps (Phase 11 - Integration & Validation)

### Pending Items:
1. ~~Fix ESO withdrawal table mapping~~ - DONE ✓
2. ~~Fix new entrant formula~~ - DONE ✓
3. ~~Extract entrant profiles~~ - DONE ✓
4. ~~Add remaining schemas~~ - DONE ✓ (WorkforceProjection, LiabilityResult, FundingResult)
5. ~~Test WorkforceProjector imports~~ - DONE ✓ (all imports working)
6. ~~Run equilibrium validation~~ - DONE ✓ (population constant at 100,000 over 30 years)
7. ~~Implement benefit decision optimization~~ - DONE ✓ (PV comparison for refund vs annuity)

---

## Phase 12: Benefit Decision Optimization (COMPLETE - 2026-03-29)

### Implemented Functions in [`src/pension_tools/benefit.py`](../src/pension_tools/benefit.py)

**1. `calculate_deferred_annuity_pv()`**
- Calculates PV of deferred monthly pension starting at retirement age
- Accounts for: final salary, YOS, benefit multiplier, discount rate, COLA

**2. `calculate_refund_pv()`**
- Calculates PV of immediate lump sum refund
- Includes employee contributions with credited interest

**3. `optimize_benefit_decision()`**
- Compares annuity PV vs refund PV
- Returns optimal decision: 'annuity' or 'refund'

### Test Results ([`scripts/test_benefit_decision.py`](../scripts/test_benefit_decision.py))

| Scenario | YOS | Age | Annuity PV | Refund PV | Decision |
|----------|-----|-----|------------|-----------|----------|
| Long-serving | 30 | 55 | $314,297 | $270,142 | ANNUITY |
| Short-serving | 6 | 35 | $10,739 | $16,873 | REFUND |
| Non-vested | 3 | 28 | $0 | $6,364 | REFUND |
| At retirement | 25 | 62 | $463,940 | $195,929 | ANNUITY |

### Key Logic
- Non-vested members (< 5 YOS) always get refund
- Long-serving members near retirement prefer annuity
- Young members with short service prefer refund

---

## File Structure

```
src/
├── pension_config/          # Configuration management
│   └── plan.py
├── pension_data/           # Data ingestion and standardization
│   ├── loaders.py
│   ├── schemas.py
│   └── data_transformer.py
├── pension_tools/          # Actuarial functions (pure functions)
│   ├── financial.py
│   ├── salary.py
│   ├── mortality.py
│   ├── withdrawal.py
│   ├── retirement.py
│   └── benefit.py
├── pension_model/          # Core calculations
│   ├── model.py            # Main orchestrator
│   └── core/
│       ├── workforce.py
│       ├── benefit.py
│       ├── liability.py
│       └── funding.py
├── pension_output/          # Output generation
│   └── generators.py
└── validation/              # Validation framework
    └── comparators.py
```

---

## Session Summary (2026-03-29)

### Completed Today:
1. ✅ Updated memory bank with bug fixes and R methodology
2. ✅ Extracted entrant profiles (7 classes) via R script
3. ✅ Added missing schemas (WorkforceProjection, LiabilityResult, FundingResult)
4. ✅ Verified all module imports working
5. ✅ Equilibrium validation passed (population constant at 100,000 over 30 years)
6. ✅ Implemented benefit decision optimization (PV comparison for refund vs annuity)

### Key Files Created/Modified:
- [`scripts/extract_entrant_profiles.R`](../scripts/extract_entrant_profiles.R) - Extracts entrant profiles from R
- [`baseline_outputs/entrant_profiles/`](../baseline_outputs/entrant_profiles/) - 7 entrant profile CSVs
- [`src/pension_data/schemas.py`](../src/pension_data/schemas.py) - Added WorkforceProjection, LiabilityResult, FundingResult
- [`scripts/test_equilibrium.py`](../scripts/test_equilibrium.py) - Equilibrium validation test
- [`src/pension_tools/benefit.py`](../src/pension_tools/benefit.py) - Added benefit decision optimization functions
- [`scripts/test_benefit_decision.py`](../scripts/scripts/test_benefit_decision.py) - Benefit decision test

### Framework Status:
- **All core features implemented**
- **All imports working**
- **Equilibrium validation passing**
- **Benefit decision optimization working**

---

## Notes

- User feedback: "please make sure you are familiar with pension math. R model is quite muddled I think, in terms of when and how they do calculations, although I think they are generally correct"
- Implemented roll-forward method for AAL calculation matching R model approach
- Mid-year timing: (1 + dr)^0.5 factor for NC accrual and benefit payments
- Liability gain/loss: Difference between estimated and rolled-forward AAL
- R baseline uses pop_growth=0 for workforce equilibrium
- New entrant formula: `ne = pre_decrement * (1 + g) - post_decrement`
