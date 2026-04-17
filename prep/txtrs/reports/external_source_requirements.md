# TXTRS External Source Requirements

## Purpose

This note records the external-source items that still appear necessary to move
TXTRS from:

- exact reproduction of the current reviewed stage-3 mortality artifact

to:

- source-faithful reconstruction of the valuation's stated mortality basis

## Current State

Already in hand under
[prep/common/sources](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources):

- `soa_pub2010_amount_mort_rates.xlsx`
- `soa_mp2021_rates.xlsx`
- related SOA report PDFs

Not currently in hand:

- `2021 TRS of Texas Healthy Pensioner Mortality Tables`

Documented local search result:

- no local copy of the healthy-pensioner tables was found under `prep/`,
  `plans/`, `scripts/`, or `R_model/`

## Why This Matters

The 2024 valuation states:

- active mortality:
  `PUB(2010), Amount-Weighted, Below-Median Income, Teacher, Male and Female`
  with a 2-year male set forward and MP-2021-style improvement
- post-retirement mortality:
  `2021 TRS of Texas Healthy Pensioner Mortality Tables`
  projected generationally by `Scale UMP 2021`
- disabled retiree mortality:
  a 3-year set forward of the healthy-pensioner tables, with minimum mortality
  floors

This means the source-faithful retiree basis is not fully covered by the shared
SOA references already in hand.

## Required External Inputs

### 1. TRS-specific healthy pensioner mortality table source

Needed item:

- the full `2021 TRS of Texas Healthy Pensioner Mortality Tables`

Why needed:

- the valuation names this as the post-retirement basis
- the current runtime uses a Pub-2010 compatibility basis instead
- more specifically, the current runtime uses distinct Pub-2010 `Employee` and
  `Healthy Retiree` columns under one shared Pub-2010 table family label
- without the full table values, we cannot claim source-faithful retiree
  mortality reconstruction

What to record when acquired:

- source document title
- issuing organization
- publication year
- local filename
- original filename if different
- source URL or acquisition note
- hash
- any licensing or reuse constraints

### 2. Operational meaning of `Scale UMP 2021`

Needed clarification:

- whether `Scale UMP 2021` is operationally identical to the shared SOA
  `MP-2021` workbook already in hand
- or whether it requires a modified ultimate-rate implementation that differs
  from a direct MP-2021 load

Why needed:

- current runtime uses `mp_2021`
- the valuation names `Scale UMP 2021`
- those may be equivalent in practice, but that should be confirmed rather than
  assumed
- the current reviewed runtime uses MP-2021 in a compatibility path, but that
  alone does not prove source-faithful implementation of the valuation's
  retiree basis

Additional implementation clue already in hand:

- the archived
  [TxTRS_R_BModel revised.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_R_BModel%20revised.R)
  explicitly notes:
  - `Since the plan assumes "immediate convergence" of MP rates, the "ultimate rates" are used for all years`
- but the current active
  [TxTRS_model_inputs.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_model_inputs.R)
  path appears to use the evolving MP schedule through the available years and
  only then hold at the ultimate rate

So the remaining question is not only “what external table is needed,” but also
“which implementation of the improvement scale is the correct one.”

Acceptable evidence could include:

- a plan-specific mortality appendix or technical note
- an official workbook or table source
- a documented actuarial note explaining the intended implementation

## What Is Still Possible Without These Items

Even before these external items are acquired, we can still:

- reproduce the current reviewed stage-3 mortality artifact
- document clearly that it is a compatibility construction
- show where it aligns with the valuation's active-mortality basis
- show where it diverges from the valuation's retiree-mortality basis

## Current Working Conclusion

For TXTRS, the main unresolved source need is not another shared SOA download.
It is a plan-specific retiree-mortality source plus a confirmation of how
`Scale UMP 2021` should be implemented.

See also:

- [mortality_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/mortality_mapping.md)
- [soa_reference_inventory.md](/home/donboyd5/Documents/python_projects/pension_model/prep/common/reports/soa_reference_inventory.md)
