# FRS Benefit Payment Mapping Notes

## Purpose

This note records the current understanding of where FRS benefit-payment inputs
come from and why the current runtime `ben_payment` fields are still only
partially resolved.

## Current Runtime Context

Current class-level benefit-payment values live in:

- [plans/frs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/config/plan_config.json)

The config note already says the values are derived rather than directly
published.

## Four Relevant Source Families

### 1. Financial-statement deductions table

Source:

- [2022-23_ACFR.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2022-23_ACFR.pdf)
  - pension-plan financial deductions table, printed p. 162 in the PDF text flow

Published 2022 totals used by the current config note:

- benefit payments = `11,944,986,866`
- transfers to investment plan = `768,106,850`
- refunds of member contributions = `28,343,757`
- administrative expenses = `22,494,571`
- total deductions = `12,763,932,044`

These are the exact plan-wide totals cited in the current config note for the
`ben_payment_ratio`.

The Reason workbook stores these same anchors directly in the `Funding Input`
sheet:

- `BL10 = 11,944,986,866` (`ben_payment_legacy`)
- `BO10 = 28,343,757` (`refund_legacy`)
- `BQ10 = 768,106,850` (`disbursement_to_IP`)
- `BR10 = 22,494,571` (`admin_exp_legacy`)

That matters because it confirms the reviewed baseline is not just loosely
consistent with the ACFR deductions table. The workbook literally seeds the
same totals into the legacy intermediate model.

### 2. Valuation AVA-development disbursement table

Source:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
  - Table 2-4 `Development of Actuarial Value of Assets by Membership Class`,
    printed p. `18`, PDF p. `23`

This table is part of the AVA roll-forward from `July 1, 2021` to `July 1,
2022`. Line `3` reports:

- `Benefit Payments and other Disbursements`

in `($ in Thousands)` by class.

Those class values match the legacy class outflow inputs almost exactly:

- regular = `8,967,096,000`
- special = `2,423,470,000`
- admin = `8,090,000`
- judges = `105,844,000`
- eco = `9,442,000`
- eso = `53,526,000`
- senior management = `338,864,000`
- drop = `857,600,000`

The important footnote says:

- class-level contribution and disbursement information does not sum exactly to
  the system-level financial-statement totals
- lines `2` and `3` are allocated to the membership classes in proportion to
  class-level information provided and then “trued-up” to the system-level
  totals
- the lines also reflect members moving between classes since the prior
  valuation date

This makes Table 2-4 line 3 the strongest current provenance match for the
legacy class outflow inputs. But it also means those inputs are not pure class
benefit payments. They are allocated class disbursements used for AVA
development over the `2021/2022` plan year.

### 3. ACFR statistical annuitant / annual-benefit tables

Sources:

- ACFR statistical section `Annuitants and Benefit Payments for the FRS Pension Plan`,
  printed p. 188
- ACFR statistical section `Total Annual Benefits by System/Class`, printed p. 204

These provide:

- annualized annuitant and disabled-retiree benefit amounts
- class-level annual benefit amounts by system/class

Example 2022 class totals from `Total Annual Benefits by System/Class`:

- Regular = `8,431,219,359`
- Senior Management Service = `327,659,694`
- Special Risk = `2,139,187,633`
- Special Risk Administrative Support = `7,284,354`
- Elected Officers' = `164,431,365`

### 4. Valuation annuitant-benefit table

Source:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
  - Table C-5 `Annuitants and Potential Annuitants at July 1, 2022`, printed
    p. C-4

This table reports class-level annuitant counts and annual benefits, including
separate EOC subclasses and a separate DROP line.

Published annual benefits for current annuitants plus future DROP annuities
(in whole dollars after scaling from thousands) are:

- regular = `9,188,016,000`
- senior management = `351,933,000`
- special = `2,187,975,000`
- admin = `7,260,000`
- judges = `106,608,000`
- eco = `11,367,000`
- eso = `57,922,000`

## What Is Resolved

