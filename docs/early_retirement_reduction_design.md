# Early Retirement Reduction Factors: Design and Rationale

## What Are Early Retirement Reductions?

When a pension plan member retires before reaching **normal retirement eligibility**, their annual pension benefit is permanently reduced. This is called an **early retirement reduction** (or early retirement penalty).

The rationale is straightforward: a member who retires early will collect benefits for more years than someone who retires at the normal age. The reduction offsets (partially or fully) the additional cost to the plan.

**Example**: A TRS member's full pension would be 2.3% × FAS × YOS. If they retire 5 years early and the reduction factor at their age is 64%, they receive 64% of that full amount — permanently.

### Actuarially Fair vs. Subsidized Reductions

An **actuarially fair** (or "actuarially equivalent") reduction would make the plan indifferent to when the member retires — the present value of benefits would be the same whether they retire early or on time. This typically works out to roughly 6-8% per year of early retirement.

Most public pension plans use reductions that are **less severe** than actuarially fair — sometimes much less. For example:
- FRS tier 2 uses 5% per year (slightly below actuarially fair)
- TRS's "others" table gives 64% at age 60 for a 5-year-early retirement, which is a ~7.2% per year reduction (closer to fair)
- TRS grandfathered members with 25+ years of service get 98-100% even at age 55 (heavily subsidized)

This subsidy means early retirement is valuable to members and costly to the plan, which is why the reduction structure significantly affects projected liabilities.

## How Different Plans Structure Reductions

### Pattern 1: Formula-Based (FRS)

A simple linear formula: reduce by X% per year before the Normal Retirement Age (NRA).

```
reduce_factor = max(0, 1 - rate_per_year × (NRA - age))
```

**FRS example** (Tier 2, regular class):
- `rate_per_year = 0.05` (5% per year)
- `NRA = 65`
- Member retiring at age 60: `1 - 0.05 × 5 = 0.75` (75% of full benefit)

This is stored entirely in `plan_config.json`:
```json
"early_retire_reduction": {
  "rate_per_year": 0.05,
  "nra": {"special": 60, "default": 65}
}
```

No data file needed — it's a parameter, not a table.

### Pattern 2: Age-Based Table (TRS Intermediate/Current)

A lookup table mapping retirement age to reduction factor.

From the TRS AV (page 47):

| Age | 55  | 56  | 57  | 58  | 59  | 60  | 61  | 62  | 63  | 64  | 65  |
|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|
|     | 43% | 46% | 50% | 55% | 59% | 64% | 70% | 76% | 84% | 91% | 100% |

This applies to members who meet the Rule of 80 but not the minimum age for unreduced retirement (age 60 for intermediate, age 62 for current tier).

Stored as a stage 3 data file because it's a data table, not a simple formula.

### Pattern 3: YOS × Age Matrix (TRS Grandfathered)

A two-dimensional lookup: the reduction depends on both years of service AND age at retirement.

From the TRS AV (page 47):

| YOS  | Age 55 | Age 56 | Age 57 | Age 58 | Age 59 | Age 60 |
|------|--------|--------|--------|--------|--------|--------|
| 20   | 90%    | 92%    | 94%    | 96%    | 98%    | 100%   |
| 21   | 92%    | 94%    | 96%    | 98%    | 100%   | 100%   |
| 22   | 94%    | 96%    | 98%    | 100%   | 100%   | 100%   |
| 23   | 96%    | 98%    | 100%   | 100%   | 100%   | 100%   |
| 24   | 98%    | 100%   | 100%   | 100%   | 100%   | 100%   |
| 25+  | 100%   | 100%   | 100%   | 100%   | 100%   | 100%   |

This reflects the plan's generous treatment of long-serving grandfathered members — with 25+ years of service, there's essentially no reduction even at age 55.

This must be a data file since it's a 2D table that can't be reduced to a simple formula.

## Stage 3 Data Design

### What's in config (formula-based reductions)

Formula-based reductions stay in `plan_config.json` under each tier's `early_retire_reduction` section:

```json
"early_retire_reduction": {
  "rate_per_year": 0.05,
  "nra": {"special": 60, "default": 65}
}
```

Or for TRS's rule-based dispatch:
```json
"early_retire_reduction": {
  "rules": [
    {"condition": {"min_yos": 30}, "formula": "linear", "rate_per_year": 0.02, "nra": 50},
    {"condition": {"grandfathered": true}, "formula": "table", "table_key": "reduced_gft"},
    {"condition": {}, "formula": "table", "table_key": "reduced_others"}
  ]
}
```

The `table_key` references a stage 3 data file.

### What's in stage 3 data (table-based reductions)

Plans with table-based reductions provide CSV files in `data/{plan}/decrements/`:

**Age-based table** (`reduction_others.csv`):
```csv
age,tier,reduce_factor
55,others,0.43
56,others,0.46
57,others,0.50
...
65,others,1.00
```

**YOS × Age matrix** (`reduction_gft.csv`):
```csv
age,yos,tier,reduce_factor
55,20,grandfathered,0.90
56,20,grandfathered,0.92
...
55,25,grandfathered,1.00
```

### How the model uses them

In `build_benefit_table()`, for each member at each potential retirement age:

1. Determine the member's tier (from entry year)
2. Check if the member meets normal retirement eligibility → `reduce_factor = 1.0`
3. If early retirement eligible, look up the reduction:
   - If formula-based: compute from parameters
   - If table-based: look up from the loaded CSV by matching (age, yos, tier)
4. Multiply the full benefit by `reduce_factor`

The config's `rules` array is evaluated in order (first matching rule wins), which allows complex tier-specific logic without code branching.

## Policy Alternatives

Early retirement reductions are a common policy lever. A legislature might consider:
- Increasing the reduction rate (e.g., 5% → 7% per year) to discourage early retirement
- Raising the minimum age for early retirement (e.g., 55 → 58)
- Eliminating the grandfathered reduction table (applying the stricter "others" table to everyone)
- Making reductions actuarially fair (much steeper than current subsidized rates)

Because formula-based reductions are in config and table-based reductions are in stage 3 CSV files, policy alternatives can modify either:
- Config diff: `{"tiers[0].early_retire_reduction.rate_per_year": 0.07}` 
- Data diff: swap `reduction_others.csv` with a steeper table

This supports the pipeline's policy alternatives phase without changing model code.

## Relationship to Retirement Rates

Early retirement reductions interact with but are distinct from **retirement rates** (the probability a member chooses to retire at a given age):

- **Retirement rates** (in `retirement_rates.csv`): the actuary's assumption about *how many* members will retire at each age
- **Reduction factors** (in `reduction_*.csv` or config): *what benefit* those early retirees receive

A steeper reduction would presumably cause fewer members to retire early (lower early retirement rates), but the rates and factors are set independently by the actuary based on experience studies. In our model, they're separate inputs — we don't endogenize the relationship between them.

## Summary

| Reduction Type | Where Stored | Example |
|---------------|-------------|---------|
| Formula (linear per year) | `plan_config.json` | FRS: 5% per year before NRA |
| Age table | `data/{plan}/decrements/reduction_*.csv` | TRS others: age → factor |
| YOS × Age matrix | `data/{plan}/decrements/reduction_*.csv` | TRS grandfathered: (yos, age) → factor |

Plans may combine multiple types via the `rules` dispatch in config — e.g., TRS uses formula for some conditions, table for others, depending on tier and service level.
