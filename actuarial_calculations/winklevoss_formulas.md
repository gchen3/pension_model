# Winklevoss Pension Mathematics - Key Formulas Reference

**Source:** `actuarial_calculations/winklevoss_converted.pdf` - "Pension Mathematics with Numerical Illustrations" 2nd Edition, Howard E. Winklevoss (1993)

This file summarizes the core actuarial formulas from the textbook so they don't need to be re-read from the PDF each session.

---

## Chapter 1: Model Pension Plan

The Winklevoss model plan assumptions (used for all numerical illustrations):

| Parameter | Value |
|---|---|
| Benefit formula | 1.5% of final 5-year avg salary × years of service |
| Normal retirement age (r) | 65 |
| Early retirement | Age 55 with 10 years of service, actuarially reduced |
| Vesting | Full after 5 years of service |
| Disability eligibility | Age 40 with 10 years of service |
| Death benefit | 50% of accrued benefit to surviving spouse |
| Employee contributions | None |
| Annuity form | Straight life annuity |

---

## Chapter 2: Actuarial Assumptions

### Decrement Rates

Four types of decrement (single-decrement rates denoted with prime `q'`):
- `q'^(m)` = mortality rate (1971 GAM Table for males)
- `q'^(t)` = termination rate (select & ultimate, 5-year select period, entry-age dependent)
- `q'^(d)` = disability rate (age-based only)
- `q'^(r)` = retirement rate (ages 55-65)

**Multi-decrement probability (UDD approximation):**

For a 4-decrement environment, the probability of decrement from cause k:

```
q^(1) ≈ q'^(1) × [1 - ½q'^(2)] × [1 - ½q'^(3)] × [1 - ½q'^(4)]
```

This converts single-decrement *rates* into multi-decrement *probabilities*.

**Mortality survival (n years):**
```
n_p_x^(m) = ∏(t=0 to n-1) (1 - q_{x+t}^(m)) = ∏(t=0 to n-1) p_{x+t}^(m)
```

**Termination survival:** Same form as mortality but using `q'^(t)` rates.

**Early Retirement Rates (Table 2-9):**

| Age | Rate |
|-----|------|
| 55-59 | 0.05 |
| 60 | 0.20 |
| 61 | 0.30 |
| 62 | 0.40 |
| 63 | 0.30 |
| 64 | 0.30 |
| 65 | 1.00 |

### Salary Assumption

Three components:
1. **Merit** - age-specific scale (Table 2-10), starts at 1.000 at age 20, reaches 2.769 at age 65
2. **Productivity** - 1% per annum (constant)
3. **Inflation** - 4% per annum (constant)

**Salary projection formula:**
```
s_x = s_y × (SS_x / SS_y) × [(1+I)(1+P)]^(x-y)
```
Where:
- `s_y` = entry-age dollar salary
- `SS_x` = merit salary scale at age x
- `I` = inflation rate (0.04)
- `P` = productivity rate (0.01)

**Cumulative salary:**
```
S_x = Σ(t=y to x-1) s_t
```

### Interest Assumption

Total rate = 8%, composed of:
- Risk-free rate: 1%
- Risk premium: 3% (2% bonds + 4% stocks, 50/50 mix)
- Inflation: 4%

**Discount factor:**
```
v = 1/(1+i), so v^n = 1/(1+i)^n
```

---

## Chapter 3: Basic Actuarial Functions

### Composite Survival Function

Probability of active participant age x surviving one year in service:
```
p_x^(T) = (1 - q'^(m)_x)(1 - q'^(t)_x)(1 - q'^(d)_x)(1 - q'^(r)_x)
```

Equivalently using multi-decrement probabilities:
```
p_x^(T) = 1 - (q_x^(m) + q_x^(t) + q_x^(d) + q_x^(r))
```

**n-year composite survival:**
```
n_p_x^(T) = ∏(t=0 to n-1) p_{x+t}^(T)
```

### Service Table

- `l_x^(T)` = survivors at age x (from initial radix, e.g., 1,000,000)
- `d_x^(T) = l_x^(T) × q_x^(T)` = total decrements at age x
- `d_x^(T) = d_x^(m) + d_x^(t) + d_x^(d) + d_x^(r)`

### Interest (Discount) Function

```
v = 1/(1+i)
```
Present value of $1 due in n years: `v^n`

### Salary Function

