# Termination Rate Assumptions: Design and Rationale

## What Are Termination Rates?

In pension actuarial modeling, **termination** (also called **withdrawal**) refers to an active member voluntarily leaving employment before retirement. This is distinct from:

- **Mortality**: death while active or retired
- **Retirement**: beginning to draw a pension benefit
- **Disability**: leaving due to disability

When a member terminates, they either:
- Take a **refund** of their accumulated contributions (forfeiting the employer-funded benefit), or
- Become a **vested termination** — retaining a right to a deferred pension at retirement age

Termination rates are a critical actuarial assumption because they determine how many members survive in the plan long enough to earn expensive retirement benefits. Higher termination rates mean fewer members reach retirement, reducing projected liabilities.

## How Plans Structure Termination Assumptions

Plans differ in how they index termination rates. The structure reflects what the plan's actuary found to be the best predictor of quitting behavior in the plan's experience study.

### Pattern 1: Years of Service Only (Simple)

The most common structure. Termination probability depends only on how long the member has worked.

```
YOS    Rate
1      0.150
2      0.120
3      0.095
...
10+    0.030  (ultimate rate)
```

**Behavioral logic**: New employees are much more likely to leave than experienced ones. After some tenure threshold, turnover stabilizes at a low "ultimate" rate.

**Example**: Florida FRS uses this pattern with an additional age-group dimension (rates vary by both YOS and broad age band).

### Pattern 2: Select and Ultimate (Age-Based Ultimate)

A refinement where early-career rates are YOS-based ("select" period) and later rates transition to age-based ("ultimate" period).

```
Select (YOS 1-5):  rate = f(YOS)
Ultimate (YOS 6+): rate = f(age)
```

**Behavioral logic**: Early turnover is driven by job fit (YOS-dependent). Later turnover is driven by life-stage factors like career mobility, which correlate with age.

### Pattern 3: Select + Years from Normal Retirement

The most behaviorally grounded structure. Early-career rates are YOS-based, but after the select period, rates are indexed by **how many years the member is from normal retirement eligibility**.

```
Select (YOS 1-10): rate = f(YOS)
Post-select:        rate = f(years_from_normal_retirement)
```