- the plan-wide ratio note in current config is tied to the financial-statement
  deductions table, not to the statistical annuitant table
- the current runtime class `ben_payment` values are exactly:
  - `class_outflow * ben_payment_ratio`
- the retained Reason workbook applies those class outflow constants directly in
  `Funding Input!BL2:BR9` against the row-10 plan-wide cash-flow anchors in
  `Funding Input!BL10:BR10`
- the baseline class outflow inputs are now much better explained:
  - they match valuation Table 2-4 line `3` `Benefit Payments and other
    Disbursements` exactly for all currently tracked classes except the
    previously noted `200,000` senior-management discrepancy
- the `ben_payment_ratio` is exactly the ACFR financial-deductions fraction:
  - `11,944,986,866 / 12,763,932,044 = 0.9358391148451025`
- the class outflow figures used by the current reviewed baseline are:
  - regular = `8,967,096,000`
  - special = `2,423,470,000`
  - admin = `8,090,000`
  - judges = `105,844,000`
  - eso = `53,526,000`
  - eco = `9,442,000`
  - senior management = `338,664,000`
- those outflow values are preserved in:
  - [plans/frs/baselines/input_params.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/input_params.json)
- and they are exported from upstream R variables by:
  - [scripts/extract/extract_baseline.R](/home/donboyd5/Documents/python_projects/pension_model/scripts/extract/extract_baseline.R)
- the statistical class table is useful because it exposes class splits that the
  deductions table does not
- the valuation Table C-5 is also useful because it provides class-level
  annuitant annual benefits plus explicit EOC subclass splits
- taken together, the current first-year path now looks like:
  - valuation Table 2-4 line `3` class allocated disbursements for `2021/2022`
  - multiplied by the ACFR plan-wide benefit share
  - to estimate class-level first-year benefit payments

This is a major improvement in provenance. But it does not settle the
conceptual question of whether allocated class disbursements were the right
source for first-year benefit payments.

Example exact reproductions:

- regular:
  - `8,967,096,000 * 0.9358391148451025 = 8,391,759,183.371059`
- judges:
  - `105,844,000 * 0.9358391148451025 = 99,052,955.271665`
- eco:
  - `9,442,000 * 0.9358391148451025 = 8,836,192.922367`

## Reconciliation Evidence

The baseline class outflows are now well explained as a provenance match to
valuation Table 2-4 line `3`. The remaining question is conceptual, not merely
provenance:

- were those allocated class disbursements the right target for first-year
  model benefit payments?
- or were they only the best available proxy?

That is why the comparisons below still matter. They compare the legacy class
outflow inputs to narrower published benefit concepts.

### Comparison to ACFR statistical annual benefits

Compared with ACFR `Total Annual Benefits by System/Class` for 2022:

- regular outflow is higher by `535,876,641` (`+6.36%`)
- senior management outflow is higher by `11,004,306` (`+3.36%`)
- special outflow is higher by `284,282,367` (`+13.29%`)
- admin outflow is higher by `805,646` (`+11.06%`)
- EOC grouped runtime outflow (`judges + eso + eco = 168,812,000`) is higher
  than the ACFR Elected Officers' total by `4,380,635` (`+2.66%`)

### Comparison to valuation Table C-5 annual benefits

Compared with valuation Table C-5 totals for current annuitants plus future DROP
annuities:

- regular outflow is lower by `220,920,000` (`-2.40%`)
- senior management outflow is lower by `13,269,000` (`-3.77%`)
- special outflow is higher by `235,495,000` (`+10.76%`)
- admin outflow is higher by `830,000` (`+11.43%`)
- judges outflow is lower by `764,000` (`-0.72%`)
- eco outflow is lower by `1,925,000` (`-16.93%`)
- eso outflow is lower by `11,458,000` (`-17.63%`)

This pattern is now easier to interpret:

- the legacy class outflows are not trying to match this statistical benefit
  table exactly
- they are closer to the broader valuation Table 2-4 disbursement concept than
  to statistical annual benefits

