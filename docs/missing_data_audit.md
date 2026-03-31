# Missing Data & Functions Audit
**Date:** 2026-03-29
**Purpose:** Identify all missing imports blocking WorkforceProjector testing

---

## 🔍 Import Errors Found

### 1. Missing Pension Tools Functions

#### pension_tools/mortality.py
**Missing:**
- `complement_of_survival` - Referenced in benefit.py line 37

**Should Implement:**
```python
def complement_of_survival(qx_values: list) -> list:
    """
    Calculate complement of survival probability.

    Args:
        qx_values: List of mortality rates

    Returns:
        List of survival probabilities (1 - qx)
    """
    return [1 - qx for qx in qx_values]


def survival_probability(qx_table: dict, start_age: int, end_age: int) -> float:
    """
    Calculate probability of surviving from start_age to end_age.

    Formula: product of (1 - qx) for each age
    """
    prob = 1.0
    for age in range(start_age, end_age):
        qx = qx_table.get(age, 0.0)
        prob *= (1 - qx)
    return prob
```

---

#### pension_tools/retirement.py
**Missing:**
- `is_normal_retirement_eligible` - Referenced in benefit.py line 40
- `is_early_retirement_eligible` - Referenced in benefit.py line 41
- `early_retirement_factor` - Referenced in benefit.py line 42

**Should Implement:**
```python
def is_normal_retirement_eligible(age: float, yos: float, normal_age: float, normal_yos: float) -> bool:
    """Check if member is eligible for normal retirement."""
    return age >= normal_age and yos >= normal_yos


def is_early_retirement_eligible(age: float, yos: float, early_age: float, early_yos: float) -> bool:
    """Check if member is eligible for early retirement."""
    return age >= early_age and yos >= early_yos


def calculate_early_retirement_factor(
    current_age: float,
    current_yos: float,
    normal_age: float,
    normal_yos: float,
    reduction_per_year: float = 0.05
) -> float:
    """
    Calculate early retirement reduction factor.

    FRS uses 5% per year early (whichever is greater: age or YOS).
    """
    months_early_age = max(0, (normal_age - current_age) * 12)
    months_early_yos = max(0, (normal_yos - current_yos) * 12)
    months_early = max(months_early_age, months_early_yos)

    # 5% per year = 0.4167% per month, max 50%
    reduction = min(0.50, months_early * 0.004167)
    return 1.0 - reduction
```

---

#### pension_tools/benefit.py
**Missing:**
- `normal_cost` - Referenced in benefit.py line 45
- `accrued_liability` - Referenced in benefit.py line 46
- `pvfb` - Referenced in benefit.py line 47
- `pvfs` - Referenced in benefit.py line 48

**NOTE:** These may already exist in benefit.py - check if circular import issue

---

### 2. Missing Schemas

#### pension_data/schemas.py
**Missing:**
- `WorkforceProjection` - Referenced in workforce.py line 23
- `LiabilityResult` - Referenced in liability.py line 23
- `SalaryHeadcountRecord` - Referenced in model.py (should be `SalaryHeadcountData`)

**Current Schemas:** (from search results)
- `SalaryHeadcountData` ✓
- `MortalityRate` ✓
- `WithdrawalRate` ✓
- `RetirementEligibility` ✓
- `SalaryGrowthRate` ✓
- `EntrantProfile` ✓
- `BenefitValuation` ✓

**Should Add:**
```python
class WorkforceProjection(BaseModel):
    """Workforce projection result."""
    year: int
    entry_age: int
    age: int
    n_active: float
    n_term: Optional[float] = None
    n_refund: Optional[float] = None
    n_retire: Optional[float] = None


class LiabilityResult(BaseModel):
    """Liability calculation result."""
    year: int
    aal: float
    nc: float
    pvfb: float
    pvfs: Optional[float] = None
```

---

## 📂 Missing Baseline Data Files

### Salary/Headcount Distribution Files
**Status:** Mentioned in issues.md but not yet extracted

**Location (if available from R):**
- R_model/R_model_original/Reports/extracted inputs/

