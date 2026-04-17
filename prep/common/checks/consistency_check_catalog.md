# Consistency Check Catalog

## Purpose

This catalog defines the shared validation checks that input-prep artifacts
should support.

The checks are organized by layer:

- source-table checks
- cross-table checks
- canonical-artifact checks
- runtime-equivalence checks

These checks are upstream prep checks. They are separate from occasional
end-to-end model runs.

## Check Status Categories

Each check result should eventually carry a status such as:

- `pass`
- `fail`
- `warning`
- `not_applicable`
- `not_yet_implemented`

## 1. Source-Table Checks

These apply to extracted or manually keyed source tables before normalization.

### ST-001 Row totals reconcile

- Purpose: detail rows sum to reported row total
- Typical use: age bands, benefit types, payroll subtotals
- Failure meaning: extraction error, OCR issue, source ambiguity, or document inconsistency

### ST-002 Column totals reconcile

- Purpose: detail columns sum to reported column total
- Typical use: years-of-service columns, class columns, tier columns

### ST-003 Grand total reconciles

- Purpose: table grand total matches reported total
- Typical use: membership, payroll, benefit-payment tables

### ST-004 Monetary scaling is explicit

- Purpose: source monetary units are identified and converted to dollars explicitly
- Typical use: tables reported in thousands or millions
- Failure meaning: canonical outputs risk unit drift

### ST-005 Percent / rate arithmetic is consistent

- Purpose: reported percentages, contribution-rate components, or funded-ratio components reconcile
- Typical use: contribution schedules, funded-ratio discussions, asset-allocation tables

### ST-006 Duplicate or conflicting extracted rows are flagged

- Purpose: prevent silent duplication when one source table is extracted twice or split oddly across pages

## 2. Cross-Table Checks

These compare related source or normalized artifacts.

### CT-001 Active headcount reconciles to reported total

- Purpose: summed active headcount from detailed tables agrees with published active-member total for the relevant scope and year
- Important note: scope and date must match before comparing

### CT-002 Payroll reconciles to reported total

- Purpose: payroll implied by salary/headcount or payroll matrices agrees with reported payroll total
- Important note: check whether payroll is DB-only, system-wide, midpoint-adjusted, or valuation payroll

### CT-003 Retiree count reconciles to reported total

- Purpose: retiree distribution totals agree with published retiree or annuitant totals

### CT-004 Benefit payments reconcile to reported totals

- Purpose: retiree distribution or class benefit totals agree with reported annual benefit-payment totals

### CT-005 Class totals reconcile to plan total

- Purpose: sum of class-level artifacts equals plan-level artifact where both exist
- Typical use: FRS class payrolls or AAL totals

### CT-006 AV-versus-ACFR comparison is documented

- Purpose: similar concepts in AV and ACFR are compared and any differences are explained or accepted
- Important note: a difference is not automatically an error

### CT-007 Source-year alignment is explicit

- Purpose: when the reviewed runtime baseline aligns to a historical column rather than the latest published year, that choice is explicit
- Example: FRS config values matching the 2022 ACFR column rather than 2023

## 3. Canonical-Artifact Checks

These apply after normalization or build into canonical prep/runtime artifacts.

### CA-001 Required columns present

- Purpose: artifact schema matches required columns and names

### CA-002 Value domains valid

- Purpose: values are in valid ranges
- Examples:
  - rates between 0 and 1 where required
  - ages within configured range
  - years of service within configured range
  - counts nonnegative

### CA-003 Key uniqueness holds

- Purpose: canonical key columns uniquely identify rows
- Examples:
  - `(age, yos)` in salary/headcount grids
  - `(age, tier, retire_type)` in retirement rates

### CA-004 No silent missing required cells

- Purpose: required key ranges are complete or missingness is explicit

### CA-005 Units match canonical contract

- Purpose: canonical outputs use required units
- Examples:
  - money in dollars
  - rates in decimal form
  - counts unscaled

### CA-006 Monotonic or shape expectations hold where actuarially expected

- Purpose: catch obvious structural mistakes without overfitting
- Examples:
  - improvement-scale direction checks
  - reduction-factor bounds
  - impossible retirement-rate spikes caused by extraction errors

### CA-007 Provenance metadata complete enough for review

- Purpose: artifact has source IDs, page/table references, units, and transform method where applicable

## 4. Runtime-Equivalence Checks

These compare prep-produced runtime artifacts to the currently reviewed runtime
files.

### RE-001 Exact file equivalence

- Purpose: generated artifact matches current canonical runtime artifact exactly
- Primary use: FRS and TXTRS pilot acceptance

### RE-002 Numeric equivalence within approved tolerance

- Purpose: compare values when file formatting differences are unavoidable
- Requirement: tolerance must be explicit and justified

### RE-003 Canonical config equivalence

- Purpose: source-linked portions of `plan_config.json` match reviewed runtime config
- Important note: runtime-only fields should be excluded or compared separately

### RE-004 Coverage gaps explicitly listed

- Purpose: any artifact that cannot be reproduced directly from PDFs is listed with its gap status and fallback method

## 5. Shared External Reference Checks

These apply to common sources such as SOA mortality tables.

### ER-001 Reference source hash recorded

- Purpose: shared reference tables are tied to a specific source file/version

### ER-002 Reference-to-canonical mapping documented

- Purpose: mapping from external reference tables to plan/runtime mortality artifacts is explicit

### ER-003 Licensing or reuse constraints noted

- Purpose: future reproducibility is not blocked by undocumented access constraints

## Implementation Guidance

- Start with the checks that directly reduce reproducibility risk:
  - ST-004
  - CT-001
  - CT-002
  - CT-007
  - CA-005
  - CA-007
  - RE-001
- Treat scope mismatches as first-class. Many false failures come from comparing:
  - DB-only to system-wide
  - June 30 to July 1
  - valuation payroll to financial-statement payroll
- A failed check should produce a short, reviewable explanation rather than a silent boolean.