### Comparison to a mixed published-payout composite

A more refined test combines:

- valuation Table C-5 current annuitant annual benefits
- ACFR disability benefits by class
- ACFR terminated DROP current benefits by class

This is not a full explanation, but it is more informative than any one-table
comparison.

Results:

- Regular becomes very close:
  - composite = `8,936,653,394`
  - baseline outflow = `8,967,096,000`
  - difference = `+30,442,606` (`+0.34%`)
- Senior Management also becomes close:
  - composite = `335,421,494`
  - baseline outflow = `338,664,000`
  - difference = `+3,242,506` (`+0.97%`)
- Grouped EOC is already close to valuation current-annuitant benefits alone:
  - valuation current annuitants = `169,201,000`
  - baseline grouped outflow = `168,812,000`
  - difference = `-389,000` (`-0.23%`)
- Special and Admin remain materially underexplained even after the composite:
  - Special difference = `+203,805,512`
  - Admin difference = `+787,401`

Implication:

- if the modeling target is “first-year class benefit payments,” the mixed
  published payout composite may be conceptually closer than Table 2-4 line `3`
- but the current reviewed runtime does not use that narrower composite
- instead, it appears to use Table 2-4 line `3` as the class disbursement base
  and then applies the plan-wide benefit share

One additional clue now stands out:

- the still-unexplained `special` and `admin` gaps are very similar when scaled
  by class size
- using 2022 annuitant counts:
  - special unexplained gap per annuitant is about `$4,683`
  - admin unexplained gap per annuitant is about `$4,772`
- using 2022 ACFR class annual benefits:
  - special unexplained gap is about `9.53%`
  - admin unexplained gap is about `10.81%`

That pattern suggests a common class-specific extra amount for the Special Risk
family rather than two unrelated mismatches.

The ACFR plan-provisions narrative makes that plausible:

- it explicitly says Special Risk in-line-of-duty disability retirement has a
  minimum Option 1 benefit of `65%` of average final compensation, versus `42%`
  for other classes
- it also describes richer line-of-duty death benefits for Special Risk members

This does not solve the allocation, because the ACFR does not publish those
special-risk-only benefit slices by class in a way that ties directly to the
baseline outflow constants. But it does provide a credible policy-level reason
why `special` and `admin` would share a common upward adjustment relative to a
simple current-annuitant-plus-DROP composite.

The workbook evidence sharpens that conclusion:

- the plan-wide row-10 values are source-direct and match the ACFR deductions
  table exactly
- the class outflow constants appear only as hard-coded literals in workbook
  `Funding Input!BL2:BR9`
- those constants do not appear elsewhere in the retained FRS workbook as
  helper inputs or derived references
- but valuation Table 2-4 now provides the missing source for those constants
  in substance
- the unresolved part is now narrower and more conceptual:
  - whether using Table 2-4 line `3` was the right first-year benefit-payment
    target
  - and whether a better class benefit-payment method should replace it in a
    future prep design

## Additional ACFR Clue Mining

The ACFR provides useful context on why the Special Risk family could need an
upward adjustment, but it still does not publish a clean class-specific table
that closes the remaining outflow gap.

Useful but still incomplete source material:

- `TOTAL DISABILITY BENEFITS BY SYSTEM/CLASS`
  - printed p. `205`, PDF p. `207`
  - this is the source already used for the disability slice in the mixed
    composite
- `TOTAL FRS ANNUAL BENEFITS BY TYPE OF RETIREMENT`
  - printed p. `210`, PDF p. `212`
  - this publishes plan-wide totals for:
    - line-of-duty death
    - not line-of-duty death
    - line-of-duty disability
    - not line-of-duty disability
    - early
    - normal
- ACFR Note 1 plan provisions
  - printed pp. `38` to `40`
  - these describe the richer Special Risk benefit provisions, including:
    - minimum line-of-duty disability Option 1 benefit of `65%` of average
      final compensation for Special Risk members versus `42%` for other
      classes
    - line-of-duty death benefit of `100%` of salary for Special Risk members
      versus `50%` for other classes