**Current dollar salary at age x:**
```
s_x = s_y × (SS_x / SS_y) × [(1+I)(1+P)]^(x-y)
```

**Salary from intermediate age z:**
```
s_x = s_z × (SS_x / SS_z) × [(1+I)(1+P)]^(x-z)
```

### Benefit Function

**Benefit accrual at age x:** `b_x` (annual benefit earned during age x to x+1)

**Accrued benefit at age x:**
```
B_x = Σ(t=y to x-1) b_t
```

**Three benefit formula types:**

1. **Flat dollar:** `b_x = constant`, `B_x = (x-y) × b_x`

2. **Career average:** `b_x = k × s_x`, `B_x = k × S_x`

3. **Final average:**
```
B_r = k(r-y) × (1/n) × (S_r - S_{r-n})    [projected benefit at retirement]
B_x = k(x-y) × (1/n) × (S_x - S_{x-n})    [accrued benefit at age x]
```
Where n = averaging period (e.g., 5 years), k = benefit rate per year of service (e.g., 0.015)

**Benefit proration modifications:**

- **Constant Dollar (CD):** `b_x = B_r / (r-y)` — pro rata share of projected benefit
- **Constant Percent (CP):** `b_x = (B_r / S_r) × s_x` — constant % of salary

### Annuity Functions

**Straight life annuity** (present value of $1/year for life starting at age x):
```
ä_x = Σ(t=0 to ∞) t_p_x^(m) × v^t
```

**Curtate life expectancy (interest rate = 0):**
```
e_x = [Σ(t=0 to ∞) t_p_x^(m)] - 1
```

**Period certain life annuity** (n-year certain + life thereafter):
```
ä_{x:n̄|} = Σ(t=0 to n-1) v^t + n_p_x^(m) × v^n × ä_{x+n}
```

**Joint and survivor annuity** (100k% to survivor):
```
k_ä_{xz} = Σ(t=0 to ∞) v^t [t_p_x^(m) × t_p_z^(m) + k × t_p_x^(m)(1 - t_p_z^(m)) + k × t_p_z^(m)(1 - t_p_x^(m))]
```

**Temporary employment-based annuity** (from age x to retirement r):
```
ä^T_{x:r-x|} = Σ(t=0 to r-x-1) t_p_x^(T) × v^t
```
Note: Uses composite survival p^(T), not just mortality.

**Salary-based temporary annuity:**
```
s_ä^T_{x:r-x} = Σ(t=x to r-1) (s_t / s_x) × t-x_p_x^(T) × v^(t-x)
```

---

## Chapter 4: Population Theory

**Population types:**
- **Stationary:** constant size, constant age/service distribution (constant new entrants, constant decrements)
- **Mature:** constant percentage age/service distribution, size may grow (constant growth rate in new entrants)
- **Undermature:** younger/shorter-service than mature (growing industry)
- **Overmature:** older/longer-service than mature (declining industry)
- **Size-constrained:** fixed total size, new entrants = total decrements each year

**Hiring age distribution (Table 4-6):**

| Entry Age | Proportion | Salary Scale |
|-----------|-----------|-------------|
| 20 | 0.277 | 1.0000 |
| 25 | 0.290 | 1.1171 |
| 30 | 0.152 | 1.2437 |
| 35 | 0.101 | 1.3747 |
| 40 | 0.086 | 1.5042 |
| 45 | 0.049 | 1.6252 |
| 50 | 0.016 | 1.7301 |
| 55 | 0.015 | 1.8122 |
| 60 | 0.014 | 1.8655 |

Average hiring age: 28

---

## Chapter 5: Pension Liability Measures

### Plan Termination Liability (PTL)

For active participants (x ≤ r):
```
(PTL)_x = B_x × r-x_p_x^(m) × v^(r-x) × ä_r
```
Uses *mortality-only* survival (not composite), since only death prevents receipt of accrued benefit if plan terminates.

For retirees (x ≥ r):
```
(PTL)_x = B_r × ä_x
```

### Plan Continuation Liability (PCL)

Uses composite (all-decrement) survival:
```
ABr(PCL)_x = B_x × r-x_p_x^(T) × v^(r-x) × ä_r
```

### Present Value of Future Benefits (PVFB)

```
r(PVFB)_x = B_r × r-x_p_x^(T) × v^(r-x) × ä_r
```
Note: Uses projected benefit B_r (not accrued B_x).

### Actuarial Liability (General Form)

