# TXTRS-AV First-Cut AV Data Batch 02: Funding Seed

## Purpose

This note records the first `txtrs-av` funding seed built directly from the
local 2024 valuation PDF.

The goal is to add the most source-backed missing funding input without pulling
runtime values across from `txtrs`.

## Artifact Built

- [init_funding.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs-av/data/funding/init_funding.csv)

## Source Pages Used

- Table 2 `Summary of Cost Items`
  - printed page `17`
  - PDF page `24`
- Table 4 `Development of Actuarial Value of Assets`
  - printed page `20`
  - PDF page `27`

## Published Values Used

From Table 2:

- projected payroll for contributions = `61,388,248,000`
- actuarial accrued liability = `273,095,060,051`
- actuarial value of assets = `212,520,440,440`
- administrative expenses rate = `0.14%`

From Table 4:

- market value of assets at end of year = `210,543,258,495`
- remaining after this valuation for the `2023` AVA deferral row = `1,977,181,945`

## Build Rule

The funding seed is produced by:

- [build_txtrs_av_from_av.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/build_txtrs_av_from_av.py)

Direct source mappings:

- `total_payroll` from Table 2 projected payroll
- `total_aal`, `aal_legacy` from Table 2 actuarial accrued liability
- `total_ava`, `ava_legacy` from Table 2 actuarial value of assets
- `total_mva`, `mva_legacy` from Table 4 market value of assets
- `admin_exp_rate` from Table 2 administrative-expenses rate

Direct derived fields:

- `total_ual_ava = total_aal - total_ava`
- `total_ual_mva = total_aal - total_mva`
- `fr_ava = total_ava / total_aal`
- `fr_mva = total_mva / total_aal`

Runtime-only structural mapping:

- The valuation publishes the remaining AVA deferral as one aggregate balance.
- The runtime funding method stores gain/loss smoothing in bucket form.
- For the 2024 opening row, the entire remaining balance comes from the `2023`
  deferral row in Table 4 and has three recognition years left after the 2024
  valuation.
- In the current funding runtime, that opening state maps to
  `defer_y2_legacy = -1,977,181,945`, with the other legacy and new deferral
  buckets set to zero.

## Scope Notes

This file is intentionally a funding **seed**, not a full funding projection
input set.

It does **not** yet include:

- `return_scenarios.csv`
- a reviewed source-backed treatment of retirement/termination assumptions in
  the funding loop

It also does not try to encode more class detail than the current `txtrs-av`
runtime can yet support.

## Remaining Required Runtime Files

- `demographics/retiree_distribution.csv`
- `decrements/all_termination_rates.csv`
- `decrements/all_retirement_rates.csv`
- `mortality/base_rates.csv`
- `mortality/improvement_scale.csv`
- `funding/return_scenarios.csv`

## Implication

`txtrs-av` now has a source-backed opening funding seed.

The clean next source-strong targets are still:

1. retirement rates
2. termination rates
3. mortality files
4. retiree distribution