**Files Needed:**
- salary and headcount distribution of regular.pdf → regular_dist.csv
- salary and headcount distribution of admin.pdf → admin_dist.csv
- salary and headcount distribution of eco.pdf → eco_dist.csv
- salary and headcount distribution of eso.pdf → eso_dist.csv
- salary and headcount distribution of judges.pdf → judges_dist.csv
- salary and headcount distribution of senior management.pdf → senior_management_dist.csv

**Format Expected:**
```csv
entry_age,age,count,average_salary
25,25,1000,50000
25,26,950,52000
...
```

---

### Year-by-Year R Baseline Outputs
**Status:** We have summary JSON but not detailed CSVs

**Currently Have:**
- `{class}_wf_summary.json` - Totals only ✓
- `{class}_liability_summary.json` - Totals only ✓

**Would Be Helpful:**
- `{class}_wf_active_yearly.csv` - Active by year/age/entry_age
- `{class}_wf_term_yearly.csv` - Terminated by year
- `{class}_wf_retire_yearly.csv` - Retired by year

**Format:**
```csv
year,entry_age,age,n_active
2022,25,25,1000
2022,25,26,950
2023,25,26,1050
...
```

---

### Entrant Profile Tables
**Status:** Unknown if loaded correctly

**File Pattern:** `{class}_entrant_profile_table`

**Format Expected:**
```csv
entry_age,entrant_dist
25,0.40
30,0.30
35,0.20
40,0.075
45,0.025
```

**Action:** Check if these exist in R model or baseline outputs

---

## 🔧 Specific Files to Check/Extract

### From R Model Directory

1. **Check if entrant profiles exist:**
```r
# In R workspace after running model
regular_entrant_profile_table
special_entrant_profile_table
# etc.
```

2. **Extract year-by-year workforce:**
```r
# After running get_wf_data()
write.csv(wf_active_regular, "regular_wf_active_yearly.csv")
# Flatten 3D array to long format
```

3. **Extract separation tables used:**
```r
# Check what the actual separation_rate_table looks like
regular_separation_rate_table
# Should have entry_age, age, entry_year, separation_rate
```

---

## 🎯 Priority List

### HIGH PRIORITY (Blocking Test)
1. **Entrant profile tables** - Need for WorkforceProjector test
2. **Separation tables in correct format** - Currently using extracted decrement tables

### MEDIUM PRIORITY (For Validation)
3. **Year-by-year R baseline** - For detailed comparison
4. **Salary/headcount distributions** - For proper initialization

### LOW PRIORITY (Nice to Have)
5. **Benefit decision tables from R** - Shows optimal refund vs retire
6. **Annuity factor tables from R** - For liability validation

---

## 🔍 How to Extract from R

### Option 1: Run R Extraction Script
```r
# Should be in: scripts/extract_baseline.R
source("scripts/extract_baseline.R")
```

### Option 2: Manual Extraction
```r
# Load R model
source("R_model/R_model_original/Florida FRS master.R")

# For each class, extract:
for (class_name in c("regular", "special", "admin", "eco", "eso", "judges", "senior_management")) {
  # Get data
  wf_data <- get_wf_data(class_name = class_name)

  # Save entrant profile
  profile <- get(paste0(class_name, "_entrant_profile_table"))
  write.csv(profile, paste0("baseline_outputs/", class_name, "_entrant_profile.csv"))

  # Save separation table
  sep_table <- get(paste0(class_name, "_separation_rate_table"))
  write.csv(sep_table, paste0("baseline_outputs/", class_name, "_separation_table.csv"))
}
```

---

## 📋 Summary

**What I Have:**
- ✓ Decrement tables (withdrawal, retirement, mortality)
- ✓ Summary totals from R baseline
- ✓ Input parameters

**What Would Help:**
1. **Entrant profile tables** - Most critical for testing
2. **Year-by-year R outputs** - For detailed validation
3. **Separation tables** - To verify we're using correct format

**Can I Work Without Them?**
- **Partially** - Can create mock entrant profiles for testing
- **But** - Real profiles needed for accurate R matching
- **Alternative** - Extract directly from R model if you can run it

Would you like me to:
A) Create mock data and proceed with testing?
B) Create an R extraction script you can run?
C) Wait while you locate the actual data files?