```
r(AL)_x = k × r(PVFB)_x
```

Where k depends on the actuarial cost method:

| Method | k (fraction of PVFB allocated) |
|--------|-------------------------------|
| Accrued Benefit (AB) | B_x / B_r |
| Benefit Prorate, Constant Dollar (BD) | (x-y) / (r-y) |
| Benefit Prorate, Constant Percent (BP) | S_x / S_r |
| Cost Prorate, Constant Dollar (CD) | ä^T_{y:x-y} / ä^T_{y:r-y} |
| Cost Prorate, Constant Percent (CP) | s_ä^T_{y:x-y} / s_ä^T_{y:r-y} |

**Inequality ordering:** AB ≤ BP ≤ BD ≤ CP ≤ CD ≤ PVFB

### Prospective Definition

```
r(AL)_x = r(PVFB)_x - r(PVFNC)_x
```
(Actuarial Liability = PVFB minus Present Value of Future Normal Costs)

### Retrospective Definition

```
r(AL)_x = r(AVPNC)_x
```
(Actuarial Liability = Accumulated Value of Past Normal Costs)

---

## Chapter 6: Normal Costs

### Generalized Normal Cost Function

```
r(NC)_x = b'_x × r-x_p_x^(T) × v^(r-x) × ä_r    (for y ≤ x < r)
```

Where `b'_x` = benefit accrual allocated by the cost method.

**Fundamental identity:** Present value of all future normal costs at entry = PVFB at entry:
```
r(PVFB)_y = Σ(t=y to r-1) r(NC)_t × t-y_p_y^(T) × v^(t-y)
```

### Normal Cost by Method

**Accrued Benefit:**
```
ABr(NC)_x = b_x × r-x_p_x^(T) × v^(r-x) × ä_r
```
(b_x = natural benefit accrual from the plan formula)

**Benefit Prorate, Constant Dollar:**
```
BDr(NC)_x = [B_r / (r-y)] × r-x_p_x^(T) × v^(r-x) × ä_r
         = r(PVFB)_x / (r-y)
```

**Benefit Prorate, Constant Percent:**
```
BPr(NC)_x = [B_r × s_x / S_r] × r-x_p_x^(T) × v^(r-x) × ä_r
          = s_x × r(PVFB)_x / S_r
```

**Cost Prorate, Constant Dollar (Entry Age Normal):**
```
CDr(NC)_y = r(PVFB)_y / ä^T_{y:r-y}
```
Same dollar amount at all ages.

**Cost Prorate, Constant Percent:**
```
CPr(NC)_x = K × s_x
where K = r(PVFB)_y / (s_y × s_ä^T_{y:r-y})
```
Constant percentage of salary at all ages.

### Normal Cost Summary

All individual normal costs can be expressed as:
```
r(NC)_x = k × r(PVFB)_x
```

### Key Relationship

```
r(AL)_x = r(PVFB)_x - r(NC)_x × ä^T_{x:r-x}    [for cost prorate methods]
```

---

## Chapter 7: Supplemental Costs (pp 101-112)

Supplemental costs arise from the unfunded actuarial liability (UAL).

**Unfunded Actuarial Liability:**
```
(UAL)_t = (AL)_t - (AV)_t
```
Where AV = actuarial value of assets.

**Sources of UAL:**
1. Initial unfunded liability (plan inception)
2. Plan amendments (benefit changes)
3. Actuarial gains/losses (experience ≠ assumptions)
4. Assumption changes

**Amortization methods:**

1. **Level dollar:** constant annual payment over n years:
```
(SC)_t = (UAL)_t / ä_{n|}    where ä_{n|} = (1 - v^n) / i
```

2. **Level percent of payroll:** payment grows with payroll:
```
(SC)_t = (UAL)_t / s_ä_{n|}    where s_ä_{n|} = Σ(t=0 to n-1) [(1+g)/(1+i)]^t
```
g = payroll growth rate

**Aggregate cost method** (no separate UAL amortization):
```
Aggregate NC = [PVFB - AV] / [Σ temporary annuities for all active members]
```
No explicit UAL — any shortfall is spread into future normal costs.

**Frozen initial liability (FIL):** Amortize only the initial UAL; experience gains/losses folded into aggregate NC going forward.

**Individual aggregate:** Like aggregate but computed per-person with individual PVFB.

---

## Chapter 8: Ancillary Benefits (pp 113-140)

Extends the basic retirement-only model to include benefits payable upon termination, disability, and death.

