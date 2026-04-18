# TXTRS-AV Artifact Coverage Matrix

## Purpose

This is the first artifact-level coverage pass for `txtrs-av`.

The goal is to map the expected runtime artifacts under `plans/txtrs-av/` to
their likely source basis and current prep status.

## Primary References

- actuarial valuation:
  - [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20Valuation%202024.pdf)
- AV-referenced external sources:
  - plan-specific mortality tables and scales named in the valuation
- auxiliary estimation-support sources:
  - none copied yet into `prep/txtrs-av/`
- narrative analysis:
  - [narrative_plan_analysis.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/reports/narrative_plan_analysis.md)
- source sufficiency summary:
  - [source_sufficiency_summary.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/reports/source_sufficiency_summary.md)

## Status Legend

- `direct_from_av`
- `direct_from_av_referenced_external`
- `derived_from_av`
- `estimation_supported`
- `referenced_not_published`
- `runtime_only`
- `computed`
- `missing`

## Config Artifacts

| Runtime artifact | Status | Likely primary source(s) | Notes |
| --- | --- | --- | --- |
| `plans/txtrs-av/config/plan_config.json` | `derived_from_av` | AV plan provisions and assumptions | A first-cut config should include only source-supported plan structure plus clearly labeled runtime-only settings. |
| `plans/txtrs-av/config/calibration.json` | `computed` | runtime calibration procedure | Not source-direct. |

## Demographics Artifacts

| Runtime artifact | Status | Likely primary source(s) | Notes |
| --- | --- | --- | --- |
| `plans/txtrs-av/data/demographics/all_headcount.csv` | `derived_from_av` | AV Table 17 | Strong candidate for first-cut exact build. |
| `plans/txtrs-av/data/demographics/all_salary.csv` | `derived_from_av` | AV Table 17 | Same source path as active headcount. |
| `plans/txtrs-av/data/demographics/entrant_profile.csv` | `derived_from_av` | AV Appendix 2 `NEW ENTRANT PROFILE` | Boundary-merge build rule is already understood. |
| `plans/txtrs-av/data/demographics/retiree_distribution.csv` | `estimation_supported` | AV retiree summary tables; possibly auxiliary sources later | Exact PDF-only path is not yet established. |
| `plans/txtrs-av/data/demographics/salary_growth.csv` | `derived_from_av` | AV Appendix 2 salary increase assumptions | Canonical runtime format will require normalization. |

## Decrement Artifacts

| Runtime artifact | Status | Likely primary source(s) | Notes |
| --- | --- | --- | --- |
| `plans/txtrs-av/data/decrements/retirement_rates.csv` | `derived_from_av` | AV Appendix 2 retirement assumptions | Source support is good, but runtime expression needs review. |
| `plans/txtrs-av/data/decrements/termination_rates.csv` | `derived_from_av` | AV Appendix 2 termination assumptions | Likely buildable in first cut. |
| `plans/txtrs-av/data/decrements/reduction_gft.csv` | `direct_from_av` | AV plan provisions | Strong source fit. |
| `plans/txtrs-av/data/decrements/reduction_others.csv` | `direct_from_av` | AV plan provisions | Strong source fit. |

## Funding Artifacts

| Runtime artifact | Status | Likely primary source(s) | Notes |
| --- | --- | --- | --- |
| `plans/txtrs-av/data/funding/init_funding.csv` | `derived_from_av` | AV Table 2, Table 3b, Table 8a | Strong first-cut candidate. |
| `plans/txtrs-av/data/funding/return_scenarios.csv` | `runtime_only` | runtime/scenario design | Not document-sourced. |

## Mortality Artifacts

| Runtime artifact | Status | Likely primary source(s) | Notes |
| --- | --- | --- | --- |
| `plans/txtrs-av/data/mortality/base_rates.csv` | `referenced_not_published` | AV-stated active and retiree mortality basis plus AV-referenced external tables | Full source-faithful retiree basis is still missing. |
| `plans/txtrs-av/data/mortality/improvement_scale.csv` | `referenced_not_published` | AV `Scale UMP 2021` | Implementation still needs confirmation. |

## Main Coverage Conclusions

- `txtrs-av` has enough source support to start a controlled first cut.
- The clearest first-cut build targets are active demographics, entrant profile,
  reduction tables, and funding seed values.
- Mortality and retiree distribution should be carried as explicit gap areas
  until their source path is tightened.

## Next Field-Level Follow-Up

For the highest-value artifacts, the next pass should map critical fields or
field groups to:

- source document ID
- printed page
- PDF page
- table or section label
- source unit
- canonical unit
- transform rule
- provenance type