What is still missing:

- a class-specific published split of line-of-duty death benefits
- a class-specific published split of line-of-duty disability benefits beyond
  the broad disability totals already used
- a published table that directly isolates the extra Special Risk-family payout
  slices implied by those richer provisions

Implication:

- the ACFR strengthens the case that the remaining `special` and `admin`
  residuals are policy-driven rather than arbitrary
- but the ACFR still does not publish enough class-specific detail to
  reconstruct the exact extra amount embedded in the legacy class outflow
  constants

## Truth-Table / Baseline Cash-Flow Nuance

The frozen FRS baseline also shows that administrative expenses are only present
in the initial year.

Evidence:

- [plans/frs/baselines/r_truth_table.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/r_truth_table.csv)
  - `2022 admin_exp = 22,494,571`
  - `2023+ admin_exp = 0`
- [plans/frs/baselines/frs_funding.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/frs_funding.csv)
  - `2022 admin_exp_legacy = 22,494,571`
  - `2023+ admin_exp_legacy = 0`
  - `2022 disbursement_to_IP = 768,106,850`
  - `2023+ disbursement_to_IP = 0`

Implication:

- the first-year baseline is using a broader observed cash-flow concept that
  includes admin expense and transfers to the investment plan
- later years are projected on a narrower modeled cash-flow basis
- that supports the interpretation that the first-year `ben_payment` estimate
  was backed out from a broader first-year disbursement base rather than drawn
  from a direct class benefit-payment table
- see also:
  - [year0_cashflow_treatment.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/year0_cashflow_treatment.md)

## What Is Not Yet Resolved

The current class-level runtime values now reduce to one clean runtime rule, but
the upstream provenance of the class outflow inputs is still unresolved.

Open points:

- where `regular_outflow`, `special_outflow`, `admin_outflow`,
  `judges_outflow`, `eso_outflow`, `eco_outflow`, and
  `senior_management_outflow` originally came from in the Reason/R workflow
- whether using valuation Table 2-4 line `3` was the right conceptual source
  for first-year benefit payments, or only a practical proxy
- how the Elected Officers' total was split across runtime `eco`, `eso`, and
  `judges`
- how the baseline class outflows reconcile to the ACFR statistical class
  annual-benefit table, especially for:
  - Elected Officers'
  - Special Risk Administrative Support
- how the baseline class outflows reconcile to valuation Table C-5 for:
  - current annuitants
  - future DROP annuities
  - any other payout component not plainly visible in one source table
- whether the class outflow concept is intended to represent:
  - annual benefits only
  - benefits plus some refund or other outflow component
  - or a class-specific proxy for a broader deductions concept

## Current Working Conclusion

For now, `valuation_inputs.{class}.ben_payment` should remain classified as:

- `derived`

And more specifically:

- exactly reproducible from the current reviewed baseline
- source-grounded through the plan-wide ACFR deductions ratio
- now strongly tied to valuation Table 2-4 line `3` class disbursement
  allocations for `2021/2022`
- but still dependent on a judgment about whether those allocated
  disbursements were the right conceptual basis for first-year benefit payments

The evidence now suggests that a fully reviewed reconstruction will probably
need:

1. one source for the plan-wide ACFR deductions ratio
2. one or more sources or build rules for class outflows
3. a documented allocation rule for EOC-related runtime subclasses
4. a reconciliation note explaining any difference between:
   - published class annual benefits
   - baseline class outflows
   - and runtime `ben_payment`

Until that provenance is reconstructed, the FRS `ben_payment` path should remain
an explicit open item in the prep pilot. The exact runtime numbers are no longer
the mystery; the upstream source-to-outflow mapping is.

Detailed reconstruction attempts and outcomes are tracked in:

- [legacy_reconstruction_log.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/legacy_reconstruction_log.md)
- [reason_artifact_clues.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/reason_artifact_clues.md)