**General PVFB with all ancillary benefits:**
```
(PVFB)_x = Σ(k=x to r''-1) [k-x_p_x^(T) × v^(k-x)] × [q_k^(t)×^v F_k + q_k^(d)×^d F_k + q_k^(m)×^s F_k + q_k^(r)×^r F_k]
```
Where F_k = value of benefit payable at each decrement:
- `^v F_k` = vested termination benefit (deferred annuity or lump sum)
- `^d F_k` = disability benefit (immediate or deferred annuity on disabled-life mortality)
- `^s F_k` = survivor/death benefit (spouse annuity or lump sum)
- `^r F_k` = retirement benefit (life annuity, possibly graded for early retirement)

**Vested termination benefit:**
```
^v F_k = g_k^(v) × B_k × r-k_p_k^(m) × v^(r-k) × ä_r
```
Where g_k^(v) = vesting grading function (0 if not vested, 1 if fully vested, partial if graded).

**Disability benefit:**
```
^d F_k = g_k^(d) × B_k × ä_k^(disabled)
```
Where ä_k^(disabled) uses disabled-life mortality table (Table 2-5).

**Survivor (death) benefit:**
```
^s F_k = g_k^(s) × B_k × Pr(married) × ä_z
```
Where z = spouse's age, using standard mortality.

**Normal cost with ancillary benefits (general form):**
```
(NC)_x = benefit_accrual × Σ(k=x to r'') [k-x_p_x^(T) × v^(k-x) × (q_k^(t)×^v F'_k + q_k^(d)×^d F'_k + q_k^(m)×^s F'_k + q_k^(r)×^r F'_k)]
```

**Key insight:** Ancillary benefits add ~15-25% to total costs depending on plan design. The retirement benefit is always the dominant component (~75-85% of total).

---

## Chapter 9: Multiple Retirement Ages (pp 141-153)

### Actuarial Equivalence

The grading function converts benefits at different retirement ages to equivalent values:
```
*g_k^(r) × B_k × ä_k = B_k × r-k_p_k^(m) × v^(r-k) × ä_r
```

Solving:
```
*g_k^(r) = [r-k_p_k^(m) × v^(r-k) × ä_r] / ä_k
```

**Approximation:** `*g_k^(r) ≈ 0.9^(r-k)` for k < r (roughly 10% reduction per year before normal retirement).

**Table 9-1 values (8% interest, GAM-71):**

| Age | g_k^(r) | 1/g_k^(r) |
|-----|---------|-----------|
| 55 | 0.33 | 3.02 |
| 60 | 0.56 | 1.79 |
| 62 | 0.70 | 1.43 |
| 65 | 1.00 | 1.00 |
| 70 | 1.94 | 0.52 |

### PVFB with Multiple Retirement Ages

```
r'(PVFB)_x = Σ(k=r' to r'') g_k^(r) × B_k × k-x_p_x^(T) × q_k^(r) × v^(k-x) × ä_k
```
Where r' = earliest retirement age, r'' = latest retirement age.

**Approximation using expected early retirement benefit E(B):**
```
*(PVFB)_x ≈ [E(B)/B_r] × r(PVFB)_x
```

### Cost Methods with Multiple Retirement Ages

All five cost methods generalize by summing over retirement ages r' to r''. The key formulas for each method under multiple retirement ages involve replacing single-age PVFB with the summation form above.

**Early Retirement Cost Ratio (ERCR):** Measures relative cost of early vs normal retirement. Under cost prorate methods with actuarially reduced benefits, ERCR < 1 (early retirement costs less). Under accrued benefit method with full benefits, ERCR >> 1 at young ages.

---

## Chapter 10: Statutory Funding Requirements (pp 154-168)

### ERISA Minimum Required Contribution

**Funding Standard Account (FSA):**
```
Charges: prior year deficiency + NC + amortization charges + interest
Credits: prior year credit balance + contributions + amortization credits + interest
```

If charges > credits → funding deficiency (minimum required contribution).

**Amortization bases (5-year for experience, closed):**
- Initial unfunded liability
- Plan amendments
- Actuarial gains/losses
- Assumption changes

**FSA equilibrium equation:**
```
(AL)_t - (AV)_t = (ULB)_t - (FSA)_t
```
Where ULB = unamortized liability balance.

### Maximum Tax Deductible Contribution

