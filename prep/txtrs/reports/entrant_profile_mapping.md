# TXTRS Entrant Profile Mapping Notes

## Purpose

This note records the current understanding of the TXTRS entrant-profile source
and how it relates to the current runtime artifact.

## Source Found In The Valuation

Source:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
  - Appendix 2, printed p. 68

The valuation includes a section titled:

- `NEW ENTRANT PROFILE`

And publishes a summary table with:

- entry-age bands
- number of employees
- average salary

The table is explicitly described as the basis for the open-group projection
used in the funding-period calculation.

## What The Valuation Publishes

Published summary rows include:

- `15-19` with `859` employees and average salary `$25,003`
- `20-24` with `49,665` employees and average salary `$47,410`
- `25-29` with `85,761` employees and average salary `$51,659`
- ...
- `65-69` with `2,372` employees and average salary `$39,321`
- total `393,267` employees and overall average salary `$49,694`

The valuation also says:

- the profile is created from valuation data using members with eight or less
  years of service
- salaries are normalized to the valuation date
- 25.9% of the population is male
- future new-hire salaries grow at general wage inflation of 2.90%

## How This Compares To The Current Runtime Artifact

Current runtime artifact:

- [plans/txtrs/data/demographics/entrant_profile.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/data/demographics/entrant_profile.csv)

Current canonical columns:

- `entry_age`
- `start_salary`
- `entrant_dist`

The current runtime file is **not** a direct transcription of the valuation
summary table.

Examples:

- runtime uses single ages such as `20`, `25`, `30`, ... rather than age bands
- runtime distributions do not match a simple normalization of the published
  age-band counts
- runtime start salaries do not match the published band-average salaries
  one-for-one

## Current Working Interpretation

The valuation does publish a usable entrant-profile source basis, but not in the
same exact shape as the current runtime artifact.

So the correct classification is:

- source exists
- runtime artifact is `derived`

Not:

- fully missing from PDFs

## Implication For Prep

For TXTRS, `entrant_profile.csv` should now be treated as a source-grounded
build artifact.

That means the remaining task is not “find any source at all,” but:

- identify the build rule from the valuation’s banded entrant profile to the
  runtime’s single-age canonical form

Possible build-rule candidates to evaluate later:

- use band lower bounds
- use band midpoints
- spread band counts across ages within each band
- use a richer valuation data table if another source section publishes one

The right answer should be whatever exactly reproduces the current reviewed
stage-3 artifact, or else reveals that the current artifact came from a richer
legacy source than the PDF summary.
