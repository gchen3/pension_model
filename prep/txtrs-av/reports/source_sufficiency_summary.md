# TXTRS-AV Source Sufficiency Summary

## Purpose

This is the first category-level sufficiency pass for `txtrs-av`.

The question is:

```text
Given the current runtime contract and the copied valuation source,
what looks directly recoverable, what looks derivable, and what still appears
blocked or runtime-only?
```

## Source Hierarchy Reminder

For `txtrs-av`:

- the AV is the source document
- external sources explicitly named in the AV are part of the authoritative
  source set for the governed item
- ACFR and similar documents are aids in estimation, reconciliation, or
  clue-mining unless a plan-specific review justifies a stronger role

## Primary Sources

- actuarial valuation:
  - [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20Valuation%202024.pdf)
- AV-referenced external sources:
  - `PUB(2010), Amount-Weighted, Below-Median Income, Teacher, Male and Female`
  - `2021 TRS of Texas Healthy Pensioner Mortality Tables`
  - `Scale UMP 2021`
- auxiliary estimation-support sources:
  - none yet copied into `prep/txtrs-av/`
- runtime-contract reference:
  - [docs/runtime_input_contract.md](/home/donboyd5/Documents/python_projects/pension_model/docs/runtime_input_contract.md)

## Status Legend

- `direct_from_av`
- `direct_from_av_referenced_external`
- `derived_from_av`
- `estimation_supported`
- `referenced_not_published`
- `runtime_only`
- `computed`
- `missing`

## First-Pass Assessment

| Runtime input area | First-pass status | Notes |
| --- | --- | --- |
| plan structure, classes, tiers | `direct_from_av` | One broad plan class with meaningful cohort/tier structure is strongly supported. |
| benefit formulas, vesting, NRA, early retirement, COLA, DROP rules | `direct_from_av` | The valuation is strong on plan provisions and reduction logic. |
| active headcount | `derived_from_av` | Table 17 is source-strong but requires canonical band-to-point transformation. |
| active salary | `derived_from_av` | Same Table 17 path as active headcount. |
| salary growth assumptions | `direct_from_av` | Appendix 2 provides inflation, general, and service-related salary growth structure. |
| retiree distribution | `estimation_supported` | Aggregate retiree tables exist, but exact age-by-age runtime structure is not clearly published. |
| entrant profile | `derived_from_av` | The valuation publishes a usable summary table with a now-understood boundary-merge build rule. |
| retirement assumptions | `derived_from_av` | Valuation support is good, but runtime table shape still requires normalization choices. |
| termination assumptions | `derived_from_av` | Source appears usable, but runtime expression still requires mapping. |
| early-retirement reduction tables or rules | `direct_from_av` | Printed provisions align well with runtime reduction-table concepts. |
| mortality basis names and mappings | `direct_from_av` | The valuation states the active and retiree basis families clearly. |
| mortality base-rate values | `referenced_not_published` | Full retiree basis values are not yet in hand in the repo. |
| mortality improvement-scale values | `referenced_not_published` | `Scale UMP 2021` is named, but its operational implementation still needs confirmation. |
| funding seed values for `init_funding.csv` | `direct_from_av` | Table 2, Table 3b, and Table 8a support a strong first-cut funding seed. |
| amortization-layer support | `runtime_only` | No evidence yet that `txtrs-av` needs FRS-style layered amortization. |
| source-linked portions of `plan_config.json` | `derived_from_av` | Core benefit and assumption content is source-linked, but runtime config also contains abstractions and computed settings. |
| runtime-only settings | `runtime_only` | Some current `txtrs` runtime semantics should not be copied into `txtrs-av` without explicit review. |
| calibration | `computed` | Calibration remains a downstream computed artifact. |

## Main Observations

- `txtrs-av` is ready for a controlled first cut.
- The valuation is strong enough to support the plan narrative, active grid,
  entrant profile, and first-pass funding inputs.
- The main source-faithful blockers are still retiree mortality and retiree
  distribution.
- A fresh `txtrs-av` build should not silently inherit broader `txtrs`
  runtime-only semantics.

## Main Risks For Source-To-Canonical Prep

- retiree mortality needs plan-specific external source material
- retiree distribution may require either a documented estimation method or a
  clearer upstream source path
- current `txtrs` runtime abstractions may be broader than the source-supported
  first-cut design

## Next Step

The next pass should be an artifact-level coverage matrix and then a first-cut
`plans/txtrs-av/` scaffold that only includes source-supported config and data
choices.
