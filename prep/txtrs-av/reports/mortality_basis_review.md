# TXTRS-AV Mortality Basis Review

## Plan And Source Context

- Plan: `txtrs-av`
- Valuation report used:
  - [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20Valuation%202024.pdf)
- Other mortality-related documents used:
  - current TXTRS pilot mortality notes for comparison only
- Shared external references used:
  - none yet copied into `prep/txtrs-av/`
- Missing external references:
  - `2021 TRS of Texas Healthy Pensioner Mortality Tables`
  - confirmation of how `Scale UMP 2021` should be implemented

## 1. Source-Stated Mortality Basis

| Member state | Stated basis | Projection scale | Special adjustments | Source location | Notes |
| --- | --- | --- | --- | --- | --- |
| active | `PUB(2010), Amount-Weighted, Below-Median Income, Teacher, Male and Female` | MP-2021-style generational improvement | male set forward `2` years | printed p. `60`, PDF p. `67` | Strong active-basis statement. |
| healthy retiree | `2021 TRS of Texas Healthy Pensioner Mortality Tables` | `Scale UMP 2021` | immediate convergence wording appears relevant | printed p. `64`, PDF p. `71` | Main source-faithful gap. |
| disabled retiree | healthy-pensioner tables with `3`-year set forward | `Scale UMP 2021` | minimum mortality floors for female `0.0200`, male `0.0400` | printed p. `64`, PDF p. `71` | Implementation details matter. |

## 2. Runtime Mortality Representation

| Runtime item | Current value / structure | Location | Notes |
| --- | --- | --- | --- |
| plan config base table | not yet created for `txtrs-av` | `plans/txtrs-av/config/plan_config.json` | Should not be copied blindly from `txtrs`. |
| plan config improvement scale | not yet created for `txtrs-av` | `plans/txtrs-av/config/plan_config.json` | Needs explicit review. |
| sex handling | not yet decided | runtime build pending | Current model semantics may average by sex downstream. |
| employee / retiree distinction | needed | runtime build pending | The valuation clearly distinguishes active and retiree basis families. |
| disabled-retiree handling | needed | runtime build pending | Floors and set-forward must be explicit if modeled. |

## 3. External Source Inventory

| Source file / table | Present? | Provenance known? | Used by current runtime? | Needed for source-faithful build? | Notes |
| --- | --- | --- | --- | --- | --- |
| shared SOA base table for active basis | no | no | not yet for `txtrs-av` | yes | Likely needed for active source-faithful build. |
| shared improvement scale workbook | no | no | not yet for `txtrs-av` | maybe | May help with active basis, but retiree implementation still needs confirmation. |
| plan-specific retiree table | no | no | no | yes | Main missing source. |
| plan-specific technical note | no | no | no | maybe | Might be needed to resolve `Scale UMP 2021` implementation details. |

## 4. Implementation Rules To Confirm

| Question | Current understanding | Evidence | Status | Notes |
| --- | --- | --- | --- | --- |
| male/female set forward | active male set forward `2` years | valuation text | partial | Likely straightforward for active basis. |
| immediate convergence | valuation wording suggests it matters for retiree basis | valuation text and prior TXTRS pilot notes | partial | Needs confirmed operational rule. |
| ultimate-rate handling | not yet confirmed for `txtrs-av` | no direct implementation note in local `txtrs-av` source set | open | Could affect improvement-scale build. |
| disabled-retiree floor timing | floors are stated | valuation text | partial | Need explicit implementation timing. |
| sex aggregation in runtime | current model may aggregate later | existing runtime behavior, not `txtrs-av` source | open | Keep separate from source basis. |

## 5. Sample-Rate Comparison

| Member state | Year | Age | Valuation sample | Runtime resolved rate | Difference | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| active |  |  |  |  |  | not yet built for `txtrs-av` |
| retiree |  |  |  |  |  | not yet built for `txtrs-av` |
| disabled retiree |  |  |  |  |  | not yet built for `txtrs-av` |

## 6. Alignment Assessment

### A. Runtime reproducibility

- `partial`

Notes:

- active mortality looks plausibly reproducible once AV-referenced external
  sources are loaded
- full runtime build is not started yet for `txtrs-av`

### B. Source-faithful reconstruction of the valuation basis

- `no`

Notes:

- plan-specific retiree mortality tables are not yet in hand
- `Scale UMP 2021` implementation remains ambiguous

## 7. Classification

- `blocked by both missing source and implementation ambiguity`

## 8. Decision / Next Step

- `acquire missing external source`

Decision notes:

- do not treat the current `txtrs` compatibility mortality path as source-
  faithful by default
- acquire the plan-specific healthy-pensioner tables and confirm the intended
  `Scale UMP 2021` implementation before claiming a source-faithful
  `txtrs-av` mortality rebuild

## 9. Related Artifacts

- mortality mapping note:
  - analogous TXTRS pilot note at [prep/txtrs/reports/mortality_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/mortality_mapping.md)
- external-source requirements note:
  - analogous TXTRS pilot note at [prep/txtrs/reports/external_source_requirements.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/external_source_requirements.md)
- issue links:
  - [#52](https://github.com/donboyd5/pension_model/issues/52)