```
Maximum = lesser of:
  (1) Max(NC + 10-year supplemental cost, minimum required contribution)
  (2) Full funding limit (AL or current liability, whichever applies)
OR if larger:
  (3) Unfunded current liability
```

### Asset Valuation Methods

**Weighted average:** `(AV)_t = k(MV)_t + (1-k)(BV)_t`

**N-year moving average (most common, n=5):**
```
(AV)_t = (MV)_t - [(n-1)/n](CG)_{t-1} - [(n-2)/n](CG)_{t-2} - ... - [1/n](CG)_{t-n+1}
```
Each year's capital gain recognized at 1/n per year (20% per year for n=5).

**Write-up method:**
```
(AV)_t = [(AV)_{t-1} + C_{t-1} - B_{t-1}](1+i)
```

**Corridor method:** Adjusts write-up if outside 85-110% of market value.

**ERISA constraint:** Actuarial value must be within 80-120% of market value.

---

## Chapter 11: Pension Accounting / SFAS 87 (pp 169-193)

### Liability Measures

**Accumulated Benefit Obligation (ABO):**
```
(ABO)_x = B_x × Σ(k=x to r'') [k-x_p_x^(T) × v^(k-x) × (q_k^(t)×^v F_k + q_k^(d)×^d F_k + q_k^(m)×^s F_k + q_k^(r)×^r F_k)]
```
Uses current accrued benefit B_x (no salary projection). Mathematically identical to plan continuation liability under accrued benefit method.

**Vested Benefit Obligation (VBO):** = vested portion of ABO. Typically ≈ ABO for mature plans.

**Projected Benefit Obligation (PBO):**
```
(PBO)_x = Σ(k=x to r'') [^CD B_k × k-x_p_x^(T) × v^(k-x) × (q_k^(t)×^v F_k + q_k^(d)×^d F_k + q_k^(m)×^s F_k + q_k^(r)×^r F_k)]
```
Where `^CD B_k = B_k × (x-y)/(k-y)` = projected benefit prorated by service. Identical to AL under constant dollar benefit prorate method.

**PBO roll-forward approximation:**
```
(PBO)_{t+1} ≈ [(PBO)_t + (SC)_t](1+i) - E(B)_t(1 + ½i)
```

### Net Periodic Pension Cost (SFAS 87)

| Component | Formula |
|-----------|---------|
| + Service Cost (SC) | Normal cost under constant dollar benefit prorate × (1+i) |
| + Interest Cost (IC) | `i × [(PBO)_t - ½E(B)_t]` |
| - Expected Return on Assets (EROA) | `i' × [(MRA)_t - ½E(B)_t + ½E(C)_t]` |
| + Amortization costs | Transition obligation + prior service cost + net loss (gain) |

