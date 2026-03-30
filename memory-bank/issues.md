# Florida FRS Pension Model - Issues and Discrepancies

## Document Status
- **Created:** 2026-03-27
- **Last Updated:** 2026-03-28
- **Model Version:** Python migration in progress

---

## ⚠️ IMPORTANT: Git Workflow Rules

**NEVER commit directly to main branch!**

Always create a feature branch for any work:
```bash
git checkout -b feature/description-of-work
# ... do work ...
git add -A && git commit -m "message"
git push origin feature/description-of-work
# Then merge via PR or after approval
```

This applies to ALL changes, no matter how small.

---

## Known Issues

### 1. Model Architecture Issues (From Colleague Review)

#### 1.1 Data Quality Issues
- **Status:** Identified, pending fix
- **Description:**
  - Missing tier_3 entries for all 7 classes in benefit rules
  - Incomplete tier_2 benefit rules (regular/admin/special classes)
  - Salary growth rate transcription error (yos=7, regular: 4.4% should be 4.5%)
  - Class name inconsistency ("senior management" vs "senior_management")
  - Dollar unit convention mismatch (thousands vs actual dollars)

#### 1.2 Dual Data Structures
- **Status:** Design decision needed
- **Description:** Legacy format (329 rows) vs Better structures (847+ rows with rich metadata)
- **Impact:** Adapter functions needed to convert better → legacy

#### 1.3 FRS-Specific Logic Mixed with General Calculations
- **Status:** Partially addressed with adapter framework
- **Description:**
  - Band-to-single-year conversion embedded in adapters
  - Class-specific logic not fully abstracted
  - Tier-specific calculations still embedded in some functions

---

## Validation Results

### R Baseline Extraction
- **Date:** 2026-03-27
- **Status:** ✅ Complete
- **Files Created:** 67 files in baseline_outputs/
- **Warnings:** All benign (package masking, dplyr join messages)

### Baseline Data Summary

#### Workforce Data (All Classes)
| Class | Total Active | Total Terms | Total Refunds | Total Retirements |
|-------|-------------|-------------|---------------|-------------------|
| Regular | 16,618,372 | 2,325,091 | 906,187 | 7,302,971 |
| Special | 2,256,099 | 326,245 | 78,976 | 769,733 |
| Admin | 3,098 | 339 | 115 | 1,774 |
| ECO | 3,278 | 472 | 54 | 1,288 |
| ESO | 28,498 | 2,436 | 1,661 | 16,539 |
| Judges | 26,540 | 747 | 71 | 13,078 |
| Senior Mgmt | 235,450 | 33,807 | 9,353 | 112,576 |

#### Key Parameters
- Start Year: 2022
- Model Period: 30 years
- Discount Rate: 6.7%
- Payroll Growth: 3.25%
- Inflation: 2.4%

---

## Decrement Table Extraction (2026-03-28)

### Status: ✅ Complete

Extracted all decrement tables from R model Excel files:

**Withdrawal Tables (11 files):**
- Regular (male/female): 19,158 records each
- Special Risk (male/female): 3,193 records each
- Admin (male/female): 19,158 records each
- Senior Management (male/female): 3,193 records each
- ECO: 3,193 records
- ESO: 3,193 records
- Judges: 3,193 records

**Retirement Tables (6 files):**
- Normal retirement tier 1: 270 records (ages 45-80)
- Normal retirement tier 2: 220 records (ages 50-80)
- Early retirement tier 1: 160 records (ages 52-80)
- Early retirement tier 2: 136 records (ages 55-80)
- DROP entry tier 1: 270 records
- DROP entry tier 2: 270 records

**Location:** `baseline_outputs/decrement_tables/`

---

## Python vs R Comparison

### Validation Status (2026-03-28)

**Decrement Tables:** ✅ All 17 tables available and loading correctly

**R Baseline Data:** ✅ All 7 classes have workforce, liability, and funding data

**Workforce Summary (R Baseline):**
| Class | Active Count (Year 2022) |
|-------|------------------------|
| Regular | 536,077 |
| Special | 72,777 |
| Admin | 100 |
| ECO | 106 |
| ESO | 919 |
| Judges | 856 |
| Senior Management | 7,595 |

### Pending Comparisons
- [x] Run Python workforce projection and compare to R (Initial run complete)
- [ ] Compare liability calculations
- [ ] Compare funding calculations
- [ ] Compare benefit calculations

