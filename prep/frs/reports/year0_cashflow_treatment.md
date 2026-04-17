# FRS Year-0 Cash-Flow Treatment

## Purpose

This note records how the initial FRS baseline year (`2022`) handles observed
cash flows, and how that differs from later projected years.

The goal is to make explicit which parts of year 0 are source-anchored observed
amounts and which parts already reflect modeled or compatibility-oriented
funding logic.

## Primary Sources

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
  - Table 2-3 `Development of 2022 Actuarial Value of Assets`, printed p. `17`,
    PDF p. `22`
  - Table 2-4 `Development of Actuarial Value of Assets by Membership Class`,
    printed p. `18`, PDF p. `23`
- [2022-23_ACFR.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2022-23_ACFR.pdf)
  - GASB 67 deductions table, printed p. `155`, PDF p. `157`
- [plans/frs/baselines/frs_funding.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/frs_funding.csv)
- [plans/frs/baselines/r_truth_table.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/r_truth_table.csv)

## Year 0 Uses Broader Observed Cash Flows

In the frozen baseline, year `2022` carries these observed system-level values:

- `total_ben_payment = 11,944,986,866`
- `total_refund = 28,343,757`
- `disbursement_to_IP = 768,106,850`
- `admin_exp_legacy = 22,494,571`

These match the ACFR deductions table exactly.

The same year-0 pattern appears in the frozen truth table:

- `2022 benefits = 11,944,986,866`
- `2022 refunds = 28,343,757`
- `2022 admin_exp = 22,494,571`

But later years differ:

- `2023+ admin_exp = 0` in the frozen truth table
- `2023+ admin_exp_legacy = 0`
- `2023+ disbursement_to_IP = 0`

So year 0 is clearly using a broader observed cash-flow concept than later
projected years.

## Exact Year-0 Baseline Net-Cash-Flow Identity

For `2022`, the stored baseline net cash flow is:

- `net_cf_legacy = -7,650,488,551`

That value is exactly:

- `total_ee_nc_cont + total_er_db_cont`
- minus `total_ben_payment`
- minus `total_refund`
- minus `disbursement_to_IP`
- minus `admin_exp_legacy`

Using the frozen baseline values:

- `total_ee_nc_cont = 763,674,943`
- `total_er_db_cont = 4,349,768,550`
- contribution side total = `5,113,443,493`
- disbursement side total = `12,763,932,044`
- net cash flow = `5,113,443,493 - 12,763,932,044 = -7,650,488,551`

This is a clean year-0 baseline identity.

## Relationship To Valuation Table 2-3 / Table 2-4

The valuation publishes:

- Table 2-3 line `3` `2021/2022 Net Cash Flow`
  - `-7,615,598,682`
- Table 2-4 line `2` total contribution for the plan year
  - `5,148,333,000`
- Table 2-4 line `3` total `Benefit Payments and other Disbursements`
  - `12,763,932,000`

Those valuation table totals imply:

- `5,148,333,000 - 12,763,932,000 = -7,615,599,000`

which matches Table 2-3 line `3` apart from rounding.

So year 0 has two related but distinct identities:

1. valuation AVA-development identity
   - `Table 2-4 line 2 - Table 2-4 line 3`
2. frozen baseline identity
   - `total_ee_nc_cont + total_er_db_cont - benefits - refunds - IP - admin`

The disbursement side matches closely and conceptually:

- baseline `benefits + refunds + disbursement_to_IP + admin`
  = `12,763,932,044`
- valuation Table 2-4 line `3`
  = `12,763,932,000`

But the contribution side does not match exactly:

- baseline `total_ee_nc_cont + total_er_db_cont`
  = `5,113,443,493`
- valuation Table 2-4 line `2`
  = `5,148,333,000`
- difference
  = `34,889,507`

That difference explains why the frozen baseline year-0 `net_cf_legacy` is
about `34.9` million lower than the valuation Table 2-3 net-cash-flow figure.

## Current Interpretation

The evidence now supports the following reading:

1. year 0 uses observed plan-wide disbursement totals directly from the ACFR
2. class-level first-year outflow inputs are strongly tied to valuation Table
   2-4 line `3` class disbursement allocations
3. the baseline then backs out class benefit payments from that broader
   disbursement base using the plan-wide ACFR benefit share
4. later years move to a narrower projected cash-flow treatment with no
   explicit admin expense or IP disbursement

## What Is Resolved

- year 0 is not treated the same way as later years
- the broader observed year-0 disbursement base is explicit
- the truth table’s initial-year admin-expense behavior is real, not accidental
- the baseline year-0 net cash flow has a clean identity using baseline
  contribution and disbursement columns

## What Is Not Yet Resolved

- why the baseline contribution side for year 0 uses
  `total_ee_nc_cont + total_er_db_cont` rather than the exact valuation Table
  2-4 line `2` total contribution amount
- whether that difference is an intentional modeling choice, a legacy
  compatibility artifact, or a byproduct of how the baseline funding files were
  assembled
- whether first-year class benefit payments should continue to be inferred from
  broader class disbursement allocations in future prep work

