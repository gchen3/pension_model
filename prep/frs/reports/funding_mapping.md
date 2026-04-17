# FRS Funding Mapping Notes

## Purpose

This note records the current understanding of how the most important FRS
`init_funding.csv` fields map back to source documents, and which ones are still
best treated as compatibility-oriented build artifacts rather than direct
document extractions.

Primary references:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
- [2022-23_ACFR.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2022-23_ACFR.pdf)
- [plans/frs/data/funding/init_funding.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/data/funding/init_funding.csv)

## Strong Source Anchors

### System-level valuation funding anchors

These values are directly published in the 2022 valuation and match the current
aggregate `frs` funding row after conversion from thousands to dollars.

Source tables:

- valuation summary table in Section 1
- Table 2-3 `Development of 2022 Actuarial Value of Assets`, printed p. `17`, PDF p. `22`
- Table 3-2 `Actuarial Liabilities by Membership Class`, printed p. `24`, PDF p. `29`

Current aggregate matches:

- `total_aal = 217,434,441,000`
  - from Table 3-2, total actuarial liability
- `total_ava = 179,178,895,000`
  - from Table 2-3 and Table 3-2, actuarial value of assets
- `total_ual_ava = 38,255,546,000`
  - from Table 3-2, unfunded actuarial liability on AVA basis
- `fr_ava = 0.8240594000...`
  - derived from Table 3-2 funded ratio `82.41%`
- `total_mva = 180,226,405,000`
  - from Table 2-1 / Section 5 market-value asset totals
- `total_ual_mva = 37,208,036,000`
  - derived as `total_aal - total_mva`
- `fr_mva = 0.8288769900...`
  - derived as `total_mva / total_aal`
- `roa = -0.0718`
  - from Table 2-6 market-value rate of return for 2021/2022

### Class-level valuation funding anchors

Source table:

- Table 3-2 `Actuarial Liabilities by Membership Class`, printed p. `24`, PDF p. `29`

Current class rows match this table cleanly for:

- `total_aal`
- `total_ava`
- `total_ual_ava`
- `fr_ava`

Examples:

- regular:
  - AAL `145,585,523,000`
  - AVA `123,245,363,000`
  - UAL `22,340,160,000`
- special:
  - AAL `45,070,773,000`
  - AVA `36,060,861,000`
  - UAL `9,009,912,000`
- senior management:
  - AAL `6,039,701,000`
  - AVA `3,391,319,000`
  - UAL `2,648,382,000`

### Class-level AVA allocation support

Source table:

- Table 2-4 `Development of Actuarial Value of Assets by Membership Class`, printed p. `18`, PDF p. `23`

This table supports the class-level AVA values and also shows the valuation’s
internal asset-allocation mechanics:

- total contribution for plan year
- benefit payments and other disbursements
- allocated investment earnings on AVA basis
- unadjusted AVA
- net reallocation to/from DROP
- allocated AVA by class at July 1, 2022

This is one of the strongest source tables in the repo for funding provenance.

### Contribution-rate anchors

Source table:

- Table 4-11 `Actuarially Calculated Employer Contribution Rates Prior to Blending with FRS Investment Plan`, printed p. `39`, PDF p. `44`

This table anchors:

- `nc_rate_db_legacy`
- `amo_rate_legacy`
- `er_stat_rate`

Examples:

- regular:
  - normal cost `5.96%`
  - UAL contribution rate `6.27%`
  - total employer contribution rate `12.23%`
- special:
  - normal cost `17.13%`
  - UAL contribution rate `12.62%`
  - total employer contribution rate `29.75%`
- admin:
  - normal cost `11.57%`
  - UAL contribution rate `33.81%`
  - total employer contribution rate `45.38%`

### Plan-wide cash-flow anchors

Source:

- ACFR GASB 67 disclosure `Statement of Changes in Fiduciary Net Position`, printed p. `155`, PDF p. `157`

Published 2022 plan-wide values match the aggregate funding row:

- `total_ben_payment = 11,944,986,866`
- `total_refund = 28,343,757`
- `disbursement_to_IP = 768,106,850`
- `admin_exp_legacy = 22,494,571`

These are system-level cash-flow anchors, not class-level source tables.

## Year-0 Observed Cash-Flow Treatment

The frozen baseline treats the initial year differently from later projected
years.

In `2022`, the frozen baseline uses explicit observed values for:

- `total_ben_payment`
- `total_refund`
- `disbursement_to_IP`
- `admin_exp_legacy`

But in later years:

- `admin_exp_legacy = 0`
- `disbursement_to_IP = 0`

So year 0 uses a broader observed cash-flow concept than later modeled years.

One useful identity is exact in the frozen baseline for `2022`:

- `net_cf_legacy`
  = `total_ee_nc_cont + total_er_db_cont`
  - `total_ben_payment`
  - `total_refund`
  - `disbursement_to_IP`
  - `admin_exp_legacy`

That year-0 baseline identity is closely related to valuation Table 2-3 and
Table 2-4, but it is not identical on the contribution side. The disbursement
side matches the valuation totals almost exactly, while the contribution side is
about `$34.9` million lower than valuation Table 2-4 line `2`.

This distinction matters because it shows that the initial funding row is a
hybrid of:

- observed valuation / ACFR cash flows
- and compatibility-oriented baseline funding logic

See also:

- [year0_cashflow_treatment.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/year0_cashflow_treatment.md)

## Clean But Limited ACFR Payroll Anchors

Source:

- ACFR `Annual FRS Payroll by System/Class`, printed p. `191`, PDF p. `193`

This table directly supports:

- class-level `total_payroll`

Examples from the 2022 column:

- regular = `29,126,383,663`
- special = `5,451,709,307`
- admin = `5,381,322`
- Elected Officers' = `211,724,251`
- senior management = `824,335,420`

This is strong support for the total payroll fields used in config and funding.

## Where The Current Funding Seed Stops Being Source-Direct

Some important `init_funding.csv` columns are **not** clean direct source
quantities.

### 1. DB/DC payroll splits

Examples:

- `payroll_db_legacy`
- `payroll_dc_legacy`

These do not appear as published fields in the valuation or ACFR in the same
form as the current runtime seed.

The ACFR gives total payroll by system/class. The runtime seed then carries a
split between:

- DB payroll
- DC payroll

Those splits appear to be compatibility-oriented inputs tied to historical
baseline logic and runtime design-ratio structure, not plain published source
tables.

### 2. EOC runtime subclass rows

Runtime has separate rows for:

- `eco`
- `eso`
- `judges`

But source tables often publish a single Elected Officers' total or use
Judicial / Leg-Atty-Cab / Local subclass tables under actuarial funding
sections.

So the mapping from published EOC-related source totals to runtime subclass rows
still needs an explicit reviewed split rule.

### 3. DROP row semantics

The valuation publishes DROP separately for funding purposes, and Table 4-11 is
clear that DROP rates are special charges rather than standard normal-cost / UAL
rates.

That means the runtime `drop` row is source-grounded, but it is not just “one
more ordinary class.”

## Current Working Classification

### Direct or near-direct from published source

- `total_aal`
- `total_ava`
- `total_mva`
- `total_ual_ava`
- `total_ual_mva`
- `fr_ava`
- `fr_mva`
- `roa`
- plan-wide benefit/refund/IP/admin cash-flow totals
- class-level total payroll
- class-level normal-cost and UAL contribution rates

### Derived / compatibility-oriented

- `payroll_db_legacy`
- `payroll_dc_legacy`
- `er_dc_rate_legacy`
- class-level benefit-payment allocations
- some EOC subclass rows
- aggregate rows that reflect runtime grouping rather than a single source table

## Implication For Prep

For the FRS pilot, `init_funding.csv` should be treated as a mixed artifact:

- part direct source reconstruction
- part documented transformation
- part compatibility-oriented runtime seed

That is acceptable for the pilot as long as the provenance is explicit.

The key mistake would be to treat the entire file as if every column came from
one source table. It does not.