**Net interest cost** (when i = i'):
```
Net Interest = i × [(PBO)_t - (MRA)_t - ½E(C)_t]
```
= interest on unfunded obligation

**Gain/loss corridor:** Only amortize cumulative unrecognized loss (gain) exceeding 10% of max(PBO, MRA). Amortized over average future service of active participants (typically 8-15 years).

**Future service of employees expected to receive benefits:**
```
(FS)_x = Σ(k=x to r-1) k-x_p_x^(T)
```

**Average future service:**
```
(AFS)_t = (FS)_t / (ERB)_t
```
Where ERB = expected to receive benefits.

---

## Chapter 12: Alternative Actuarial Assumptions (pp 194-200+)

Sensitivity analysis of assumption changes on NC and AL (values as % of baseline = 100):

### Mortality Sensitivity
| Multiple | NC (AB/BD/CP) | AL (AB/BD/CP) |
|----------|--------------|--------------|
| 0.50 | 120/121/122 | 121/121/121 |
| 0.75 | 109/109/110 | 109/109/109 |
| 1.00 | 100/100/100 | 100/100/100 |
| 1.25 | 87/86/85 | 86/86/86 |
| 1.50 | 77/75/74 | 77/76/76 |

**Key finding:** Mortality has modest impact. ±25% change → ±10-15% cost change.

### Termination Rate Sensitivity
| Multiple | NC (AB/BD/CP) | AL (AB/BD/CP) |
|----------|--------------|--------------|
| 0.50 | 102/115/127 | 100/104/100 |
| 1.00 | 100/100/100 | 100/100/100 |
| 1.50 | 97/84/60 | 99/95/97 |

**Key finding:** Termination rates barely affect AL but significantly affect NC under cost prorate methods (up to 40% change for ±50% rate change).

### Disability Rate Sensitivity
Virtually no impact on costs (< 2% for ±50% change). Disability cost changes are offset by retirement cost changes.

### Retirement Age Sensitivity
| Avg Ret Age | NC (AB/BD/CP) | AL (AB/BD/CP) |
|-------------|--------------|--------------|
| 57.5 | 90/79/75 | 99/90/85 |
| 61.4 | 100/100/100 | 100/100/100 |
| 65.0 | 107/117/121 | 101/109/114 |

**Key finding:** Retirement age has the largest impact on costs among demographic assumptions. Earlier retirement reduces costs under accrued benefit method but increases them under cost prorate methods.

### Interest Rate Sensitivity (most important assumption)
A 1% change in interest rate changes costs by approximately 15-25% depending on method.

### Salary Increase Sensitivity
Second most important assumption. A 1% change affects NC by ~10-15%.

---

## Key Tables in the PDF (for data extraction if needed)

| Table | Content | PDF Page |
|-------|---------|----------|
| 2-1 | 1971 GAM Mortality Rates (ages 20-110) | 30 |
| 2-3 | Select & Ultimate Termination Rates | 33 |
| 2-5 | Disabled-Life Mortality Rates | 36 |
| 2-7 | Disability Rates | 37 |
| 2-9 | Early Retirement Rates | 39 |
| 2-10 | Merit Salary Scale | 41 |
| 3-2 | Service Table (age 20 entrant, 1M radix) | 49 |
| 3-4 | Salary Function per dollar of entry salary | 53 |
| 3-6 | Annuity Values | 64 |
| 3-7 | Temporary Employment-Based Annuity | 67 |
| 3-8 | Salary-Based Temporary Annuity | 68 |
| 4-6 | Hiring Age Distribution and Salary Scale | 77 |
| 5-2 | Actuarial Liabilities by Method | 89 |
| 9-1 | Actuarial Equivalent Grading Function | 143 |
| 9-2 | Relative Cost of Early Retirement (full benefits) | 150 |
| 9-3 | Relative Cost of Early Retirement (reduced benefits) | 151 |
| 10-5a | Funding Standard Account worksheet | 155 |
| 10-6 | Valuation and Experience Assumptions | 162 |
| 10-7 | ERISA Min/Max Contribution Projection | 163 |
| 10-8 | Contributions Under Alternative Funding Methods | 164 |
| 10-9 | Asset Valuation Method Comparison | 168 |
| 11-1 | Net Periodic Pension Cost Components | 176 |
| 11-3 | SFAS 87 Pension Cost Projection | 184 |
| 11-5 | Financial Statement Disclosure Projection | 189 |
| 12-1 | Effect of Alternative Mortality Rates | 195 |
| 12-2 | Effect of Alternative Termination Rates | 197 |
| 12-3 | Effect of Alternative Disability Rates | 199 |
| 12-4 | Effect of Alternative Retirement Rates | 200 |

---

## Note on Chapters 13-16

These chapters were not included in the converted PDF (it ends around page 200). They cover:
- **Ch 13:** Alternative Plan Benefits (flat dollar, career avg, offset plans, floor-offset)
- **Ch 14:** Funding Policy (contribution timing, investment of contributions)
- **Ch 15:** Investment Policy / Asset Allocation (asset-liability matching, immunization)
- **Ch 16:** Retiree Health Benefits (FAS 106, prefunding vs pay-as-you-go)

| Table | Content | PDF Page |
|-------|---------|----------|
| 2-1 | 1971 GAM Mortality Rates (ages 20-110) | 30 |
| 2-3 | Select & Ultimate Termination Rates | 33 |
| 2-5 | Disabled-Life Mortality Rates | 36 |
| 2-7 | Disability Rates | 37 |
| 2-9 | Early Retirement Rates | 39 |
| 2-10 | Merit Salary Scale | 41 |
| 3-2 | Service Table (age 20 entrant, 1M radix) | 49 |
| 3-4 | Salary Function per dollar of entry salary | 53 |
| 3-6 | Annuity Values | 64 |
| 3-7 | Temporary Employment-Based Annuity | 67 |
| 3-8 | Salary-Based Temporary Annuity | 68 |
| 4-6 | Hiring Age Distribution and Salary Scale | 77 |
| 5-2 | Actuarial Liabilities by Method | 89 |
