# Florida FRS Pension Model - Issues and Discrepancies

## Document Status
- **Created:** 2026-03-27
- **Last Updated:** 2026-03-27
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

## Python vs R Comparison

### Pending Comparisons
- [ ] Workforce projection by year
- [ ] Liability calculations
- [ ] Funding calculations
- [ ] Benefit calculations

### Discrepancies Found
*None yet - comparison not complete*

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
