# FRS Source Sufficiency Summary

## Purpose

This is the first source-sufficiency pass for FRS.

It is intentionally category-level rather than file-by-file or field-by-field.
The question here is:

```text
Given the current runtime contract, what appears recoverable from the FRS PDFs,
what will require transformation or judgment, and what is not fully published?
```

Primary sources:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
- [2022-23_ACFR.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2022-23_ACFR.pdf)
- [prep/frs/reports/narrative_plan_analysis.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/narrative_plan_analysis.md)
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
| plan structure, classes, tiers | `direct` | AV and ACFR clearly describe the DB Pension Plan, the DC Investment Plan alternative, the five main classes, EOC subgroups, and the pre/post July 1 2011 tier split. |
| benefit formulas, vesting, NRA, early retirement, COLA, DROP rules | `direct` | Appendix B is strong here and closely tracks what the runtime needs conceptually. |
| active headcount by class | `direct` | AV Appendix C gives DB-plan counts by class; ACFR gives broader system totals by class. Scope tagging will be essential. |
| active salary by class | `direct` | AV Appendix C gives DB-plan salary totals by class; class-by-age/service detail is published at least for major classes. |
| salary growth assumptions | `derived` | The valuation reports individual salary increase assumptions by service and membership class, but these will need normalization into the runtime CSV shape. |
| retiree distribution | `derived` | The PDFs provide annuitant counts and annual benefits by class and DROP summaries, but not obviously in the exact runtime `retiree_distribution.csv` layout. |
| entrant profile | `referenced_not_published` | No clear entrant profile table has been identified in the AV or ACFR. |
| retirement assumptions | `derived` | The valuation publishes retirement tables by tier, class, sex, K-12 status, and law-enforcement subset. Runtime tables will need a documented reduction from that richer source structure. |
| termination assumptions | `derived` | Withdrawal tables are published by age, service, sex, and broad class grouping. They are source-rich but not already in runtime-ready form. |
| early-retirement reduction tables | `direct` | FRS mainly uses rule-based early-retirement reductions rather than plan-specific reduction CSVs. The rules are directly reported. |
| mortality basis names and mappings | `direct` | The valuation clearly states PUB-2010 family mappings and MP-2018 improvement, segmented by member category. |
| mortality base-rate values | `referenced_not_published` | The valuation names the PUB-2010 base tables but does not itself publish the full underlying mortality-rate tables needed for `base_rates.csv`. |
| mortality improvement-scale values | `referenced_not_published` | The valuation identifies MP-2018, but the full scale values are not published in the FRS PDFs. |
| funding seed values for `init_funding.csv` | `derived` | The valuation and ACFR report assets, liabilities, contribution rates, and class-level funding context. A build rule will still be needed to map exactly to runtime columns. |
| return scenarios | `runtime_only` | These are model/scenario inputs, not source-document facts. |
| source-linked portions of `plan_config.json` | `derived` | Much of the class, tier, benefit, and valuation-input content is source-linked, but the current config mixes those with runtime choices. |
| plan-design / DB-vs-DC choice settings | `derived` | FRS source docs confirm the DB-plus-DC-choice structure, but current runtime design-ratio settings likely require interpretation and possibly additional non-PDF evidence. |
| calibration | `computed` | `calibration.json` is computed to match valuation targets, not sourced from the PDFs. |

## Main Observations

- FRS is strong on plan structure and actuarial-table publication.
- The most important source complication is scope:
  - valuation tables are often DB-plan-only
  - ACFR tables can be system-wide and include Investment Plan or renewed membership
- Exact mortality CSV reconstruction will probably require approved external table sources for PUB-2010 and MP-2018, because the PDFs identify the basis but do not reproduce the full standard tables.
- Exact runtime reconstruction will also require a documented transformation from richer source assumptions to the current runtime table shapes.

## Main Risks For PDF-To-Stage-3 Reproduction

- Mixed-scope tables could create false mismatches if Pension Plan and system-wide values are compared directly.
- Current runtime plan-choice behavior may encode assumptions not fully recoverable from the AV and ACFR alone.
- Some values currently in config appear derived from financial-flow tables rather than directly published as runtime-ready Pension Plan inputs.
- Mortality is a clear boundary case where the PDFs describe the basis but do not appear to publish the full canonical data table.

## Next Step

The next FRS pass should be a field-level coverage matrix that maps:

- each current stage-3/runtime artifact
- to source document/table/page
- with a status of direct, derived, referenced-not-published, runtime-only, or computed

That should be done after the source-registry and naming conventions are finalized.
