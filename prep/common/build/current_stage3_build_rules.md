# Current Stage-3 Build Rules

## Purpose

This note summarizes how the current repo’s canonical stage-3 demographic and
decrement artifacts were built from the legacy FRS and TXTRS sources.

It is not a source-first workflow. It is a description of the current canonical
shape that a future PDF-first prep workflow must reproduce.

Primary references:

- [scripts/build/convert_frs_to_stage3.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/convert_frs_to_stage3.py)
- [scripts/build/convert_txtrs_to_stage3.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/convert_txtrs_to_stage3.py)
- [docs/termination_rate_design.md](/home/donboyd5/Documents/python_projects/pension_model/docs/termination_rate_design.md)

## Shared Pattern

Across both plans, current stage-3 artifacts are mostly built by:

1. reading plan-specific raw matrices or tables
2. reshaping them into tidy long-format CSVs
3. normalizing column names and units
4. preserving only the runtime lookup structure needed by the model

That means many runtime artifacts are already one abstraction step away from the
source tables.

## FRS Build Rules

### Salary and headcount

Current source shape:

- wide matrices by age with one column per YOS bucket

Current build rule:

- melt to long format
- output columns:
  - salary: `age`, `yos`, `salary`
  - headcount: `age`, `yos`, `count`
- drop zeros and missing values

Artifacts:

- `plans/frs/data/demographics/{class}_salary.csv`
- `plans/frs/data/demographics/{class}_headcount.csv`

### Salary growth

Current source shape:

- one table with `yos` and one salary-increase column per class

Current build rule:

- if all classes share the same salary-growth values, write one shared file
- otherwise write one file per class

Current FRS runtime shape is class-specific:

- `plans/frs/data/demographics/{class}_salary_growth.csv`

### Retiree distribution

Current source shape:

- one table with retiree count and benefit columns

Current build rule:

- standardize to:
  - `age`
  - `count`
  - `avg_benefit`
  - `total_benefit`

Artifact:

- `plans/frs/data/demographics/retiree_distribution.csv`

### Termination rates

Current source shape:

- years-of-service rows
- age-group columns

Current build rule:

- expand age groups to individual ages
- keep years of service as the lookup variable
- canonical columns:
  - `lookup_type = yos`
  - `age`
  - `lookup_value`
  - `term_rate`

Important implication:

- the canonical runtime table is already an expansion of grouped source logic,
  not a direct transcription of a printed table

### Retirement rates

Current source shape:

- separate files by class, tier, and retirement type

Current build rule:

- combine into one file per class with:
  - `age`
  - `tier`
  - `retire_type`
  - `retire_rate`

Artifacts:

- `plans/frs/data/decrements/{class}_retirement_rates.csv`

### Mortality

Current source shape:

- standard external Pub-2010 and MP-2018 workbooks

Current build rule:

- write `base_rates.csv` in long format:
  - `age`
  - `gender`
  - `member_type`
  - `table`
  - `qx`
- write `improvement_scale.csv` in long format:
  - `age`
  - `year`
  - `gender`
  - `improvement`

## TXTRS Build Rules

### Salary and headcount

Current source shape:

- Excel matrices read through the TXTRS loader

Current build rule:

- melt wide matrices to long format
- standardize to:
  - salary: `age`, `yos`, `salary`
  - headcount: `age`, `yos`, `count`
- drop zeros and missing values

Artifacts:

- `plans/txtrs/data/demographics/all_salary.csv`
- `plans/txtrs/data/demographics/all_headcount.csv`

### Salary growth

Current source shape:

- one table returned by the TXTRS loader

Current build rule:

- rename the value column to `salary_increase`
- keep `yos`

Artifact:

- `plans/txtrs/data/demographics/salary_growth.csv`

### Entrant profile

Current source shape:

- entrant counts and starting salaries from the legacy workbook

Current build rule:

- compute `entrant_dist = count / sum(count)`
- standardize to:
  - `entry_age`
  - `start_salary`
  - `entrant_dist`

Artifact:

- `plans/txtrs/data/demographics/entrant_profile.csv`

This is important because it shows the current canonical artifact is not just a
copied table. It includes a derived distribution.

### Retiree distribution

Current build rule:

- standardize to:
  - `age`
  - `count`
  - `avg_benefit`
  - `total_benefit`

Artifact:

- `plans/txtrs/data/demographics/retiree_distribution.csv`

### Termination rates

Current source shape is structurally different from FRS:

- years of service for early-career members
- years from normal retirement for later-career members

Current build rule:

- combine both structures into one canonical file
- canonical columns:
  - `lookup_type`
  - `age`
  - `lookup_value`
  - `term_rate`

Current lookup types:

- `yos`
- `years_from_nr`

This is one of the best examples of preserving actuarial structure rather than
forcing everything into one flat age-only table.

### Retirement rates

Current source shape:

- raw TXTRS retirement rates are not split by runtime tiers

Current build rule:

- output one file with:
  - `age`
  - `tier = all`
  - `retire_type`
  - `retire_rate`

The runtime then applies tier-specific logic on top of these raw rates.

### Early-retirement reduction tables

TXTRS has two distinct reduction structures:

- grandfathered members:
  YOS-by-age matrix
- others:
  simple age-to-factor table

Current build rules:

- `reduction_gft.csv` is melted from wide to long with:
  - `age`
  - `yos`
  - `reduce_factor`
  - `tier = grandfathered`
- `reduction_others.csv` keeps the simpler age-based structure

### Mortality

Current source shape:

- Pub-2010 amount-weighted teacher below-median workbook sheet
- MP-2021 workbook

Current build rule:

- write `base_rates.csv` with one table label:
  - `teacher_below_median`
- write `improvement_scale.csv` from MP-2021 male/female sheets

This is a runtime-compatibility representation, not necessarily a complete
source-faithful expression of the valuation’s full mortality basis.

## Implication For PDF-First Prep

The future PDF-first prep workflow should not aim to reproduce the legacy raw
files. It should aim to reproduce the canonical stage-3 artifacts **using these
build rules or approved replacements for them**.

That means each artifact needs two things:

1. source coverage and provenance
2. a reviewed transformation rule into canonical runtime shape

## Current Most Important Build-Rule Gaps

- FRS funding-seed compatibility rules, especially DB/DC payroll splits
- FRS class-level benefit-payment allocation rules
- TXTRS entrant-profile reconstruction from source-first documents
- TXTRS source-faithful retiree mortality reconstruction
