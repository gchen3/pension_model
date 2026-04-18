# TXTRS-AV First-Year Cash-Flow Review

## Plan And Source Context

- Plan: `txtrs-av`
- Baseline year: `2024`
- Valuation report used:
  - [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20Valuation%202024.pdf)
- ACFR used:
  - not yet copied into `prep/txtrs-av/`
- Other source documents used:
  - none yet for this first pass

## 1. Observed-Year Source Tables

| Source family | Document | Printed page | PDF page | Table / section | Scope | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| valuation funding table | AV_2024 | `17` | `24` | Table 2 `Summary of Cost Items` | participant counts, gross normal cost, AAL | Core valuation anchors. |
| valuation funding table | AV_2024 | `19` | `26` | Table 3b `Calculation of Covered Payroll` | covered payroll | Covered payroll basis. |
| valuation funding table | AV_2024 | `26` | `33` | Table 8a `Change in Plan Net Assets` | benefit payments and asset-flow context | Direct benefit-payment anchor. |
| ACFR deductions table | not yet in local `txtrs-av` source set |  |  |  |  | Not needed for the first AV-first pass unless a later gap appears. |

## 2. Observed-Year Cash-Flow Categories

| Category | Source value | Units | Source location | Included in observed-year path? | Notes |
| --- | --- | --- | --- | --- | --- |
| benefit payments | `15,258,219,146` | dollars | AV Table 8a | yes | Strong first-cut anchor. |
| refunds | not yet isolated | dollars | not yet mapped | unknown | May need later review if the runtime benefit concept is narrower. |
| admin expense | not yet isolated | dollars | not yet mapped | unknown | Not needed for the first-cut benefit-payment anchor. |
| transfers / disbursements to other plan components | not yet isolated | dollars | not yet mapped | unknown | Keep explicit if later evidence shows they matter. |
| employee contributions | valuation/statutory context present | dollars or rates | AV funding tables and statutory summary | yes | Rate and contribution context are source-supported. |
| employer DB contributions | valuation/statutory context present | dollars or rates | AV funding tables and statutory summary | yes | Source-supported. |
| employer DC contributions | not clearly in first-cut pension trust scope |  |  | no | Should not be assumed without explicit source support. |
| other |  |  |  |  |  |

## 3. Year-0 Identity Checks

| Identity name | Formula | Expected value | Actual value | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| valuation benefit-payment anchor | `init_funding.benefit_payments == AV Table 8a benefit payments` | `15,258,219,146` | not built yet | pending | First-cut identity to preserve. |
| valuation covered payroll anchor | `init_funding.total_payroll == AV Table 3b covered payroll` | source-supported | not built yet | pending | Covered payroll should remain on the valuation basis. |
| valuation AAL anchor | `init_funding.total_aal == AV Table 2 AAL` | source-supported | not built yet | pending | First-cut funding seed should reconcile directly. |

## 4. Conceptual Classification

Answer to the main question:

- the first-cut observed-year benefit-payment input should be treated as a
  direct valuation benefit-payment anchor, not as a broad ACFR deductions proxy

Classification:

- `direct benefit payments`

Reasoning:

- the valuation already publishes a direct plan-wide benefit-payment figure in
  Table 8a
- `txtrs-av` is one broad class, so the main FRS-style class-allocation problem
  is not the first issue to solve here
- the AV-first rule argues against importing a broader proxy when a direct
  valuation anchor is already available

## 5. Later-Year Contrast

| Item | Year 0 treatment | Later-year treatment | Same concept? | Notes |
| --- | --- | --- | --- | --- |
| benefit payments | valuation anchor from Table 8a | modeled benefit payments | mostly yes | Still worth checking whether refunds or other disbursements need separate handling later. |
| refunds | not yet isolated | modeled separately if needed | unknown | Later review item. |
| admin expense | not yet isolated | modeled separately if needed | unknown | Later review item. |
| net cash flow | valuation/accounting identity | modeled projection identity | not necessarily | Conceptual differences should be documented if they matter. |

## 6. AV-First Assessment

Assessment:

- `AV-faithful`

Justification:

- the first proposed year-0 benefit-payment anchor comes directly from the
  valuation rather than from an auxiliary ACFR proxy

## 7. Decision

Decision:

- `keep and adopt as preferred method`

Decision notes:

- for the first-cut `txtrs-av` funding seed, use the valuation's direct
  benefit-payment figure
- revisit only if later artifact-building requires more granular year-0 cashflow
  treatment than the valuation alone supports

## 8. Open Questions

- Are refunds or other year-0 disbursement categories needed separately in the
  first runtime build?
- Does any later-year runtime concept diverge materially from the valuation's
  year-0 benefit-payment presentation?

## 9. Related Artifacts

- plan narrative:
  - [narrative_plan_analysis.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/reports/narrative_plan_analysis.md)
- issue links:
  - none yet specific to `txtrs-av`