**Behavioral logic**: Once a member has significant tenure (10+ years in TRS's case), the dominant factor in their decision to leave is proximity to their pension. A member 20 years from retirement eligibility has a much weaker incentive to stay than one who is 2 years away. The pension's "pull" increases nonlinearly as eligibility approaches.

This is actuarially sound because pension wealth accrual is heavily back-loaded — the value of staying one more year grows dramatically as you approach eligibility for unreduced benefits.

**Example**: Texas TRS uses this pattern:
- YOS 1-10: termination rate by YOS (single Male/Female averaged rate)
- YOS 10+: termination rate by years from normal retirement (1-32 years)

## Why "Years from NR" Depends on Tier

A complication: **normal retirement eligibility rules differ by tier**. In TRS:

| Tier | Entry Date | Normal Retirement |
|------|-----------|-------------------|
| Grandfathered | On or before Aug 31, 2005 | Rule of 80 (age + service >= 80) |
| Intermediate | After 2005, vested by Aug 31, 2014 | Rule of 80 with minimum age 60 |
| Current | After Aug 31, 2014 | Rule of 80 with minimum age 62 |

This means two members with identical age and YOS but different entry dates may have different "years from NR" values, and therefore different termination rates. For example:

- **Member A** (grandfathered, age 50, YOS 15): Rule of 80 reached at age 57.5 (when age + YOS = 80). Years from NR = 8.
- **Member B** (current tier, age 50, YOS 15): Rule of 80 at age 57.5, but minimum age is 62. Years from NR = 12.

The model must resolve this at runtime using tier eligibility rules from the plan configuration.

## How This Affects Data Format Design

### The Problem

A naive stage 3 format of `(age, yos, term_rate)` cannot represent TRS's assumption because the same `(age, yos)` cell maps to different rates depending on entry year (which determines tier).

### Our Solution

We store the **raw actuarial assumptions as published**, using a single `termination_rates.csv` with a `lookup_type` column:

```csv
lookup_type,lookup_value,term_rate
yos,1,0.143011
yos,2,0.121016
yos,3,0.101138
...
yos,10,0.041029
years_from_nr,1,0.016910
years_from_nr,2,0.018788
...
years_from_nr,32,0.028627
```

**For FRS** (simple YOS + age-group structure), the file contains only `yos`-type rows (with an additional `age` column for the age-group lookup):

```csv
lookup_type,age,yos,term_rate
yos,20,0,0.275
yos,20,1,0.185
yos,25,0,0.265
...
```

**For future plans**, additional `lookup_type` values could support other structures (e.g., `age` for age-based ultimate rates, `age_yos` for age-service matrices).

### Why Not Pre-Expand?

An alternative is to pre-compute rates for every `(entry_year, age, yos)` cell (~100K+ rows). We rejected this because:

1. **It destroys the actuarial structure.** The AV assumes rates by years-from-NR, not by entry cohort. Storing the pre-expanded version obscures what was actually assumed.
2. **Scenario analysis becomes harder.** If you want to test "what if termination rates were 10% higher after year 10?", you'd need to re-expand the entire grid. With the raw assumption, you just scale the rates.
3. **It's unnecessarily large.** ~40 rows vs ~100K+ rows for the same information.
4. **The computation is cheap.** Resolving years-from-NR from tier config takes milliseconds.

### Why Not Force All Plans into (age, yos)?

FRS and similar plans could be represented as `(age, yos, rate)`. But TRS structurally cannot — the same `(age, yos)` maps to different rates for different cohorts. Forcing a common format would require either:
- Pre-expanding (loses structure, see above), or
- Storing the wrong assumption (approximating years-from-NR with a fixed age/yos mapping)

Neither is acceptable. The `lookup_type` approach preserves fidelity while maintaining a single file format.

## How the Model Uses These Rates

The separation rate builder in the model:

1. Reads `termination_rates.csv`
2. For `yos`-type rows: directly maps to the `(entry_year, entry_age, term_age, yos)` grid
3. For `years_from_nr`-type rows: computes `years_from_nr` for each grid cell using tier eligibility rules from `plan_config.json`, then joins
4. Combines termination and retirement rates into a composite separation rate table
5. Computes cumulative survival probabilities (`remaining_prob`, `separation_prob`)

This keeps plan-specific logic in the **configuration** (tier rules) rather than in the **data** (pre-expanded rates) or the **code** (if/else by plan name).

## Prevalence in Practice

The select-and-ultimate structure for termination rates is standard actuarial practice. The specific use of "years from normal retirement" as the post-select index is common among larger, well-studied public pension plans. GRS (the actuary for TRS) developed these rates from TRS's 2021 experience study, which analyzed actual member behavior against multiple predictive variables.

Key references:

- The [American Academy of Actuaries' Fundamentals of Pension Funding](https://www.actuary.org/sites/default/files/pdf/pension/fundamentals_0704.pdf) describes how demographic assumptions including termination rates are structured based on plan experience.
- The [Texas Pension Review Board's guide to actuarial methods](https://www.prb.texas.gov/wp-content/uploads/2019/11/finalbasicsofactmethod.pdf) notes that termination assumptions should be subdivided based on retirement eligibility status.
- The [GFOA best practices for actuarial valuations](https://www.gfoa.org/materials/enhancing-reliability-of-actuarial-valuations-for-pension) emphasizes that assumptions should be based on plan-specific experience studies.
- Winklevoss's [Pension Mathematics](https://pensionresearchcouncil.wharton.upenn.edu/wp-content/uploads/2015/09/0-8122-3196-1-9.pdf) provides the theoretical foundation for decrement modeling.
- [Milliman's guide to experience studies](https://www.milliman.com/en/insight/understanding-need-for-experience-studies-with-pension-plans) explains how actuaries determine the best indexing structure for termination rates.

## Summary

| Plan | Select Period | Post-Select Index | Rationale |
|------|-------------|-------------------|-----------|
| FRS | YOS 0-70 (with age groups) | N/A (single structure) | Simple, adequate for FRS experience |
| TRS | YOS 1-10 | Years from normal retirement | Behavioral: pension proximity drives retention |
| Future plans | Varies | Could be age, YOS, or years-from-NR | Format supports all via `lookup_type` |
