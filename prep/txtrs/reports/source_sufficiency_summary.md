# TXTRS Source Sufficiency Summary

## Purpose

This is the first source-sufficiency pass for TXTRS.

It is intentionally category-level rather than file-by-file or field-by-field.
The question here is:

```text
Given the current runtime contract, what appears recoverable from the TXTRS PDFs,
what will require transformation or judgment, and what is not fully published?
```

Primary sources:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
- [Texas TRS ACFR 2023.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20ACFR%202023.pdf)
- [prep/txtrs/reports/narrative_plan_analysis.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/narrative_plan_analysis.md)
- [docs/runtime_input_contract.md](/home/donboyd5/Documents/python_projects/pension_model/docs/runtime_input_contract.md)

## Status Legend

- `direct`: clearly reported in the PDFs in a form close to runtime needs
- `derived`: available from the PDFs, but only after transformation, regrouping, or scaling
- `referenced_not_published`: the PDFs identify the concept or basis, but do not appear to publish the full canonical table values
- `runtime_only`: needed by the runtime but not document-sourced
- `computed`: produced by procedure rather than sourced from documents

## First-Pass Assessment

| Runtime input area | First-pass status | Notes |
| --- | --- | --- |
| plan structure, broad classing, cohorts/tiers | `direct` | The valuation clearly supports one broad class plus multiple benefit cohorts driven by hire and vesting status. |
| benefit formulas, retirement eligibility, early-retirement reductions, partial lump sum, legacy DROP | `direct` | The valuation is strong on plan provisions and reduction logic. |
| active/member status counts | `direct` | ACFR reports active, inactive non-vested, inactive vested, and retirement-recipient counts. |
| active salary/headcount detail in runtime-ready shape | `derived` | The valuation publishes `Distribution of Active Members by Age and Service` with counts and average compensation. The runtime files still require a band-to-point transformation and matrix melt. |
| salary growth assumptions | `direct` | The valuation explicitly reports inflation, a general salary component, and service-related merit scales. |
| retiree distribution | `derived` | The documents provide retiree counts and benefit-payment context, but not obviously in the exact runtime distribution layout. |
| entrant profile | `derived` | The valuation publishes a `NEW ENTRANT PROFILE` summary table, but the current runtime artifact is more granular and will require a build rule. |
| retirement assumptions | `derived` | The valuation reports retirement assumptions and cohort-specific adjustments, but the exact runtime table shape still needs mapping. |
| termination assumptions | `derived` | The source documents appear to provide termination assumptions, but the exact lookup structure used by the runtime needs confirmation. |
| early-retirement reduction tables | `direct` | The valuation describes cohort-specific reduction structures closely aligned with the current runtime's reduction-table concept. |
| mortality basis names | `direct` | The valuation identifies the 2021 TRS of Texas Healthy Pensioner Mortality Tables and Scale UMP 2021. |
| mortality base-rate values | `referenced_not_published` | The valuation names the mortality basis, but it is not yet clear that the full base-rate tables are reproduced in the PDFs. |
| mortality improvement-scale values | `referenced_not_published` | The valuation names Scale UMP 2021, but the full scale values are not clearly published in the PDFs. |
| funding seed values for `init_funding.csv` | `direct` | The valuation and ACFR provide funded ratio, UAAL, contribution context, and other core funding values. Exact column mapping still needs build rules. |
| return scenarios | `runtime_only` | These are model/scenario inputs, not source-document facts. |
| source-linked portions of `plan_config.json` | `derived` | Core benefit and assumption content is source-linked, but the config also includes runtime/modeling choices. |
| current `benefit_types` mix of `db`, `cb`, `dc` | `runtime_only` | The source documents reviewed here describe a DB plan; the broader runtime `benefit_types` setting appears to reflect general model capability, not direct source description. |
| calibration | `computed` | `calibration.json` is computed to match valuation targets, not sourced from the PDFs. |

## Main Observations

- TXTRS looks strong for plan structure, cohort logic, and actuarial assumptions.
- The main likely weakness is detailed demographic reconstruction in the exact stage-3 shape.
- Mortality is again a likely boundary case where the PDFs state the basis but may not publish the full canonical tables.
- The current runtime appears to contain at least one important modeling/generalization choice, `benefit_types`, that is not directly supported by the source documents.

## Main Risks For PDF-To-Stage-3 Reproduction

- Detailed salary and headcount cells may not be published in the same grid structure the runtime consumes.
- Termination and retirement assumptions may need careful re-expression to preserve their actuarial meaning in canonical prep outputs.
- Mortality inputs may require approved external source tables even if the plan valuation identifies the correct basis.
- Some current runtime choices may reflect earlier implementation generalization rather than direct TXTRS source facts.

## Next Step

The next TXTRS pass should be a field-level coverage matrix that maps:

- each current stage-3/runtime artifact
- to source document/table/page
- with a status of direct, derived, referenced-not-published, runtime-only, or computed

That should be done after the source-registry and naming conventions are finalized.