### Workforce Projection Validation (2026-03-28)

**Validation Script:** `scripts/run_full_workforce_validation.py`

**Method:** Simplified Python projection using average decrement rates vs R baseline

**Results Summary:**
| Class | Pass Rate | Max % Diff | Status |
|-------|-----------|------------|--------|
| Regular | 25.8% | 1.32% | FAIL |
| Special | 100.0% | 0.09% | PASS |
| Admin | 100.0% | 0.21% | PASS |
| ECO | 45.2% | 0.80% | FAIL |
| ESO | 19.4% | 1.91% | FAIL |
| Judges | 16.1% | 2.22% | FAIL |
| Senior Mgmt | 35.5% | 1.04% | FAIL |

**Overall:** 106/217 comparisons passed (48.8%)
### Workforce Projection Discrepancies (Updated 2026-03-28)

**Calibrated Projection Results:**

After implementing proper R-model new entrant logic:
`ne = sum(wf1)*(1+g) - sum(wf2)` where g=0:

| Class | Pass Rate | Max % Diff | Status | Notes |
|-------|-----------|------------|--------|-------|
| Regular | 100.0% | 0.00% | ✅ PASS | Perfect match with R baseline |
| Special | 100.0% | 0.00% | ✅ PASS | Perfect match with R baseline |
| Admin | 41.9% | 11.65% | ❌ FAIL | Uses Regular withdrawal table (may need own table) |
| ECO | 9.7% | 51.76% | ❌ FAIL | Uses Special Risk withdrawal table (may need own table) |
| ESO | 9.7% | 55.90% | ❌ FAIL | Uses Special Risk withdrawal table (may need own table) |
| Judges | 38.7% | 15.50% | ❌ FAIL | Uses Special Risk withdrawal table (may need own table) |
| Senior Mgmt | 9.7% | 26.62% | ❌ FAIL | Uses Special Risk withdrawal table (may need own table) |

**Root Cause for Remaining Discrepancies:**

The failing classes (ECO, ESO, Judges, Senior Management, Admin) are using withdrawal tables that may not be appropriate:
- ECO, ESO, Judges: Using Special Risk withdrawal table (3,193 records)
- Senior Management: Has own table but may have data issues
- Admin: Has own table though may have data issues

**Required Investigation:**
1. Verify withdrawal table assignments in DecrementLoader
2. Check if class-specific withdrawal tables are being loaded correctly
3. Review entrant profile distributions for failing classes
---

## Issues to Fix AFTER R Model Match (2026-03-30)

These are known inaccuracies that we are deliberately keeping to match R model output first. Fix after full validation passes.

### Issue #1: Retiree mortality in liability.py uses flat 5% rate
- **File:** `src/pension_model/core/liability.py:462`
- **Problem:** All retirees have same 5% annual mortality regardless of age
- **Correct approach:** Use actual mortality table (age-based qx from R baseline)
- **Impact:** Overstates mortality for younger retirees, understates for older

### Issue #2: Retiree COLA in liability.py hardcoded at 3%
- **File:** `src/pension_model/core/liability.py:466`
- **Problem:** Hardcoded `1.03` multiplier. FRS Tier 1 COLA is 3%, Tier 2 has no automatic COLA
- **Correct approach:** Use tier-specific COLA rates from config
- **Impact:** Overstates benefits for Tier 2 retirees

---

## Technical Debt

### High Priority
1. Complete adapter framework integration
2. Fix data quality issues in input tables
3. Implement full validation pipeline

### Medium Priority
1. Add unit tests for all calculation functions
2. Create integration tests against R baseline
3. Document all assumptions

### Low Priority
1. Performance optimization
2. Memory usage profiling
3. Add logging framework

---

## Resolved Issues

### 2026-03-27
- ✅ Fixed R extraction script syntax errors
  - Changed "senior management" to "senior_management" for consistency
  - Removed non-existent tier_4/5/6 retirement table references
- ✅ Created multi-plan adapter framework
- ✅ Refactored workforce and benefit modules to use adapters

---

## Notes

### For Future Development
1. The R model uses a complex data structure with multiple nested levels
2. Some calculations are spread across multiple R files
3. The Python implementation should maintain clear separation of concerns
4. All actuarial functions should be pure (no side effects)

### Validation Strategy
1. Compare year-by-year workforce totals
2. Compare liability roll-forwards
3. Compare funding calculations
4. Document any differences > 1%
