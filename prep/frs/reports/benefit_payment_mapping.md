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

## Three Relevant Source Families

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

### 2. ACFR statistical annuitant / annual-benefit tables

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

### 3. Valuation annuitant-benefit table

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

Example exact reproductions:

- regular:
  - `8,967,096,000 * 0.9358391148451025 = 8,391,759,183.371059`
- judges:
  - `105,844,000 * 0.9358391148451025 = 99,052,955.271665`
- eco:
  - `9,442,000 * 0.9358391148451025 = 8,836,192.922367`

## Reconciliation Evidence

The baseline class outflows are not an exact copy of either published
class-benefit table.

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

This pattern strongly suggests that the baseline class outflows are a legacy
intermediate allocation, not a direct copy of one published table.

The workbook evidence sharpens that conclusion:

- the plan-wide row-10 values are source-direct and match the ACFR deductions
  table exactly
- the unresolved part is now much narrower: where the class outflow constants
  themselves came from before being multiplied through that row-10 block

## What Is Not Yet Resolved

The current class-level runtime values now reduce to one clean runtime rule, but
the upstream provenance of the class outflow inputs is still unresolved.

Open points:

- where `regular_outflow`, `special_outflow`, `admin_outflow`,
  `judges_outflow`, `eso_outflow`, `eco_outflow`, and
  `senior_management_outflow` originally came from in the Reason/R workflow
- whether those class outflows were copied directly from one published table,
  or derived from a more complex intermediate allocation
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
- but still dependent on upstream class outflow inputs whose published
  provenance has not yet been reconstructed

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
