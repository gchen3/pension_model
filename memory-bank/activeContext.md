# Active Context

**Session Date:** 2026-03-27
**Current Phase:** Validation Framework Complete

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

**Implementing validation framework** - COMPLETE

All core calculation engines and validation framework have been implemented:

1. **Workforce Projection** - Projects population through Markov chain
2. **Benefit Calculation** - Calculates benefits using tier-specific formulas
3. **Liability Calculation** - Uses roll-forward method matching R model
4. **Funding Calculation** - AAL roll-forward with mid-year timing
5. **Validation Framework** - Compares Python to R baseline with configurable tolerances

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

## Next Steps

1. **Fix R baseline extraction script** - Ensure all outputs are generated
2. **Run R baseline extraction** - Execute `Rscript scripts/extract_baseline.R`
3. **Validate against R baseline** - Run validation framework comparing Python outputs to R baseline
4. **Document discrepancies in issues.md** - Track differences between Python and R
5. **Performance optimization** - Profile and optimize critical calculation paths

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

## Notes

- User feedback: "please make sure you are familiar with pension math. R model is quite muddled I think, in terms of when and how they do calculations, although I think they are generally correct"
- Implemented roll-forward method for AAL calculation matching R model approach
- Mid-year timing: (1 + dr)^0.5 factor for NC accrual and benefit payments
- Liability gain/loss: Difference between estimated and rolled-forward AAL

- Baseline extraction script needs to be fixed to generate complete baseline outputs
- Once baseline is available, validation framework can compare Python outputs to R baseline
